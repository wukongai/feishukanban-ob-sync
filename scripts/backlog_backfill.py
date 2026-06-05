#!/usr/bin/env python3
"""
backlog_backfill.py v0.1.0 — 历史 backlog ↔ task md 关系回填

用途:
  Phase 1 的 backlog_to_task.py 中间件只处理"新创建的 backlog"(走 create / update 路径)。
  历史 170+ 条 backlog 与 100+ 条 task md 之间没有显式关联字段(backlog_source / backlog_path)。
  本脚本一次性扫描两边,主题模糊匹配,给每条 backlog 找现有 task 或新建 task md。

三档模式:
  --report-only  只生成对账表(stdout + 报告文件),不动文件
  --dry-run      模拟动作,显示会做什么(默认)
  --apply        真改文件(给已有 task 补 backlog_source / 给孤儿 backlog 新建 task md)

模糊匹配启发式:
  1. backlog 标题关键词 vs task md 标题关键词,Jaccard 相似度
  2. backlog tags vs task md tags 交集
  3. backlog created date vs task md created date 时间窗 ±30 天
  综合得分 ≥ 阈值才判定为"匹配"

交互模式(--interactive):
  对每条潜在匹配,prompt y/n/skip 让用户人工 confirm

设计原则:
  - 默认 dry-run / 非交互模式输出对账表;真改用 --apply
  - 主题匹配是启发式,不准确(已 done 的 task 主题可能跟某条 backlog 接近但不真对应)
  - 报告输出到 stdout + 落地文件,方便用户审阅
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("❌ 需要 PyYAML: pip install pyyaml\n")
    sys.exit(1)

# 复用 backlog_to_task 的 helpers
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))
from backlog_to_task import (  # noqa
    parse_frontmatter,
    format_yaml_value,
    derive_slug,
    derive_title,
    derive_today_iso,
    parse_estimate_hours,
    build_task_md,
    create_task_md as middleware_create_task_md,
    update_existing_task as middleware_update_existing_task,
    find_existing_task,
    PRIORITY_MAP,
    SKIP_BACKLOG_PATTERNS,
    DEFAULT_VAULT,
    DEFAULT_TASK_DIR,
    DEFAULT_BACKLOG_DIR,
    DEFAULT_LOG_DIR,
)


# ============================================================
# 主题模糊匹配
# ============================================================

# 中文停用词 / task 通用前缀(影响关键词分布)
STOP_TOKENS = {
    "的", "了", "和", "与", "及", "对", "在", "为", "是", "也",
    "task", "功能", "优化", "修复", "v1", "v2", "v3", "bug",
    "布丁开发", "布丁内容", "ob", "内容工厂",
    "P0", "P1", "P2", "P3", "optim", "idea", "unrated", "fix",
    "md", "需求", "需要", "完成", "实现", "新建",
}

TOKEN_PATTERN = re.compile(r"[\w\-]+", re.UNICODE)


def tokenize(text):
    """切词 + 去停用词 + 截短"""
    if not text:
        return set()
    text = str(text).lower()
    # 把【...】这种全去掉
    text = re.sub(r"【[^】]*】", " ", text)
    text = re.sub(r"\[\[[^\]]+\]\]", " ", text)
    tokens = TOKEN_PATTERN.findall(text)
    # 加上 1-3 字中文片段(用滑动窗口拆中文)
    chinese_text = re.sub(r"[^一-鿿]+", " ", str(text))
    for chunk in chinese_text.split():
        if 2 <= len(chunk) <= 6:
            tokens.append(chunk)
        # 2-char window
        for i in range(len(chunk) - 1):
            tokens.append(chunk[i:i + 2])
    return {t for t in tokens if t and t not in STOP_TOKENS and len(t) >= 2}


def title_similarity(bl_title, tk_title):
    """多维度标题相似度 — Jaccard / contains / LCS / chunk overlap 取 max。
    对中文短主题更鲁棒。"""
    bl = (bl_title or "").lower().strip()
    tk = (tk_title or "").lower().strip()
    if not bl or not tk:
        return 0.0

    # 1. Jaccard tokens
    bl_tokens = tokenize(bl_title)
    tk_tokens = tokenize(tk_title)
    jaccard = 0.0
    if bl_tokens and tk_tokens:
        jaccard = len(bl_tokens & tk_tokens) / max(len(bl_tokens | tk_tokens), 1)

    # 2. Containment(单向包含)
    contain_score = 0.0
    if bl in tk:
        contain_score = len(bl) / max(len(tk), 1)
    elif tk in bl:
        contain_score = len(tk) / max(len(bl), 1)

    # 3. 最长公共连续子串 LCS substring
    longest = ""
    for i in range(len(bl)):
        for j in range(len(tk)):
            k = 0
            while i + k < len(bl) and j + k < len(tk) and bl[i + k] == tk[j + k]:
                k += 1
            if k > len(longest):
                longest = bl[i:i + k]
    lcs_score = len(longest) / max(min(len(bl), len(tk)), 1) if longest and len(longest) >= 2 else 0.0

    # 4. 共享 ≥ 2 字 chunks 数(中文关键词命中数)
    shared_chunks = [t for t in bl_tokens & tk_tokens if len(t) >= 2]
    chunk_score = min(1.0, len(shared_chunks) / 3.0)

    return max(jaccard, contain_score, lcs_score, chunk_score)


def extract_task_title(task_md_path, task_fm, task_body):
    """从 task md 抽多种 title:H1 / 文件名(去日期前缀)"""
    h1 = ""
    m = re.search(r"^#\s+(.+?)$", task_body, re.MULTILINE)
    if m:
        h1 = re.sub(r"^【[^】]*】", "", m.group(1).strip()).strip()
    # 文件名:2026-05-26-【布丁开发】功能：日常习惯打卡.md → 功能：日常习惯打卡
    fname = task_md_path.stem
    fname = re.sub(r"^\d{4}-\d{2}-\d{2}-?", "", fname)
    fname = re.sub(r"^【[^】]*】", "", fname).strip()
    return h1, fname


def fuzzy_score(backlog_fm, backlog_body, backlog_slug, task_md_path):
    """对一对 (backlog, task md) 算综合相似度 score ∈ [0, 1]。

    title 维度用 H1 / 文件名两路对比,取最大;tag / time 加成保持。
    title 权重提高到 0.7(从 0.6),让标题主导匹配。"""
    try:
        task_text = task_md_path.read_text(encoding="utf-8")
    except Exception:
        return 0.0
    task_fm, task_body = parse_frontmatter(task_text)
    if task_fm is None:
        task_fm = {}

    backlog_title = derive_title(backlog_fm, backlog_body, backlog_slug)
    tk_h1, tk_fname = extract_task_title(task_md_path, task_fm, task_body)

    # 两路 title 比对取最大
    title_score = max(
        title_similarity(backlog_title, tk_h1),
        title_similarity(backlog_title, tk_fname),
    )

    # tags 交集
    bl_tags = set(str(t).lower() for t in (backlog_fm.get("tags") or []))
    tk_tags = set(str(t).lower() for t in (task_fm.get("tags") or []))
    for noise in ("task", "auto-from-backlog", "pulled-from-backlog", "pulled-from-feishu", "backlog"):
        bl_tags.discard(noise)
        tk_tags.discard(noise)
    tag_score = 0.0
    if bl_tags and tk_tags:
        tag_score = len(bl_tags & tk_tags) / max(len(bl_tags | tk_tags), 1)

    # 时间窗(±60 天得 0.15 加成,放宽一点 — backlog 通常比 task 早建)
    time_score = 0.0
    try:
        bl_created = backlog_fm.get("created")
        tk_created = task_fm.get("created")
        if bl_created and tk_created:
            bl_dt = bl_created if isinstance(bl_created, datetime) else datetime.fromisoformat(str(bl_created)[:19])
            tk_dt = tk_created if isinstance(tk_created, datetime) else datetime.fromisoformat(str(tk_created)[:19])
            diff_days = abs((bl_dt - tk_dt).days)
            if diff_days <= 60:
                time_score = 0.15 * (1 - diff_days / 60)
    except Exception:
        pass

    # 综合:title 权重 0.7 + tag 0.15 + time 0.15
    score = 0.7 * title_score + 0.15 * tag_score + time_score
    return min(score, 1.0)


# ============================================================
# 给已有 task md 补 backlog_source 字段
# ============================================================

def link_existing_task(task_md_path, backlog_path, dry_run):
    """给已有 task md 加 backlog_source / backlog_path / backlog_priority /
    backlog_status_seen / backlog_synced_at,不动其它字段。"""
    text = task_md_path.read_text(encoding="utf-8")
    fm, _ = parse_frontmatter(text)
    if fm is None:
        return False, "no_frontmatter"

    backlog_fm, _ = parse_frontmatter(backlog_path.read_text(encoding="utf-8"))
    if backlog_fm is None:
        backlog_fm = {}
    slug = derive_slug(backlog_path)
    backlog_path_rel = f"docs/backlog/{backlog_path.name}"

    new_fields = {
        "backlog_source": f'"[[{slug}]]"',
        "backlog_path": backlog_path_rel,
        "backlog_priority": str(backlog_fm.get("priority", "")).strip(),
        "backlog_status_seen": str(backlog_fm.get("status", "")).strip(),
        "backlog_synced_at": derive_today_iso(),
    }

    # 已经有 backlog_source 字段 → 跳过(不覆盖)
    if fm.get("backlog_source"):
        return True, "already_linked"

    fm_match = re.match(r"^---\n(.*?)\n---\n?", text, re.DOTALL)
    if not fm_match:
        return False, "no_fm_block"
    fm_str = fm_match.group(1)
    fm_end = fm_match.end()

    # 加新字段(全部不存在就追加)
    additions = []
    for key, val in new_fields.items():
        line_re = re.compile(rf"^{re.escape(key)}:[^\n]*$", re.MULTILINE)
        if line_re.search(fm_str):
            fm_str = line_re.sub(f"{key}: {val}", fm_str)
        else:
            additions.append(f"{key}: {val}")
    if additions:
        fm_str = fm_str.rstrip() + "\n" + "\n".join(additions)

    new_text = "---\n" + fm_str + "\n---\n" + text[fm_end:]

    if dry_run:
        return True, f"would_link: + {list(new_fields.keys())}"

    tmp = task_md_path.with_suffix(".md.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(task_md_path)
    return True, f"linked: + {list(new_fields.keys())}"


# ============================================================
# 主流程
# ============================================================

def backfill(backlog_dir, vault_root, task_subdir, mode, fuzzy_threshold,
             auto_accept_threshold, interactive, log_dir, report_file):
    """
    mode: 'report-only' | 'dry-run' | 'apply'
    """
    backlog_dir = Path(backlog_dir)
    task_dir = vault_root / task_subdir
    if not backlog_dir.is_dir():
        sys.stderr.write(f"⛔ backlog 目录不存在: {backlog_dir}\n")
        return
    if not task_dir.is_dir():
        sys.stderr.write(f"⛔ vault task 目录不存在: {task_dir}\n")
        return

    dry_run = mode != "apply"
    task_files = [p for p in task_dir.glob("*.md") if ".bak" not in p.name and not p.name.endswith(".tmp")]
    sys.stderr.write(f"📂 vault task md 共 {len(task_files)} 条(用作模糊匹配候选)\n")

    backlogs = []
    for p in sorted(backlog_dir.glob("*.md")):
        if SKIP_BACKLOG_PATTERNS.search(p.name):
            continue
        backlogs.append(p)
    sys.stderr.write(f"📂 backlog 共 {len(backlogs)} 条\n\n")

    stats = {"already_linked": 0, "linked": 0, "would_link": 0,
             "created": 0, "would_create": 0, "skipped": 0,
             "ambiguous": 0, "error": 0}
    report_lines = []
    report_lines.append(f"# Backlog 历史回填对账报告 — {derive_today_iso()}\n")
    report_lines.append(f"模式: **{mode}**\n")
    report_lines.append(f"backlog 总数: {len(backlogs)} | task md 总数: {len(task_files)}\n")
    report_lines.append(f"模糊阈值: 提示阈值 = {fuzzy_threshold} / 自动接受阈值 = {auto_accept_threshold}\n\n")
    report_lines.append("---\n\n")

    for bl_path in backlogs:
        slug = derive_slug(bl_path)
        try:
            bl_text = bl_path.read_text(encoding="utf-8")
        except Exception as e:
            stats["error"] += 1
            sys.stderr.write(f"❌ {bl_path.name} 读取失败: {e}\n")
            continue
        bl_fm, bl_body = parse_frontmatter(bl_text)
        if bl_fm is None:
            bl_fm = {}

        # 1. find_existing_task:看 vault 已有任何 task md 含 backlog_source 字段命中
        existing_by_field = find_existing_task(vault_root, task_subdir, slug)
        if existing_by_field:
            stats["already_linked"] += 1
            report_lines.append(f"## ✅ 已有关联: `{slug}`\n")
            report_lines.append(f"   task: `{existing_by_field.name}`\n\n")
            continue

        # 2. 主题模糊匹配
        scored = []
        for tk in task_files:
            score = fuzzy_score(bl_fm, bl_body, slug, tk)
            if score >= fuzzy_threshold:
                scored.append((score, tk))
        scored.sort(key=lambda x: -x[0])

        report_lines.append(f"## `{slug}`(priority={bl_fm.get('priority', '?')} / status={bl_fm.get('status', '?')})\n")

        if not scored:
            # 无候选 → 新建 task md
            if mode == "report-only":
                stats["would_create"] += 1
                report_lines.append(f"   📌 无候选,**应新建** task md\n\n")
                continue
            ok, detail = middleware_create_task_md(
                vault_root, task_subdir, bl_fm, bl_body, bl_path, dry_run=dry_run
            )
            if ok:
                if dry_run:
                    stats["would_create"] += 1
                    report_lines.append(f"   📌 [dry-run] 新建:{detail}\n\n")
                else:
                    stats["created"] += 1
                    report_lines.append(f"   ✅ 已新建:{detail}\n\n")
            else:
                stats["error"] += 1
                report_lines.append(f"   ❌ 失败:{detail}\n\n")
            continue

        # 有候选
        top_score, top_task = scored[0]
        candidates_md = []
        for sc, tk in scored[:5]:
            candidates_md.append(f"   - `{tk.name}` (score={sc:.2f})")

        if top_score >= auto_accept_threshold:
            # 自动接受最优候选,补 backlog_source
            decision = "auto-accept"
        elif interactive:
            print(f"\n候选 backlog: {slug}")
            print(f"标题: {derive_title(bl_fm, bl_body, slug)}")
            print(f"  候选 task(score):")
            for sc, tk in scored[:3]:
                print(f"    [{sc:.2f}] {tk.name}")
            choice = input(f"  选哪个?(0=新建/1-{min(3, len(scored))}=选/s=跳过): ").strip().lower()
            if choice in ("s", "skip", ""):
                stats["skipped"] += 1
                report_lines.append(f"   ⏭ 用户跳过\n\n")
                continue
            if choice == "0":
                ok, detail = middleware_create_task_md(
                    vault_root, task_subdir, bl_fm, bl_body, bl_path, dry_run=dry_run
                )
                if ok and dry_run:
                    stats["would_create"] += 1
                elif ok:
                    stats["created"] += 1
                report_lines.append(f"   📌 用户选新建:{detail}\n\n")
                continue
            try:
                top_task = scored[int(choice) - 1][1]
                decision = "user-pick"
            except (ValueError, IndexError):
                stats["skipped"] += 1
                continue
        else:
            # 非交互 + 不到自动接受阈值 → 报告"待人工 review"
            stats["ambiguous"] += 1
            report_lines.append(f"   ⚠️ 候选不够确定(top={top_score:.2f}),待人工 review:\n")
            for line in candidates_md:
                report_lines.append(line + "\n")
            report_lines.append("\n")
            continue

        # 真正做链接(report-only 不动文件)
        if mode == "report-only":
            stats["would_link"] += 1
            report_lines.append(f"   📌 [{decision}] 关联到 `{top_task.name}` (score={top_score:.2f})\n\n")
            continue

        ok, detail = link_existing_task(top_task, bl_path, dry_run=dry_run)
        if ok:
            if dry_run:
                stats["would_link"] += 1
                report_lines.append(f"   📌 [dry-run / {decision}] {detail} → `{top_task.name}` (score={top_score:.2f})\n\n")
            else:
                stats["linked"] += 1
                report_lines.append(f"   ✅ [{decision}] {detail} → `{top_task.name}` (score={top_score:.2f})\n\n")
        else:
            stats["error"] += 1
            report_lines.append(f"   ❌ link 失败:{detail}\n\n")

    # 汇总
    summary = f"""
