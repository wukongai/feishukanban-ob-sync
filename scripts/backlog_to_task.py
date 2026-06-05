#!/usr/bin/env python3
"""
backlog_to_task.py v0.1.0 — 布丁 backlog ↔ OB task md 自动镜像中间件

输入:zhixing-game/docs/backlog/<slug>.md 路径(或 --scan 扫全目录)
输出:OB vault 04 Inbox/task/<YYYY-MM-DD>-【布丁开发】<title>.md(新建或更新映射字段)

设计原则:
  - 不调飞书 API(只动本地 task md)
  - 不动 user-managed 字段(status / today / adhd_priority / feishu_record / done_date 等)
  - 幂等:同一 backlog 重复同步,有 task md 走 update(只刷 backlog_* 镜像字段),无走 create
  - 默认 dry-run,显式 --apply 才写文件
  - 失败有 stderr 日志,exit 0 不阻塞调用方(hook / userscript)

模式:
  python3 backlog_to_task.py --backlog <绝对路径>        # 单文件同步(hook/userscript 调)
  python3 backlog_to_task.py --backlog X --apply         # 真改
  python3 backlog_to_task.py --scan                      # 全目录扫描(漂移检测 / 兜底)
  python3 backlog_to_task.py --scan --apply              # 全量补建

环境变量:
  BACKLOG_TO_TASK_DISABLE=1  → 整条同步关闭(紧急 kill switch)

依赖:
  Python 3.8+ / PyYAML
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("❌ 需要 PyYAML: pip install pyyaml\n")
    sys.exit(1)


# ============================================================
# 默认配置
# ============================================================

DEFAULT_VAULT = Path.home() / "Documents/OB"
DEFAULT_TASK_DIR = "04 Inbox/task"
DEFAULT_BACKLOG_DIR = Path.home() / "Documents/CodingProject/zhixing-game/docs/backlog"
DEFAULT_LOG_DIR = Path.home() / ".claude/logs"

# task md 标题前缀 / 项目挂靠
TASK_TITLE_PREFIX = "【布丁开发】"
PARENT_PROJECT = "[[布丁开发]]"

# backlog priority → task priority 映射(task 只支持 P0-P3)
PRIORITY_MAP = {
    "P0": "P0",
    "P1": "P1",
    "P2": "P2",
    "P3": "P3",
    "optim": "P3",
    "idea": "P3",
    "unrated": "P3",
    "fix": "P2",
}

# backlog status → task status 映射(task 7 态:todo/doing/subdone/done/block/cancel/idea)
# 2026-06-05:Phase 4 backfill 发现 23 条已 done 的 backlog 被建为 task status=todo,污染需求池。
# 让中间件读 backlog status 镜像到 task,避免假"待办"。
BACKLOG_STATUS_TO_TASK_STATUS = {
    "done": "done",
    "shelved": "cancel",
    "superseded": "cancel",
    "cancel": "cancel",
    "cancelled": "cancel",
    "doing": "doing",
    "in_progress": "doing",
    "active": "doing",
    "drafting": "doing",
    "partial": "doing",
    "paused": "block",
    "block": "block",
    "blocked": "block",
    "idea": "idea",
    # 默认(backlog / todo / open / pending / ready / unrated 等):"todo"
}

# backlog 文件名跳过(不是真需求,只是规范文档)
SKIP_BACKLOG_PATTERNS = re.compile(r"(README|_index|\.bak)", re.IGNORECASE)


# ============================================================
# frontmatter 解析(简化版,只读不改;改用 append-only regex)
# ============================================================

def parse_frontmatter(text):
    """返回 (frontmatter dict 或 None, 正文 str)"""
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if not m:
        return None, text
    try:
        fm = yaml.safe_load(m.group(1))
        if not isinstance(fm, dict):
            fm = {}
        return fm, m.group(2)
    except yaml.YAMLError as e:
        sys.stderr.write(f"⚠️  frontmatter YAML 解析失败: {e}\n")
        return None, text


def format_yaml_value(value):
    """生成 YAML 字段值字符串(给 append-only 改字段用)"""
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        if not value:
            return "[]"
        items = [format_yaml_value(v) for v in value]
        return "[" + ", ".join(items) + "]"
    s = str(value)
    # 已经是 wikilink "[[xxx]]" 或含 yaml 特殊字符 → 加引号
    if s.startswith("[[") and s.endswith("]]"):
        return f'"{s}"'
    if any(c in s for c in [":", "#", "&", "*", "?", "|", ">", "!", "%", "@", "`"]):
        return f'"{s}"'
    return s


# ============================================================
# slug / title / 字段抽取
# ============================================================

def derive_slug(backlog_path):
    return Path(backlog_path).stem


def derive_title(fm, body, slug):
    """优先 frontmatter.title → H1 → slug 去前缀"""
    if fm and fm.get("title"):
        return str(fm["title"]).strip()
    m = re.search(r"^#\s+(.+?)$", body, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return re.sub(r"^(P[0-3]|optim|idea|unrated|fix)-", "", slug)


def derive_today_iso():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def derive_today_date():
    return datetime.now().strftime("%Y-%m-%d")


def parse_estimate_hours(estimate_str):
    """把 backlog estimate 解析成小时数。
    支持 '1h' / '2-3h' / '5~7天' / '1~2周' / '30 min' 等粗略写法。
    区间取上限,失败返回空字符串。
    """
    if not estimate_str:
        return ""
    s = str(estimate_str).strip().lower()
    nums = re.findall(r"(\d+(?:\.\d+)?)", s)
    if not nums:
        return ""
    n = float(nums[-1])  # 区间取大,如 '1-2h' → 2
    if "周" in s or "week" in s:
        n *= 40
    elif "天" in s or "day" in s:
        n *= 8
    elif "min" in s or "分" in s:
        n /= 60
    # 默认小时
    return n if n != int(n) else int(n)


# ============================================================
# 查找已有 task md(幂等性核心)
# ============================================================

def find_existing_task(vault_root, task_subdir, slug):
    """grep vault task 目录里的 backlog_source / backlog_path 命中"""
    task_dir = vault_root / task_subdir
    if not task_dir.is_dir():
        return None
    slug_re = re.escape(slug)
    src_pattern = re.compile(rf'^backlog_source:\s*"?\[\[{slug_re}\]\]"?', re.MULTILINE)
    path_pattern = re.compile(rf'^backlog_path:.*{slug_re}\.md', re.MULTILINE)
    for md in sorted(task_dir.glob("*.md")):
        if ".bak" in md.name or md.name.endswith(".tmp"):
            continue
        try:
            # 只读头部(frontmatter 通常 < 80 行)
            with md.open("r", encoding="utf-8") as f:
                head = "".join(f.readline() for _ in range(120))
        except Exception:
            continue
        if src_pattern.search(head) or path_pattern.search(head):
            return md
    return None


# ============================================================
# 新建 task md
# ============================================================

def build_task_md(backlog_fm, body, slug, title, backlog_path_rel):
    """套模板拼新 task md 全文本。
    跟 obsidian-assets/templates/task-template.md 字段对齐 + 新增 5 个 backlog_* 字段。
    """
    today_iso = derive_today_iso()
    backlog_priority = str(backlog_fm.get("priority", "")).strip()
    backlog_status = str(backlog_fm.get("status", "")).strip()
    task_priority = PRIORITY_MAP.get(backlog_priority, "P3")
    # 镜像 backlog status → task status(默认 todo)
    task_status = BACKLOG_STATUS_TO_TASK_STATUS.get(backlog_status, "todo")
    # done 状态:抄 backlog 的 done_date,没有就填今天
    task_done_date = ""
    if task_status == "done":
        raw_dd = backlog_fm.get("done_date")
        if isinstance(raw_dd, str) and raw_dd.strip():
            task_done_date = raw_dd.strip()[:10]
        else:
            task_done_date = derive_today_date()
    estimate_hours = parse_estimate_hours(backlog_fm.get("estimate", ""))

    # created 字段:用 backlog 的 created,降级到现在
    created_raw = backlog_fm.get("created")
    if isinstance(created_raw, datetime):
        created_str = created_raw.strftime("%Y-%m-%dT%H:%M:%S")
    elif created_raw:
        # 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS' or 'YYYY-MM-DDTHH:MM:SS+...'
        created_str = str(created_raw)[:19]
    else:
        created_str = today_iso

    # tags 合并:task 基础标签 + backlog 标签(去重去冲突)
    backlog_tags = backlog_fm.get("tags") or []
    if not isinstance(backlog_tags, list):
        backlog_tags = []
    base_tags = ["task", "auto-from-backlog", "pulled-from-backlog"]
    merged_tags = base_tags + [str(t) for t in backlog_tags if str(t) not in base_tags + ["backlog"]]

    # related_spec → 正文相关资料区块
    related_lines = []
    for key in ("related_spec", "related_plan", "related_design", "related"):
        v = backlog_fm.get(key)
        if not v:
            continue
        items = v if isinstance(v, list) else [v]
        for r in items:
            r_str = str(r).strip().strip('"').strip("'")
            if r_str.startswith("[[") and r_str.endswith("]]"):
                related_lines.append(f"- {r_str}")
            else:
                # 路径形式 → 包成 wikilink
                related_lines.append(f"- [[{r_str}]]")
    related_block = "\n".join(related_lines) if related_lines else ""

    estimate_str = "" if estimate_hours == "" else str(estimate_hours)

    # tags YAML block list
    tags_yaml = "\n".join(f"  - {t}" for t in merged_tags)

    fm_block = f"""---
