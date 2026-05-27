#!/usr/bin/env python3
"""
Hook: PreToolUse(Bash) — 硬拦截复合 Bash 命令

设计来源:照搬 zhixing-game/.claude/hooks/prevent-bash-compound.py(2026-05-23 验证版),
精简白名单 + 改教育文案适配本项目(feishukanban-ob-sync)。

为什么硬拦截而不靠 CLAUDE.md 规则:
  zhixing-game 实证 2026-05-23 — 规则教育不可靠,Claude 自己也会违规
  (cd && / cat | head 等),升级为 hook 硬拦截。

拦截范围:
  A. cd 复合:cd /path && cmd / bash -c "cd ..."
  B. 管道:cmd1 | cmd2(含 ls | head / grep | head 等)
  C. 串联:cmd1 ; cmd2 / cmd1 && cmd2 / cmd1 || cmd2

白名单(允许复合):
  1) hook 自身:.claude/hooks/*.{sh,py}
  2) 引号内的特殊字符不算(git commit -m "fix: a | b")
"""

import json
import re
import sys

INPUT = sys.stdin.read()

try:
    data = json.loads(INPUT)
    cmd = data.get('tool_input', {}).get('command', '')
except Exception:
    sys.exit(0)

if not cmd:
    sys.exit(0)


# ============ 白名单 1:hook 自身调用 ============
# .claude/hooks/*.{sh,py} 内部可自由用复合(已经审过)
WHITELIST_PREFIX_PATTERNS = [
    r'^\s*\.claude/hooks/[a-z][a-z0-9\-]*\.(sh|py)',
    r'^\s*bash\s+\.claude/hooks/[a-z][a-z0-9\-]*\.sh',
    r'^\s*python3?\s+\.claude/hooks/[a-z][a-z0-9\-]*\.py',
]
for pat in WHITELIST_PREFIX_PATTERNS:
    if re.match(pat, cmd):
        sys.exit(0)


# 去掉引号内容(避免 git commit -m "fix: a | b" 之类的引号内字符误报)
# 用占位符 "" / '' 保留原长度,便于其他正则定位
clean = re.sub(r"'[^']*'", "''", cmd)
clean = re.sub(r'"[^"]*"', '""', clean)


# ============ 检测复合标志 ============
REASONS = []

# A. cd 复合(用 cmd 原文,精准检测)
if re.search(r'(^|[;&|]\s*)cd\s+[^;&|]+\s*(&&|\|\||;)', cmd):
    REASONS.append('cd 裸复合')
if re.search(r'(^|\s)(bash|sh|zsh)\s+(-[lic]+\s+)?["\'][^"\']*\bcd\s+', cmd):
    REASONS.append('bash -c "cd ..." 包装复合')

# B. 管道(用 clean,已去引号内容)
# 排除 || 和 |& 的情况
if re.search(r'(?<!\|)\|(?![|&])', clean):
    REASONS.append('管道 |')

# C. 串联(用 clean)
# 排除 find -exec ... \;(用 \; 终止)
if re.search(r'(?<!\\);', clean):
    REASONS.append('分号 ;')
if '&&' in clean:
    REASONS.append('&&')
if '||' in clean:
    REASONS.append('||')

if not REASONS:
    sys.exit(0)


# 去重(保留顺序)
seen = set()
REASONS_DEDUPED = []
for r in REASONS:
    if r not in seen:
        seen.add(r)
        REASONS_DEDUPED.append(r)


# ============ 拦截 + 给替代方案 ============
cmd_preview = cmd[:300] + ('...' if len(cmd) > 300 else '')
reasons_str = ', '.join(REASONS_DEDUPED)

print(f"""⛔ 已阻止:检测到复合 Bash 命令({reasons_str})

原文:{cmd_preview}

为什么拦:Claude Code allowlist 是字符串前缀匹配,复合命令(cd && / | / ; / && / ||)
几乎一定触发 permission 弹窗。参数稍变就重弹,越授权越脏。
zhixing-game 2026-05-23 实证:规则教育失败 — Claude 自己也会违规,升级为 hook 硬拦截。

【必须改写为以下之一】

1) 探测多个独立信息 → 拆成多个 Bash 调用(同一 message 内并行发)
   ❌ ls dir1 ; ls dir2 ; cat file1
   ✅ 一次 message 发 3 个 Bash tool_use:
      • Bash: ls dir1
      • Bash: ls dir2
      • Bash: cat file1(其实直接 Read 工具更好,见 2)

2) 读文件 / 看片段 → 用 Read 工具(强红线)
   ❌ cat /path/to/file 2>/dev/null | head -100
   ❌ tail -50 /path/to/log
   ❌ head -20 /path/to/file
   ✅ Read(file_path="/path/to/file", limit=100, offset=0)

3) 列目录限量 → 直接全列或用 Glob 工具
   ❌ ls /OB/04\\ Inbox/task/ | head -30
   ✅ ls /OB/04\\ Inbox/task/(30 个文件直接看,不需要 head)
   ✅ Glob(pattern="04 Inbox/task/*.md")

4) 跨仓库 / 跨目录 → 用 git -C / python3 --vault 等
   ❌ cd /path && git status
   ✅ git -C /path status
   ❌ cd /OB && python3 .../sync.py --pull-today
   ✅ python3 .../sync.py --vault /OB --pull-today(v0.3.1+ 已支持)

5) 搜文件名/内容 → 用 Glob / Grep 工具
   ❌ grep -l "X" /OB/journals/*.md 2>/dev/null | head -20
   ✅ Grep(pattern="X", path="/OB/journals", glob="*.md", output_mode="files_with_matches")

【白名单内的复合不拦】
- .claude/hooks/*.{{sh,py}} 自身

详见全局 ~/.claude/CLAUDE.md「Bash 命令写法约定」section。
""", file=sys.stderr)

sys.exit(2)