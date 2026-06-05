#!/usr/bin/env python3
"""
一次性 migration:task md 文件名【X_Y】→【X-Y】

背景(v0.7.11,2026-06-04):
  quickadd-快记任务-v2 v0.7.10 之前用 `/` 拼 category/subcategory →
  sanitize 把 `/` 替换 `_` → 文件名出现 `_` →
  journal dataview 渲染 wikilink `[[<file.path>|本地]]` 时,title (含_) +
  wikilink (含同一_) 在同一 markdown 字符串里两个 `_` 配对成 emphasis →
  wikilink 整体被破坏,渲染成原始文本。

本脚本:
  - 扫 vault `04 Inbox/task/*.md`(排除 .bak),把文件名里【...】块内的 `_` 替换成 `-`
  - 同步改文件内 H1 `# 【X_Y】...` + 完成标记段 `- [ ] 【X_Y】...`
  - 默认 dry-run,加 --apply 实际执行

不动:
  - frontmatter category / subcategory(值是单一类名,如「杂务」,本就无 `_`)
  - vault 其他 md 文件里的 wikilink 反向引用(初版假设没引用;有引用需手动跑 grep 兜底)

用法:
  python3 scripts/migrate_title_prefix_dash.py --vault /path/to/vault         # dry-run
  python3 scripts/migrate_title_prefix_dash.py --vault /path/to/vault --apply # 真改
"""
import argparse
import re
import sys
from pathlib import Path

# 匹配【...】块。文件名内只会出现 `_`(sanitize 把 `/` 变 _);
# 文件内文(H1 / 完成标记)用的是 titleTrimmed,可能含 `/` 也可能含 `_`。
BRACKET_BLOCK_RE = re.compile(r"【([^【】]+)】")


def normalize_bracket(text: str, chars: str) -> str:
    """text 里所有【...】块,块内出现的 chars 任意字符 → -;块外不动。"""
    def repl(m):
        inside = m.group(1)
        for c in chars:
            inside = inside.replace(c, "-")
        return f"【{inside}】"
    return BRACKET_BLOCK_RE.sub(repl, text)


def rewrite_filename(name: str) -> str:
    """文件名层面:【...】块内的 _ → -。"""
    return normalize_bracket(name, "_")


def rewrite_body_line(line: str) -> str:
    """文件内 H1 / 完成标记行层面:【...】块内的 / 和 _ 都 → -。"""
    return normalize_bracket(line, "/_")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--vault", required=True, type=Path, help="OB vault root 绝对路径")
    p.add_argument("--task-dir", default="04 Inbox/task", help="vault 内 task 目录(相对 vault root)")
    p.add_argument("--apply", action="store_true", help="实际改;不带 = dry-run")
    args = p.parse_args()

    vault = args.vault.resolve()
    task_dir = vault / args.task_dir
    if not task_dir.is_dir():
        print(f"❌ 找不到 task 目录: {task_dir}", file=sys.stderr)
        return 1

    # 收集 candidates(.md,排除 .bak)
    candidates = []
    for f in sorted(task_dir.glob("*.md")):
        if ".bak" in f.name:
            continue
        new_name = rewrite_filename(f.name)
        if new_name != f.name:
            candidates.append((f, task_dir / new_name))

    if not candidates:
        print("✅ 没有要 migration 的 task md(文件名【...】块内无 `_`)")
        return 0

    mode = "🚀 应用" if args.apply else "🔍 dry-run"
    print(f"{mode}:待处理 {len(candidates)} 个 task md\n")

    for old, new in candidates:
        print(f"  📁 {old.name}")
        print(f"  →  {new.name}")
        # 预览文件内 H1 + 完成标记段会怎么改
        try:
            text = old.read_text()
        except Exception as e:
            print(f"     ⚠️  读不了文件: {e}")
            print()
            continue
        # 扫所有要改的行(H1 / 完成标记段 - [ ] / - [x] 行)
        changed_lines = []
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            is_h1 = stripped.startswith("# ") and not stripped.startswith("##")
            is_task = stripped.startswith("- [") and "】" in line
            if is_h1 or is_task:
                new_line = rewrite_body_line(line)
                if new_line != line:
                    changed_lines.append((i, line, new_line))
        if changed_lines:
            print(f"     文件内 {len(changed_lines)} 行将改写:")
            for ln, old_l, new_l in changed_lines:
                print(f"       L{ln}: {old_l.strip()[:80]}")
                print(f"          → {new_l.strip()[:80]}")
        else:
            print(f"     ⚠️  文件内没找到 H1 / 完成标记行(可能模板被改过)")
        print()

    if not args.apply:
        print("⚠️  当前 dry-run。确认无误后加 --apply 实际执行。")
        return 0

    # ===== apply =====
    print(f"🚀 开始应用...\n")
    for old, new in candidates:
        text = old.read_text()
        # 改 H1 / 完成标记行(只改这两类,body 不动)
        new_lines = []
        body_changed = False
        for line in text.splitlines(keepends=True):
            stripped = line.lstrip()
            is_h1 = stripped.startswith("# ") and not stripped.startswith("##")
            is_task = stripped.startswith("- [") and "】" in line
            if is_h1 or is_task:
                new_line = rewrite_body_line(line)
                if new_line != line:
                    body_changed = True
                new_lines.append(new_line)
            else:
                new_lines.append(line)
        if body_changed:
            old.write_text("".join(new_lines))
            print(f"  ✏️  改文件内 H1/完成标记: {old.name}")

        # 重命名
        if new.exists():
            print(f"  ⚠️  目标已存在,跳过 rename:{new.name}")
            continue
        old.rename(new)
        print(f"  📁 改名: {old.name} → {new.name}")

    print(f"\n✅ 完成 {len(candidates)} 个 task md migration")
    print(f"\n💡 后续手动检查:")
    print(f"   1. OB 内打开几个改名后的 task md,确认 H1 + 完成标记段 OK")
    print(f"   2. 飞书项目看板对应 record 的「OB 备份路径」字段(如有)需手动更新")
    print(f"   3. 真打开今日 journal,确认 dataview wikilink 渲染成可点击「本地」")
    return 0


if __name__ == "__main__":
    sys.exit(main())
