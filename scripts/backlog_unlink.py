#!/usr/bin/env python3
"""
backlog_unlink.py — 撤销 backlog_backfill.py --apply 的改动

用途:
  backlog_backfill.py 算法在某轮 apply 产生误关联时,本脚本一次性回滚:
    - 新建的 task md(tags 含 auto-from-backlog)→ 整文件删除
    - 已有 task md 加的 5 个 backlog_* 字段 → 字段全删
    - 时间戳门槛 --since 之前的不动(保留更早的合法 link)

CLI:
  python3 backlog_unlink.py --since 2026-06-05T02:58 [--apply]

  默认 dry-run。--apply 才真改。

例外保护:
  --keep 'file1.md,file2.md' 显式排除某些文件不动(如已推飞书的测试 task)。
"""

import argparse
import re
import sys
from pathlib import Path

from backlog_to_task import DEFAULT_VAULT, DEFAULT_TASK_DIR

BACKLOG_FIELDS = [
    "backlog_source",
    "backlog_path",
    "backlog_priority",
    "backlog_status_seen",
    "backlog_synced_at",
]

# 新建判定:中间件给 task md tags 加的标记
AUTO_FROM_BACKLOG_TAG = "auto-from-backlog"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--vault", default=str(DEFAULT_VAULT))
    parser.add_argument("--task-dir", default=DEFAULT_TASK_DIR)
    parser.add_argument("--since", required=True,
                        help="时间戳门槛,backlog_synced_at >= 此值才算本次改动(格式 'YYYY-MM-DDTHH:MM')")
    parser.add_argument("--keep", default="",
                        help="逗号分隔的文件名,显式保留不动")
    parser.add_argument("--apply", action="store_true", help="真改文件(默认 dry-run)")
    args = parser.parse_args()

    vault = Path(args.vault).resolve()
    task_dir = vault / args.task_dir
    keep_set = {n.strip() for n in args.keep.split(",") if n.strip()}

    if not task_dir.is_dir():
        sys.stderr.write(f"⛔ task 目录不存在: {task_dir}\n")
        sys.exit(2)

    deleted_files = []
    unlinked_files = []
    preserved_files = 0
    not_touched = 0

    for md in sorted(task_dir.glob("*.md")):
        if md.name in keep_set:
            preserved_files += 1
            continue
        if ".bak" in md.name or md.name.endswith(".tmp"):
            not_touched += 1
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            not_touched += 1
            continue

        # 没 backlog_synced_at 字段 → 跳过(没被 backfill 动过)
        m = re.search(r"^backlog_synced_at:\s*(\S+)", text, re.MULTILINE)
        if not m:
            not_touched += 1
            continue
        synced_at = m.group(1).strip()
        if synced_at < args.since:
            preserved_files += 1
            continue

        # 判断是否新建(tags 含 auto-from-backlog)
        is_new = AUTO_FROM_BACKLOG_TAG in text

        if is_new:
            deleted_files.append(md)
            if args.apply:
                md.unlink()
        else:
            unlinked_files.append(md)
            if args.apply:
                new_text = text
                for field in BACKLOG_FIELDS:
                    new_text = re.sub(rf"^{re.escape(field)}:[^\n]*\n", "", new_text, flags=re.MULTILINE)
                tmp = md.with_suffix(".md.tmp")
                tmp.write_text(new_text, encoding="utf-8")
                tmp.replace(md)

    prefix = "✅ DONE" if args.apply else "🟡 DRY-RUN"
    print(f"\n{prefix} backlog_unlink — since {args.since}\n")
    print(f"删除文件({'已执行' if args.apply else '将'}): {len(deleted_files)}")
    for p in deleted_files[:20]:
        print(f"  🗑 {p.name}")
    if len(deleted_files) > 20:
        print(f"  ...另 {len(deleted_files) - 20} 个省略\n")

    print(f"\n解关联({'已执行' if args.apply else '将'}): {len(unlinked_files)}")
    for p in unlinked_files[:20]:
        print(f"  ↩️  {p.name}")
    if len(unlinked_files) > 20:
        print(f"  ...另 {len(unlinked_files) - 20} 个省略\n")

    print(f"\n保留(显式 keep / 时间戳早于 --since): {preserved_files}")
    print(f"未触及(无 backlog_synced_at 字段): {not_touched}")

    if not args.apply:
        print("\n💡 --apply 真改。检查清单 OK 后跑:")
        print(f'    python3 {Path(__file__).name} --since "{args.since}" --keep "{args.keep}" --apply')


if __name__ == "__main__":
    main()
