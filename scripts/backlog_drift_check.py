#!/usr/bin/env python3
"""
backlog_drift_check.py v0.1.0 — 布丁 backlog ↔ OB task md 漂移检测

用途:
  扫 vault task md 与 zhixing-game backlog 双向对比,识别 4 类漂移并出周报。
  设计用于定时(cron / launchd 每周日 21:00)或手动 `--apply` 半自动修。

4 类漂移:
  1. status 漂移:task md 的 backlog_status_seen ≠ 当前 backlog status
                  (例:backlog 改成 done 了,task md 还显示 doing)
  2. 孤儿 task:task md 有 backlog_source 字段但对应 backlog 文件已不存在
                (backlog 被重命名 / 删除)
  3. 孤儿 backlog:backlog 文件存在但 vault 无对应 task md
                  (中间件没触发 / 历史未回填)
  4. 重复 task:多个 task md 引用同一 backlog slug
                (回填 / 中间件 race condition 导致)

模式:
  默认  → 只输出周报到 stdout + 文件
  --apply → 自动修「status 漂移」(更新 task md 的 backlog_status_seen 字段
            跟当前 backlog status 对齐),孤儿 / 重复仍只报告不动文件
  --auto-create-orphan-backlog → 孤儿 backlog 自动调中间件补建 task md
            (相当于 backlog_to_task.py --scan 但只针对没对应的)

报告位置:
  默认 → ~/.claude/reports/backlog-drift-YYYY-WNN.md

紧急关闭:
  BACKLOG_TO_TASK_DISABLE=1 → 任何修改都不做(报告仍生成)
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("❌ 需要 PyYAML: pip install pyyaml\n")
    sys.exit(1)

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))
from backlog_to_task import (  # noqa
    parse_frontmatter,
    format_yaml_value,
    derive_slug,
    derive_today_iso,
    SKIP_BACKLOG_PATTERNS,
    DEFAULT_VAULT,
    DEFAULT_TASK_DIR,
    DEFAULT_BACKLOG_DIR,
    DEFAULT_LOG_DIR,
    BEIJING_TZ,
    sync_one,
)


# ============================================================
# 扫描:vault 端 + backlog 端,建索引
# ============================================================

def scan_vault_task_md(vault_root, task_subdir):
    """扫 vault 04 Inbox/task/*.md,找含 backlog_source 字段的 task,建索引。

    返回:
        by_slug: {slug: [task_md_path, ...]}  (重复检测用)
        all_linked: [(task_md_path, slug, backlog_status_seen, backlog_priority)]
    """
    task_dir = vault_root / task_subdir
    by_slug = defaultdict(list)
    all_linked = []
    if not task_dir.is_dir():
        return by_slug, all_linked

    src_re = re.compile(r'^backlog_source:\s*"?\[\[([^\]]+)\]\]"?', re.MULTILINE)
    for md in sorted(task_dir.glob("*.md")):
        if ".bak" in md.name or md.name.endswith(".tmp"):
            continue
        try:
            with md.open("r", encoding="utf-8") as f:
                head = "".join(f.readline() for _ in range(150))
        except Exception:
            continue
        m = src_re.search(head)
        if not m:
            continue
        slug = m.group(1).strip()
        by_slug[slug].append(md)
        fm, _ = parse_frontmatter(head + "\n---\n")  # head 已含 fm,补 --- 让 parser 不爆
        if fm is None:
            fm = {}
        all_linked.append((
            md,
            slug,
            str(fm.get("backlog_status_seen", "") or "").strip(),
            str(fm.get("backlog_priority", "") or "").strip(),
        ))
    return by_slug, all_linked


def scan_backlog(backlog_dir):
    """扫 zhixing-game backlog 目录,返回 {slug: {path, current_status, current_priority, fm}}"""
    backlog_dir = Path(backlog_dir)
    out = {}
    if not backlog_dir.is_dir():
        return out
    for p in sorted(backlog_dir.glob("*.md")):
        if SKIP_BACKLOG_PATTERNS.search(p.name):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        fm, _ = parse_frontmatter(text)
        if fm is None:
            fm = {}
        slug = derive_slug(p)
        out[slug] = {
            "path": p,
            "status": str(fm.get("status", "") or "").strip(),
            "priority": str(fm.get("priority", "") or "").strip(),
            "fm": fm,
        }
    return out


# ============================================================
# 4 类漂移识别
# ============================================================

def detect_drifts(by_slug, all_linked, backlog_index):
    """返回 4 个 list:status_drift / orphan_task / orphan_backlog / dup_task"""
    status_drift = []   # (task_md, slug, old_status_seen, new_status_in_backlog)
    orphan_task = []    # (task_md, slug)  — task 有 backlog_source 但 backlog 不存在
    orphan_backlog = [] # (backlog_path, slug)  — backlog 存在但 vault 无 task
    dup_task = []       # (slug, [task_md, ...])  — N>1 个 task 指向同一 slug

    # status_drift + orphan_task
    for md, slug, status_seen, priority_seen in all_linked:
        if slug not in backlog_index:
            orphan_task.append((md, slug))
            continue
        cur = backlog_index[slug]["status"]
        if status_seen and cur and status_seen != cur:
            status_drift.append((md, slug, status_seen, cur))

    # dup_task
    for slug, mds in by_slug.items():
        if len(mds) > 1:
            dup_task.append((slug, mds))

    # orphan_backlog
    linked_slugs = set(by_slug.keys())
    for slug, info in backlog_index.items():
        if slug not in linked_slugs:
            orphan_backlog.append((info["path"], slug))

    return status_drift, orphan_task, orphan_backlog, dup_task


# ============================================================
# 修「status 漂移」— append-only 更新 task md 的 backlog_status_seen
# ============================================================

def fix_status_drift(task_md_path, new_status, dry_run):
    text = task_md_path.read_text(encoding="utf-8")
    fm_match = re.match(r"^---\n(.*?)\n---\n?", text, re.DOTALL)
    if not fm_match:
        return False, "no_frontmatter"
    fm_str = fm_match.group(1)
    fm_end = fm_match.end()

    val = format_yaml_value(new_status)
    line_re = re.compile(r"^backlog_status_seen:[^\n]*$", re.MULTILINE)
    if line_re.search(fm_str):
        fm_str = line_re.sub(f"backlog_status_seen: {val}", fm_str)
    else:
        fm_str = fm_str.rstrip() + f"\nbacklog_status_seen: {val}"

    # 同步更新 backlog_synced_at
    synced_at = derive_today_iso()
    line_re2 = re.compile(r"^backlog_synced_at:[^\n]*$", re.MULTILINE)
    if line_re2.search(fm_str):
        fm_str = line_re2.sub(f"backlog_synced_at: {synced_at}", fm_str)
    else:
        fm_str = fm_str.rstrip() + f"\nbacklog_synced_at: {synced_at}"

    new_text = "---\n" + fm_str + "\n---\n" + text[fm_end:]
    if dry_run:
        return True, "would_update"
    tmp = task_md_path.with_suffix(".md.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(task_md_path)
    return True, "updated"


# ============================================================
# 标孤儿 task — 加 backlog_orphaned: true 字段
# ============================================================

def mark_orphan_task(task_md_path, dry_run):
    text = task_md_path.read_text(encoding="utf-8")
    fm_match = re.match(r"^---\n(.*?)\n---\n?", text, re.DOTALL)
    if not fm_match:
        return False, "no_frontmatter"
    fm_str = fm_match.group(1)
    fm_end = fm_match.end()

    line_re = re.compile(r"^backlog_orphaned:[^\n]*$", re.MULTILINE)
    if line_re.search(fm_str):
        # 已标过
        return True, "already_marked"
    fm_str = fm_str.rstrip() + "\nbacklog_orphaned: true"

    new_text = "---\n" + fm_str + "\n---\n" + text[fm_end:]
    if dry_run:
        return True, "would_mark"
    tmp = task_md_path.with_suffix(".md.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(task_md_path)
    return True, "marked"


# ============================================================
# 报告生成
# ============================================================

def build_report(status_drift, orphan_task, orphan_backlog, dup_task,
                 by_slug, backlog_index, week_label, apply_mode):
    lines = []
    now = derive_today_iso()
    lines.append(f"# 🔄 布丁 backlog ↔ OB task 漂移报告 — {week_label}\n\n")
    lines.append(f"生成时间: `{now}` | 模式: **{'apply' if apply_mode else 'report-only'}**\n\n")

    # 概览
    lines.append("## 📊 概览\n\n")
    lines.append(f"- backlog 总数: **{len(backlog_index)}**\n")
    lines.append(f"- 已镜像 task md 总数: **{len(by_slug)}**\n")
    lines.append(f"- 镜像匹配: **{len(by_slug) - len(orphan_task)}**\n")
    lines.append(f"- 漂移项总数: **{len(status_drift) + len(orphan_task) + len(orphan_backlog) + len(dup_task)}**\n\n")

    # 健康度
    total = max(len(backlog_index), 1)
    healthy = total - len(status_drift) - len(orphan_backlog)
    pct = healthy / total
    flag = "🟢" if pct >= 0.9 else ("🟡" if pct >= 0.7 else "🔴")
    lines.append(f"健康度: {flag} **{int(pct * 100)}%**({healthy} / {total} 对齐)\n\n")
    lines.append("---\n\n")

    # status 漂移
    lines.append(f"## 1️⃣ status 漂移({len(status_drift)})\n\n")
    if status_drift:
        lines.append("task md 的 `backlog_status_seen` ≠ 当前 backlog status。\n")
        if apply_mode:
            lines.append("✅ 已自动更新 `backlog_status_seen` 跟最新 backlog 对齐。\n\n")
        else:
            lines.append("💡 `--apply` 会自动更新 `backlog_status_seen` 字段(不动 task 自己的 status)。\n\n")
        for md, slug, old, new in status_drift:
            lines.append(f"- **[[{slug}]]**: `{old}` → `{new}`(task: `{md.name}`)\n")
        lines.append("\n")
    else:
        lines.append("✅ 无 status 漂移\n\n")

    # 孤儿 task
    lines.append(f"## 2️⃣ 孤儿 task({len(orphan_task)})\n\n")
    if orphan_task:
        lines.append("task md 有 `backlog_source` 但对应 backlog 文件不存在(可能 backlog 已重命名 / 删除)。\n")
        lines.append("💡 不级联删,建议手动 review;`--apply` 会在 task frontmatter 标 `backlog_orphaned: true`。\n\n")
        for md, slug in orphan_task:
            lines.append(f"- task: `{md.name}` → 缺失 backlog `[[{slug}]]`\n")
        lines.append("\n")
    else:
        lines.append("✅ 无孤儿 task\n\n")

    # 孤儿 backlog
    lines.append(f"## 3️⃣ 孤儿 backlog({len(orphan_backlog)})\n\n")
    if orphan_backlog:
        lines.append("backlog 文件存在但 vault 无对应 task md。可能是:\n")
        lines.append("- 中间件没触发(hook 关了 / userscript 没接)\n")
        lines.append("- 历史 backlog 还没 backfill\n\n")
        lines.append("💡 `--auto-create-orphan-backlog` 会调中间件补建。也可手动跑:\n")
        lines.append("```bash\npython3 scripts/backlog_backfill.py --apply --auto-accept-threshold 0.55\n```\n\n")
        # 按 priority 分组展示
        by_pri = defaultdict(list)
        for path, slug in orphan_backlog:
            pri = backlog_index.get(slug, {}).get("priority", "?")
            by_pri[pri].append((path, slug))
        for pri in sorted(by_pri.keys()):
            lines.append(f"### {pri}({len(by_pri[pri])})\n\n")
            for path, slug in by_pri[pri][:30]:
                status = backlog_index.get(slug, {}).get("status", "?")
                lines.append(f"- `{slug}`(status={status})\n")
            if len(by_pri[pri]) > 30:
                lines.append(f"- ...另 {len(by_pri[pri]) - 30} 条省略\n")
            lines.append("\n")
    else:
        lines.append("✅ 无孤儿 backlog\n\n")

    # 重复 task
    lines.append(f"## 4️⃣ 重复 task({len(dup_task)})\n\n")
    if dup_task:
        lines.append("多个 task md 引用同一 backlog slug(可能 backfill / 中间件 race condition)。\n")
        lines.append("💡 人工 review 合并 — 不自动改。\n\n")
        for slug, mds in dup_task:
            lines.append(f"- **[[{slug}]]** ({len(mds)} 条):\n")
            for md in mds:
                lines.append(f"  - `{md.name}`\n")
        lines.append("\n")
    else:
        lines.append("✅ 无重复 task\n\n")

    return "".join(lines)


# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="布丁 backlog ↔ OB task md 漂移检测 v0.1.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--vault", default=str(DEFAULT_VAULT))
    parser.add_argument("--task-dir", default=DEFAULT_TASK_DIR)
    parser.add_argument("--backlog-dir", default=str(DEFAULT_BACKLOG_DIR))
    parser.add_argument("--week", default=None,
                        help="周标签(默认 YYYY-WNN 自动算)")
    parser.add_argument("--report-file", default=None,
                        help="报告位置(默认 ~/.claude/reports/backlog-drift-YYYY-WNN.md)")
    parser.add_argument("--apply", action="store_true",
                        help="自动修 status 漂移 + 标孤儿 task(不动正文)")
    parser.add_argument("--auto-create-orphan-backlog", action="store_true",
                        help="孤儿 backlog 自动调中间件补建 task md(等于跑 backlog_to_task.py 那条 slug)")
    args = parser.parse_args()

    if os.environ.get("BACKLOG_TO_TASK_DISABLE") == "1":
        sys.stderr.write("⏸  BACKLOG_TO_TASK_DISABLE=1,任何修改都不做(但报告仍生成)\n")
        args.apply = False
        args.auto_create_orphan_backlog = False

    vault_root = Path(args.vault).resolve()
    if not vault_root.is_dir():
        sys.stderr.write(f"⛔ vault 不存在: {vault_root}\n")
        sys.exit(2)

    now = datetime.now(BEIJING_TZ)
    week_label = args.week or now.strftime("%Y-W%V")

    if args.report_file:
        report_file = Path(args.report_file)
    else:
        report_file = Path.home() / ".claude/reports" / f"backlog-drift-{week_label}.md"

    # 扫
    by_slug, all_linked = scan_vault_task_md(vault_root, args.task_dir)
    backlog_index = scan_backlog(args.backlog_dir)
    sys.stderr.write(f"📂 vault 已镜像 task md: {len(by_slug)} 条\n")
    sys.stderr.write(f"📂 backlog: {len(backlog_index)} 条\n")

    # 检测
    status_drift, orphan_task, orphan_backlog, dup_task = detect_drifts(
        by_slug, all_linked, backlog_index
    )

    # 修(--apply)
    fixed_status = 0
    marked_orphan = 0
    created_orphan = 0
    if args.apply:
        for md, slug, old, new in status_drift:
            ok, _ = fix_status_drift(md, new, dry_run=False)
            if ok:
                fixed_status += 1
        for md, slug in orphan_task:
            ok, _ = mark_orphan_task(md, dry_run=False)
            if ok:
                marked_orphan += 1

    if args.auto_create_orphan_backlog:
        for path, slug in orphan_backlog:
            try:
                ok, detail = sync_one(
                    path, vault_root, args.task_dir,
                    dry_run=False, log_dir=DEFAULT_LOG_DIR,
                )
                if ok and ("created" in detail or "would_create" in detail):
                    created_orphan += 1
            except Exception as e:
                sys.stderr.write(f"❌ {slug} 补建失败: {e}\n")

    # 报告
    report = build_report(
        status_drift, orphan_task, orphan_backlog, dup_task,
        by_slug, backlog_index, week_label, args.apply,
    )
    if args.apply or args.auto_create_orphan_backlog:
        report += "\n---\n\n## 📝 --apply 执行汇总\n\n"
        report += f"- 修 status 漂移: **{fixed_status}**\n"
        report += f"- 标孤儿 task(`backlog_orphaned: true`): **{marked_orphan}**\n"
        report += f"- 孤儿 backlog 自动补建 task md: **{created_orphan}**\n"

    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(report, encoding="utf-8")
    sys.stderr.write(f"\n📝 报告: {report_file}\n")

    # stdout 总结
    print(f"\n📊 漂移检测完成 — {week_label}")
    print(f"  status 漂移: {len(status_drift)}{' (已修 ' + str(fixed_status) + ')' if args.apply else ''}")
    print(f"  孤儿 task: {len(orphan_task)}{' (已标 ' + str(marked_orphan) + ')' if args.apply else ''}")
    print(f"  孤儿 backlog: {len(orphan_backlog)}{' (已补建 ' + str(created_orphan) + ')' if args.auto_create_orphan_backlog else ''}")
    print(f"  重复 task: {len(dup_task)}")


if __name__ == "__main__":
    main()