---

## 📊 汇总

- 已有 backlog_source 关联 (跳过): {stats['already_linked']}
- 真链接(给已有 task 加字段): {stats['linked']}
- dry-run 待链接: {stats['would_link']}
- 真新建 task md: {stats['created']}
- dry-run 待新建: {stats['would_create']}
- 跳过(用户/规则): {stats['skipped']}
- 待人工 review(候选不确定): {stats['ambiguous']}
- 错误: {stats['error']}
"""
    report_lines.append(summary)

    # 写报告
    if report_file:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text("".join(report_lines), encoding="utf-8")
        sys.stderr.write(f"\n📝 报告写到: {report_file}\n")

    print(summary)


def main():
    parser = argparse.ArgumentParser(
        description="布丁 backlog 历史回填 — 一次性给已有 task md 补 backlog_source 关联,或新建缺失的 task md",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--report-only", action="store_true", help="只生成对账报告,不动任何文件")
    mode.add_argument("--dry-run", action="store_true", help="模拟动作,显示会做什么(默认)")
    mode.add_argument("--apply", action="store_true", help="真改文件")
    parser.add_argument("--vault", default=str(DEFAULT_VAULT), help=f"vault 根目录(默认 {DEFAULT_VAULT})")
    parser.add_argument("--task-dir", default=DEFAULT_TASK_DIR)
    parser.add_argument("--backlog-dir", default=str(DEFAULT_BACKLOG_DIR))
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    parser.add_argument("--fuzzy-threshold", type=float, default=0.25,
                        help="提示阈值 — 低于此分不算候选(默认 0.25)")
    parser.add_argument("--auto-accept-threshold", type=float, default=0.55,
                        help="自动接受阈值 — 高于此分不问直接关联(默认 0.55)")
    parser.add_argument("--interactive", action="store_true",
                        help="对模糊匹配 prompt y/n/skip(仅 apply / dry-run 模式)")
    parser.add_argument("--report-file", default=None,
                        help="对账报告写到指定 md 文件路径(默认 ~/.claude/reports/backlog-backfill-YYYY-MM-DD.md)")
    args = parser.parse_args()

    if args.apply:
        mode_str = "apply"
    elif args.report_only:
        mode_str = "report-only"
    else:
        mode_str = "dry-run"

    vault_root = Path(args.vault).resolve()
    log_dir = Path(args.log_dir)
    report_file = Path(args.report_file) if args.report_file else (
        Path.home() / ".claude/reports" / f"backlog-backfill-{datetime.now().strftime('%Y-%m-%d-%H%M')}.md"
    )

    if not vault_root.is_dir():
        sys.stderr.write(f"⛔ vault 不存在: {vault_root}\n")
        sys.exit(2)

    backfill(
        backlog_dir=args.backlog_dir,
        vault_root=vault_root,
        task_subdir=args.task_dir,
        mode=mode_str,
        fuzzy_threshold=args.fuzzy_threshold,
        auto_accept_threshold=args.auto_accept_threshold,
        interactive=args.interactive,
        log_dir=log_dir,
        report_file=report_file,
    )


if __name__ == "__main__":
    main()