priority: {task_priority}
status: {task_status}
today: false
today_source:
today_source_history:
today_history: []
created: {created_str}
done_date: {task_done_date}
due:
category: 产品项目
subcategory:
project_minor:
adhd_priority:
estimate_hours: {estimate_str}
actual_hours:
efficiency:
quality:
parent_project: "{PARENT_PROJECT}"
parent_subproject:
parent_task:
parent_inspiration:
日志:
feishu_record:
feishu_url:
iteration_week: []
iteration_month: []
completion_month:
backlog_source: "[[{slug}]]"
backlog_path: {backlog_path_rel}
backlog_priority: {backlog_priority}
backlog_status_seen: {backlog_status}
backlog_synced_at: {today_iso}
tags:
{tags_yaml}
---"""

    body_block = f"""

# {TASK_TITLE_PREFIX}{title}

## 👥 用户故事
<!-- 同步到飞书「用户故事」字段。可选 -->

## ✅ 验收条件

## 💡 执行思路

## 📝 执行概述
(自动从 backlog 镜像 — 详情见上游 [[{slug}]])

## 📈 执行明细

## 📦 交付

## 🔗 相关资料
- 上游 backlog:[[{slug}]]
{related_block}

## 🪞 复盘

## ✅ 完成标记
- [ ] {TASK_TITLE_PREFIX}{title}
"""

    return fm_block + body_block


def create_task_md(vault_root, task_subdir, backlog_fm, body, backlog_path, dry_run):
    slug = derive_slug(backlog_path)
    title = derive_title(backlog_fm, body, slug)
    # 文件名清洗:剔除 / \ : * ? " < > | 等不安全字符
    safe_title = re.sub(r'[/\\:*?"<>|]', "_", title)[:60]
    date_str = derive_today_date()
    filename = f"{date_str}-{TASK_TITLE_PREFIX}{safe_title}.md"
    target_dir = vault_root / task_subdir
    target_path = target_dir / filename
    counter = 2
    while target_path.exists():
        target_path = target_dir / f"{date_str}-{TASK_TITLE_PREFIX}{safe_title}-{counter}.md"
        counter += 1
        if counter > 99:
            return False, "name_collision_too_many"

    backlog_path_rel = f"docs/backlog/{Path(backlog_path).name}"
    content = build_task_md(backlog_fm, body, slug, title, backlog_path_rel)

    if dry_run:
        return True, f"would_create: {target_path.name} ({len(content)} chars)"

    target_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_suffix(".md.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(target_path)
    return True, f"created: {target_path.name}"


# ============================================================
# 更新已有 task md(append-only,只动 backlog_* 镜像字段)
# ============================================================

UPDATE_FIELDS = [
    "backlog_priority",
    "backlog_status_seen",
    "backlog_synced_at",
    "backlog_path",
]


def update_existing_task(task_md_path, backlog_fm, backlog_path, dry_run):
    text = task_md_path.read_text(encoding="utf-8")
    fm, _ = parse_frontmatter(text)
    if fm is None:
        return False, "no_frontmatter"

    backlog_path_rel = f"docs/backlog/{Path(backlog_path).name}"

    new_values = {
        "backlog_priority": str(backlog_fm.get("priority", "")).strip(),
        "backlog_status_seen": str(backlog_fm.get("status", "")).strip(),
        "backlog_synced_at": derive_today_iso(),
        "backlog_path": backlog_path_rel,
    }

    # 只有值确实变了的字段才写(backlog_synced_at 例外,每次都更新)
    changes = {}
    for key, new_val in new_values.items():
        if key == "backlog_synced_at":
            changes[key] = new_val
            continue
        cur = str(fm.get(key, "") or "").strip()
        if cur != new_val:
            changes[key] = new_val

    # 漂移检测:status 变了要告警(留给 Phase 5 用)
    drift_note = ""
    cur_status_seen = str(fm.get("backlog_status_seen", "") or "").strip()
    new_status = new_values["backlog_status_seen"]
    if cur_status_seen and new_status and cur_status_seen != new_status:
        drift_note = f" [drift: status {cur_status_seen} → {new_status}]"

    if len(changes) == 1 and "backlog_synced_at" in changes:
        # 只更新时间戳,实质无变化 → 不动文件
        return True, f"nochange (just touch synced_at){drift_note}"

    # frontmatter append-only 改:正则替换已有 key,没有就追加在 --- 前
    fm_match = re.match(r"^---\n(.*?)\n---\n?", text, re.DOTALL)
    if not fm_match:
        return False, "no_fm_block"
    fm_str = fm_match.group(1)
    fm_end = fm_match.end()

    for key, val in changes.items():
        val_yaml = format_yaml_value(val)
        line_re = re.compile(rf"^{re.escape(key)}:[^\n]*$", re.MULTILINE)
        if line_re.search(fm_str):
            fm_str = line_re.sub(f"{key}: {val_yaml}", fm_str)
        else:
            fm_str = fm_str.rstrip() + f"\n{key}: {val_yaml}"

    new_text = "---\n" + fm_str + "\n---\n" + text[fm_end:]

    if dry_run:
        return True, f"would_update: {list(changes.keys())}{drift_note}"

    tmp_path = task_md_path.with_suffix(".md.tmp")
    tmp_path.write_text(new_text, encoding="utf-8")
    tmp_path.replace(task_md_path)
    return True, f"updated: {list(changes.keys())}{drift_note}"


# ============================================================
# 日志(JSON line)
# ============================================================

def log_action(slug, action, detail, dry_run, log_dir):
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        month = datetime.now().strftime("%Y-%m")
        log_file = log_dir / f"backlog-to-task-{month}.log"
        record = {
            "ts": derive_today_iso(),
            "slug": slug,
            "action": action,
            "detail": detail,
            "dry_run": dry_run,
        }
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 日志失败不阻塞主流程


# ============================================================
# 单文件同步入口
# ============================================================

def sync_one(backlog_path, vault_root, task_subdir, dry_run, log_dir):
    backlog_path = Path(backlog_path).resolve()
    if not backlog_path.is_file():
        sys.stderr.write(f"⛔ backlog 文件不存在: {backlog_path}\n")
        return False, "file_not_found"

    if SKIP_BACKLOG_PATTERNS.search(backlog_path.name):
        return True, "skip (README/_index/.bak)"

    text = backlog_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    if fm is None:
        fm = {}

    slug = derive_slug(backlog_path)
    existing = find_existing_task(vault_root, task_subdir, slug)

    if existing:
        ok, detail = update_existing_task(existing, fm, backlog_path, dry_run)
        action = "update"
    else:
        ok, detail = create_task_md(vault_root, task_subdir, fm, body, backlog_path, dry_run)
        action = "create"

    log_action(slug, action, detail, dry_run, log_dir)

    prefix = "🟡 dry-run" if dry_run else "✅"
    print(f"{prefix} [{action}] {slug} → {detail}")
    return ok, detail


# ============================================================
# 全目录扫描
# ============================================================

def scan_mode(backlog_dir, vault_root, task_subdir, dry_run, log_dir):
    backlog_dir = Path(backlog_dir)
    if not backlog_dir.is_dir():
        sys.stderr.write(f"⛔ backlog 目录不存在: {backlog_dir}\n")
        return

    stats = {"create": 0, "update": 0, "nochange": 0, "skip": 0, "error": 0, "drift": 0}
    for md in sorted(backlog_dir.glob("*.md")):
        if SKIP_BACKLOG_PATTERNS.search(md.name):
            stats["skip"] += 1
            continue
        try:
            ok, detail = sync_one(md, vault_root, task_subdir, dry_run, log_dir)
            if "would_create" in detail or detail.startswith("created"):
                stats["create"] += 1
            elif "would_update" in detail or detail.startswith("updated"):
                stats["update"] += 1
            elif "nochange" in detail:
                stats["nochange"] += 1
            else:
                stats["skip"] += 1
            if "drift:" in detail:
                stats["drift"] += 1
        except Exception as e:
            sys.stderr.write(f"❌ {md.name} 同步失败: {e}\n")
            stats["error"] += 1

    print()
    print("📊 扫描完成统计")
    print(f"  新建/将建: {stats['create']}")
    print(f"  更新/将更新: {stats['update']}")
    print(f"  无变化: {stats['nochange']}")
    print(f"  跳过(README/_index): {stats['skip']}")
    print(f"  错误: {stats['error']}")
    print(f"  status 漂移: {stats['drift']}")


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="布丁 backlog ↔ OB task md 自动镜像中间件 v0.1.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--backlog", help="单文件同步:backlog md 绝对路径")
    parser.add_argument("--scan", action="store_true", help="扫描模式:扫整个 backlog 目录")
    parser.add_argument("--vault", default=str(DEFAULT_VAULT),
                        help=f"vault 根目录(默认 {DEFAULT_VAULT})")
    parser.add_argument("--task-dir", default=DEFAULT_TASK_DIR,
                        help=f"vault 内 task 子目录(默认 '{DEFAULT_TASK_DIR}')")
    parser.add_argument("--backlog-dir", default=str(DEFAULT_BACKLOG_DIR),
                        help=f"backlog 目录(--scan 模式用)")
    parser.add_argument("--apply", action="store_true",
                        help="真改文件(默认 dry-run,不写文件)")
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR),
                        help=f"日志目录(默认 {DEFAULT_LOG_DIR})")
    args = parser.parse_args()

    # 紧急 kill switch
    if os.environ.get("BACKLOG_TO_TASK_DISABLE") == "1":
        print("⏸  BACKLOG_TO_TASK_DISABLE=1,中间件已禁用")
        sys.exit(0)

    dry_run = not args.apply
    vault_root = Path(args.vault).resolve()
    log_dir = Path(args.log_dir)

    if not vault_root.is_dir():
        sys.stderr.write(f"⛔ vault 不存在: {vault_root}\n")
        sys.exit(2)

    if args.backlog:
        sync_one(args.backlog, vault_root, args.task_dir, dry_run, log_dir)
    elif args.scan:
        scan_mode(args.backlog_dir, vault_root, args.task_dir, dry_run, log_dir)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
