---
title: 布丁 backlog ↔ OB task md 自动镜像教程
created: 2026-06-04
status: published
version: v0.8.0
related:
  - "[[../design/backlog-to-task-mirror.md]]"
  - "[[../design/backlog-to-task-mirror-plan.md]]"
---

# 布丁 backlog ↔ OB task md 自动镜像教程

> **作用**:你在 OB 或 zhixing-game CC 里新建布丁 backlog 时,task 看板自动出现一条对应 task md。
> 不再遗漏,不需要记得手动同步。
> task md 默认 `today: false` 进需求池(不进今日 todo,不打扰 ADHD 焦点)。

## 一、架构总览

```
┌─ 触发点 A: OB Cmd+P「🎮 新建布丁需求」───────────┐
│ Macro Step 1: Template 创建 backlog md           │
│   (vault 路径经 symlink 落到 zhixing-game repo)  │
│ Macro Step 2: UserScript 调中间件                │
└──────────────────┬───────────────────────────────┘
                   │
┌─ 触发点 B: zhixing-game CC Write backlog md ────┐
│ .claude/hooks/post-backlog-sync.py 监听         │
│ Write/Edit/MultiEdit 到 docs/backlog/<prefix>-* │
└──────────────────┬───────────────────────────────┘
                   ↓
         ┌──────────────────────────────────┐
         │ 中间件:                         │
         │ feishukanban-ob-sync/scripts/    │
         │   backlog_to_task.py             │
         │                                  │
         │ - 幂等:已镜像走 update 不重建    │
         │ - dry-run 默认,--apply 真改      │
         │ - 5 个 backlog_* frontmatter 字段│
         │ - 日志 ~/.claude/logs/           │
         └────────────────┬─────────────────┘
                          ↓
              OB vault 04 Inbox/task/
              YYYY-MM-DD-【布丁开发】<标题>.md
              (today=false 进需求池)
```

## 二、Phase 2 安装:OB QuickAdd Macro 升级

### 2.1 前置确认

确认 vault 这个 symlink 存在(2026-05-14 已建):

```bash
ls -la "/Users/aim5/Documents/OB/01 Project/00 进行中/应用产品/布丁/zhixing-game-docs"
# 应输出: lrwxr-xr-x → /Users/aim5/Documents/CodingProject/zhixing-game/docs
```

### 2.2 把 UserScript 放进 vault

UserScript 文件位置:
- 源码:`feishukanban-ob-sync/obsidian-assets/userscripts/quickadd-新建布丁需求-后处理.js`
- vault 安装路径(经 symlink):`01 Project/00 进行中/应用产品/小工具开发/feishukanban-ob-sync/userscripts/quickadd-新建布丁需求-后处理.js`

```bash
# 重跑 install.sh 把新 userscript 链接到 vault
cd ~/Documents/CodingProject/feishukanban-ob-sync
./install.sh --vault ~/Documents/OB --apply
```

(注:如果 install.sh 不识别新文件,手动 cp 一份到上述 vault 路径)

### 2.3 在 QuickAdd UI 升级「🎮 新建布丁需求」Template → Macro

**操作步骤**(Obsidian UI):

1. `Cmd+,` 打开 Settings → QuickAdd → Manage Macros
2. 找到「🎮 新建布丁需求」当前是 Template 类型
3. 点击 ⚙️ Settings → 记下当前的:
   - templatePath: `03 Resources/素材库/模版/好奇猫开发需求模版.md`
   - fileNameFormat: `idea-{{NAME}}`
   - folder: `01 Project/00 进行中/应用产品/布丁/zhixing-game-docs/backlog/`
4. 删掉当前 Template 项 → 新建一个 Macro 项,**命名跟原来一样**:`🎮 新建布丁需求`
5. 进入 Macro 编辑界面,加 2 个 step:

**Step 1: Template**
- Template Path: `03 Resources/素材库/模版/好奇猫开发需求模版.md`
- File Name Format: `idea-{{NAME}}`
- Create in folder: `01 Project/00 进行中/应用产品/布丁/zhixing-game-docs/backlog/`
- ✅ Open created file
- ✅ Open in new tab(可选)

