---
title: Bash 命令写法约定
type: engineering
status: active
created: 2026-05-28
updated: 2026-05-28
tags: [规范, bash, permission, allowlist]
related: ["[[README]]", "[[../../.claude/CLAUDE.md]]"]
---

# Bash 命令写法约定

> 来源:全局 `~/.claude/CLAUDE.md`「Bash 命令写法约定」+ 本项目 `.claude/hooks/prevent-bash-compound.py` 硬拦截。
>
> 目的:减少 Claude Code permission 弹窗噪音 + 让命令在 CC 环境跑顺。

---

## 1. 核心约束

**禁止 `cd /path && <cmd>` 复合命令**。

CC 的 allowlist 是字符串前缀匹配,`cd` 开头会**绕过所有规则**,连 `ls` / `grep` 这种默认 auto-allow 的命令也会弹 permission 授权窗。

**项目内有硬拦截**:`.claude/hooks/prevent-bash-compound.py` 在 PreToolUse 阶段检测复合命令(管道 `|` / `&&` / `;` / `||` / `cd && ...`)→ 直接阻止,提示替代写法。

---

## 2. 替代写法

### ❌ → ✅ 对照表

| 错误写法 | 正确写法 |
|---|---|
| `ls /path/ \| head -30` | `ls /path/`(直接全列)+ 用 Read/Glob 工具替代 head |
| `grep -l "X" file* \| head -20` | Grep 工具:`pattern="X"`, `glob="*.md"`, `output_mode="files_with_matches"` |
| `cat /path/to/file \| head -100` | Read 工具:`file_path="/path/to/file"`, `limit=100`, `offset=0` |
| `cd /path && git status` | `git -C /path status` |
| `cd /path && python3 sync.py` | `python3 /path/sync.py --vault /path`(v0.3.1+ 支持 `--vault` flag) |
| `DB_URL="..." pg_dump` | 让 shell 已有 env 处理:`pg_dump $DB_URL`(env 前缀绕过 allowlist 规则) |
| `cmd1 ; cmd2 ; cmd3` | 拆成 3 个 Bash tool 调用(同一 message 内并行发) |

### 探测多个独立信息

❌ 不要:
```bash
ls /dir1 ; ls /dir2 ; cat /file3
```

✅ 要(一个 message 内并行 3 个 Bash tool_use):
- Bash: `ls /dir1`
- Bash: `ls /dir2`
- Read tool: `/file3`(优先用 Read 工具,见 §3)

### 读文件内容

❌ 不要 `cat` / `head` / `tail`:
```bash
cat /path/to/file 2>/dev/null | head -100
tail -50 /path/to/log
head -20 /path/to/file
```

✅ 用 **Read 工具**:
```
Read(file_path="/path/to/file", limit=100, offset=0)
```

Read 工具支持 `limit` + `offset`,功能完整覆盖 head/tail。

### 搜文件名/内容

❌ 不要 `grep -l` + pipe:
```bash
grep -l "X" /OB/journals/*.md 2>/dev/null | head -20
```

✅ 用 **Grep 工具**:
```
Grep(pattern="X", path="/OB/journals", glob="*.md", output_mode="files_with_matches")
```

### 跨仓库 / 跨目录 git 操作

❌ 不要 `cd /path && git`:
```bash
cd /path && git status
```

✅ 用 `git -C`:
```bash
git -C /path status
```

`git -C <dir>` 是 git 原生 flag,语义等价于「在该目录执行」但命令开头还是 `git`,allowlist 规则继续生效。

### 跨 vault 跑 sync.py

❌ 不要 `cd OB && python3 sync.py`:
```bash
cd /OB && python3 /Users/aim5/Documents/CodingProject/feishukanban-ob-sync/sync.py --pull-today
```

✅ v0.3.1+ 用 `--vault` flag:
```bash
python3 /Users/aim5/Documents/CodingProject/feishukanban-ob-sync/sync.py --vault /Users/aim5/Documents/OB --pull-today
```

---

## 3. 工具优先级(用对工具事半功倍)

| 任务 | 首选工具 | Bash fallback(仅当工具不够时) |
|---|---|---|
| 读文件(已知路径) | Read | `cat`(❌ 别用) |
| 列目录 | Bash `ls` | `find`(深度遍历时) |
| 搜内容 | Grep | Bash `grep`(❌ 别用) |
| 搜文件名 | Glob | Bash `find`(❌ 别用) |
| 编辑文件 | Edit / Write | `sed -i`(❌ 别用) |
| git 操作 | Bash `git -C` 或当前目录 git | — |
| 跨工程 sync | Bash `python3 sync.py --vault X` | — |

---

## 4. 例外情况

确需持续多步操作同一目录(罕见),可用 `cd`:

```bash
npm install && npm run build && npm test
```

但 feishukanban-ob-sync 是 Python 单脚本工具,这种 case **几乎不出现**。

---

## 5. 根本治理:正确的 CC 启动方式

每个 worktree 里的 Claude 会话应当**在那个 worktree 的目录启动**:

```bash
code -n /path/to/worktree     # 新 VS Code 窗口
# → 在新窗口启动 Claude Code
```

这样 cwd 天然正确,根本不需要 cd 跳转。

对应 feishukanban-ob-sync:用户在 `/Users/aim5/Documents/CodingProject/feishukanban-ob-sync/` 目录启动 CC,默认 cwd 就是仓库根目录,所有相对路径都对。

---

## 6. 失败示例(历史教训)

### 2026-05-23 zhixing-game 教训(对应 .claude/CLAUDE.md 中记录)

> 规则教育失败 — Claude 自己也会违规,升级为 hook 硬拦截。

`cd && grep` 类复合命令 → CC permission 弹窗 → 用户授权 → 参数稍变又弹 → 越授权越脏。规则文档反复提醒不够,最后写了 `prevent-bash-compound.py` hook 在 PreToolUse 阶段硬阻止。

### 本项目 hook 配置

`.claude/hooks/prevent-bash-compound.py` + `.claude/settings.json` 已配置:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/prevent-bash-compound.py"
      }
    ]
  }
}
```

**hook 命中后会返回详细的替代写法提示**,不需要 Claude 自己记 — 直接看错误消息修。

---

## 🔗 相关

- 全局源头:`~/.claude/CLAUDE.md` 「Bash 命令写法约定」section
- hook 文件:[`.claude/hooks/prevent-bash-compound.py`](../../.claude/hooks/prevent-bash-compound.py)
- 配置:[`.claude/settings.json`](../../.claude/settings.json)
- 其他规范:[`README.md`](README.md)