**Step 2: UserScript**
- UserScript: 选 `quickadd-新建布丁需求-后处理.js`(从下拉里挑)

6. 保存 → 回主设置 → 找到这个 Macro → 启用 "Show in command palette"
7. 测试:`Cmd+P` → 输入「新建布丁需求」→ 起一个测试 backlog 名(如 `测试镜像`)→ 看 vault 弹通知:`✅ task 镜像完成`
8. 检查 `04 Inbox/task/` 出现 `2026-06-04-【布丁开发】测试镜像.md`

### 2.4 测试失败排查

- **没弹通知**:Cmd+P 看是否真的跑到 Step 2(可以在 userscript 第 1 行加 `new obsidian.Notice('Step 2 triggered')`测)
- **弹 `❌ task 镜像失败`**:打开 DevTools(`Cmd+Opt+I`)看 console.error 详情
- **vault 没出 task md**:检查中间件路径是否对(`ls ~/Documents/CodingProject/feishukanban-ob-sync/scripts/backlog_to_task.py`)
- **Python 版本不对**:检查 `python3 --version`(需要 3.8+ + PyYAML)

## 三、Phase 3 安装:zhixing-game CC hook

### 3.1 文件位置

- `~/Documents/CodingProject/zhixing-game/.claude/hooks/post-backlog-sync.py`
- `~/Documents/CodingProject/zhixing-game/.claude/settings.json` 挂 PostToolUse hook

### 3.2 验证 hook 可执行

```bash
ls -la ~/Documents/CodingProject/zhixing-game/.claude/hooks/post-backlog-sync.py
# 应是 -rwxr-xr-x(可执行)
chmod +x ~/Documents/CodingProject/zhixing-game/.claude/hooks/post-backlog-sync.py
```

### 3.3 settings.json 挂载

`~/Documents/CodingProject/zhixing-game/.claude/settings.json` 的 `hooks.PostToolUse` 数组应有一项:

```json
{
  "matcher": "Write|Edit|MultiEdit",
  "hooks": [
    {
      "type": "command",
      "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/post-backlog-sync.py"
    }
  ]
}
```

### 3.4 测试

在 zhixing-game CC 会话里让 CC 写一条测试 backlog:

```
Write /Users/aim5/Documents/CodingProject/zhixing-game/docs/backlog/idea-CC-hook-test.md
```

frontmatter 随意。看 OB vault `04 Inbox/task/` 几秒后出现:`2026-06-04-【布丁开发】CC hook test...md`

### 3.5 不触发的情况(预期)

- README.md / _index.base / .bak 文件 → 跳过
- 非 backlog 目录的 md → 跳过
- env `BACKLOG_TO_TASK_DISABLE=1` → 关闭

## 四、紧急关闭

```bash
export BACKLOG_TO_TASK_DISABLE=1
# 当前 shell 会话 + 之后启的 CC / Obsidian 都会跳过同步
# 永久关:加进 ~/.zshrc
```

## 五、日志

中间件每次同步都写 `~/.claude/logs/backlog-to-task-YYYY-MM.log`,JSON line 格式:

```bash
tail -20 ~/.claude/logs/backlog-to-task-2026-06.log
```

每行字段:
- `ts`:时间戳
- `slug`:backlog 文件名 stem(如 `P1-习惯养成打卡`)
- `action`:`create` / `update`
- `detail`:操作结果细节
- `dry_run`:true / false

## 六、相关命令

```bash
# 单文件 dry-run
python3 ~/Documents/CodingProject/feishukanban-ob-sync/scripts/backlog_to_task.py \
  --backlog "/Users/aim5/Documents/CodingProject/zhixing-game/docs/backlog/<slug>.md"

# 单文件 --apply
python3 .../scripts/backlog_to_task.py --backlog X --apply

# 全量 scan(看会建/更新多少条)
python3 .../scripts/backlog_to_task.py --scan

# 自定义 vault
python3 .../scripts/backlog_to_task.py --backlog X --vault /custom/path/to/vault
```

## 七、相关文档

- [设计 spec](../design/backlog-to-task-mirror.md)
- [实施 plan](../design/backlog-to-task-mirror-plan.md)
- [架构总览](../ARCHITECTURE.md)
