---
created: 2026-05-26T19:00:00
status: done
from_project: OB(Claudian)
to_project: feishukanban-ob-sync(Claude Code in VS Code)
to_repo: /Users/aim5/Documents/CodingProject/feishukanban-ob-sync/
priority: P1
estimated_effort: 0.5 小时
completed: 2026-05-26T20:30:00
tags:
  - handoff
  - userscript
  - 跨日
  - 时区
---

# Handoff:quickadd-快记任务-v2-task-md.js 跨日支持

## 一句话需求

改 `obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js`,让 `dateContext` 优先用「Obsidian 当前打开的 journal 日期」,fallback 到「北京时间」,解决跨日工作流 task 进错 journal 的问题。

## 背景

OB vault 用户 Mac 系统时区设为 `America/Los_Angeles`(PDT/PST,夏令时 UTC-7,冬令时 UTC-8),但人在北京。当前 userscript 用「北京时间」算 `bjDate`(规则 `base-and-frontmatter.md` 第 4 条强制北京时间)。

**典型故障路径**(2026-05-26 实证):
1. Mac PDT 时间 2026-05-26 18:26(用户视角:5-26 晚上 6 点半)
2. 用户在 `journals/2026-05-26.md` 工作(他心理上还在 5-26)
3. 用户跑 Cmd+P「📝 快记任务」创建一条新 task
4. userscript 用 `bjDate` 算出 `2026-05-27`(北京时间已过午夜)
5. 新 task 写入:
   - 文件名:`2026-05-27-<title>.md`
   - frontmatter `created: 2026-05-27T09:26:22`
   - `today_history: [2026-05-27]`
   - `日志: [[journals/2026-05-27]]`
6. 用户在 `journals/2026-05-26.md` 的 dataview 查询 `contains(today_history, "2026-05-26")` → false → **task 不显示**
7. 用户体验:**我建的 task 消失了**

## 目标 / 非目标

### ✅ 目标

- userscript 改一处:`bjDate` 改用 `getDateContext(app)`,优先用当前打开的 journal 日期
- 在 journal 文件(`journals/YYYY-MM-DD.md`)内触发 → 用该 journal 的日期
- 非 journal 文件触发 → fallback 北京时间(行为不变)
- 时间部分(`HH:mm:ss`)始终用北京时间(只有日期部分受影响)
- commit message 说清楚:跨日支持 + 引用本 handoff

### ❌ 非目标

- 不改 `sync.py`(sync.py 用 task md frontmatter,与日期无关)
- 不改 task 模板(模板已 OK)
- 不动 `quickadd-完成task.js`(已经读 task md frontmatter,与日期无关)
- 不动 `quickadd-拉今日todo.js`(操作飞书,与日期无关)
- 不动 `quickadd-同步飞书项目.js`(批量同步,与日期无关)
- 不改飞书 schema

## 接口契约

### 输入(OB 给的)

| 字段 | 类型 | 说明 |
|------|------|------|
| `app.workspace.getActiveFile()` | TFile or null | Obsidian 当前活动文件,可能是 journal / task md / 任意 md / null |
| `file.path` | string | 文件相对路径(如 `journals/2026-05-26.md`)|
| `file.name` | string | 文件名(如 `2026-05-26.md`)|

### 输出(改动的 userscript 行为)

| 场景 | dateContext 取值 |
|------|----------------|
| 当前 file = `journals/YYYY-MM-DD.md` | `YYYY-MM-DD`(journal 日期)|
| 当前 file = 其他(task md / Inbox / 任意 md / null) | 北京时间日期(原 bjDate 行为)|

### 边界情况

- 用户在 `journals/2026-05-26.md` 工作:`dateContext = "2026-05-26"`
- 用户从 task md 触发 Cmd+P:`dateContext = bjDate`(北京时间)
- 用户在 Obsidian 启动直接 Cmd+P(无 active file):`dateContext = bjDate`
- 用户在非标准命名的 journal(如 `journals/detail/2026-05-26 周二.md`):**不匹配正则 → fallback bjDate**(保守行为)

## 实施任务

### 任务 1:加 `getDateContext()` 函数(约 12 行)

在 module.exports 函数体内,Step 4「计算北京时间 + 构造路径」**之前**,加这个 helper 函数(或者在文件顶部 module.exports 外定义):

```js
function getDateContext(app) {
  // 1) 优先:当前打开的 journal 日期(跨日工作友好)
  const active = app.workspace.getActiveFile();
  if (active && active.path.startsWith("journals/") 
      && /^\d{4}-\d{2}-\d{2}\.md$/.test(active.name)) {
    return active.name.slice(0, 10);  // "YYYY-MM-DD"
  }
  // 2) fallback:北京时间(原 bjDate 行为)
  return new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10);
}
```

### 任务 2:替换 dateContext 计算(约 3 行改动)

**当前**(line 184-190):
```js
// ============ Step 4: 计算北京时间 + 构造路径 ============
const bjISO = new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 19);
const bjDate = bjISO.slice(0, 10);
// 文件名安全字符(替换 Windows/Mac 不允许的字符)
const safeTitle = titleTrimmed.replace(/[\\\/:*?"<>|]/g, "_");
const filename = `${bjDate}-${safeTitle}.md`;
const taskPath = `04 Inbox/task/${filename}`;
const journalPath = `journals/${bjDate}`;
```

**改为**:
```js
// ============ Step 4: 计算日期上下文 + 北京时间 + 构造路径 ============
// dateContext 优先用「当前打开的 journal 日期」(跨日工作支持),fallback 北京时间
// bjISO 保留(用于 frontmatter created 的完整时间戳,时间部分始终北京时间)
const bjISO = new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 19);
const dateContext = getDateContext(app);
// created 的日期用 dateContext,时间部分用北京时间 HH:mm:ss
const createdISO = `${dateContext}T${bjISO.slice(11)}`;
// 文件名安全字符(替换 Windows/Mac 不允许的字符)
const safeTitle = titleTrimmed.replace(/[\\\/:*?"<>|]/g, "_");
const filename = `${dateContext}-${safeTitle}.md`;
const taskPath = `04 Inbox/task/${filename}`;
const journalPath = `journals/${dateContext}`;
```

### 任务 3:更新 frontmatter 字段引用(2 处)

**line 210**(today_history init)— 把 `bjDate` 改为 `dateContext`:
```js
// 原: const todayHistoryInit = isToday ? `[${bjDate}]` : `[]`;
const todayHistoryInit = isToday ? `[${dateContext}]` : `[]`;
```

**line 216**(created 字段)— 把 `bjISO` 改为 `createdISO`:
```yaml
# 原: created: ${bjISO}
created: ${createdISO}
```

### 任务 4:更新顶部 JSDoc 注释(行为说明)

line 6-15 的 JSDoc 「行为」 list 末尾追加一条:

```
 * 6. 日期上下文(2026-05-26 v0.2.5 加跨日支持):
 *    - 当前打开 journal(`journals/YYYY-MM-DD.md`)→ 用 journal 日期作为文件名前缀 / today_history / 日志字段
 *    - 其他场景 → fallback 北京时间(原行为)
 *    详见 docs/handoff/OB对接/2026-05-26-userscript-跨日-handoff.md
```

### 任务 5(可选,推荐):CHANGELOG.md 加一行

把 CHANGELOG.md 顶部加一个 v0.2.5 条目(2026-05-26):

```
## [v0.2.5] - 2026-05-26

### Fixed
- `quickadd-快记任务-v2-task-md.js`:跨日工作流 task 进错 journal(根因:bjDate 与用户活动 journal 不一致)
  - 加 `getDateContext()` 函数,优先用当前活动 journal 日期,fallback 北京时间
  - 影响字段:文件名前缀 / frontmatter `created` 的日期部分 / `today_history` / `日志`
  - 北京时间部分(`HH:mm:ss`)保留(完整时间戳跨工程一致)
```

### 任务 6:commit + tag(不要 push)

```bash
cd /Users/aim5/Documents/CodingProject/feishukanban-ob-sync/
git add -A
git status  # 确认改的就是这些文件
git commit -m "$(cat <<'EOF'
fix(userscript): 快记任务跨日支持(优先用当前 journal 日期)

根因:Mac PDT 时区 + 北京工作流跨日时,bjDate 算北京时间 = 用户视角"明天",
新 task 写入明天的 journal,不出现在用户当前打开的 journal。

修复:
- 加 getDateContext() 函数,优先用当前活动 journal 日期
- fallback 北京时间(原行为,兼容非 journal 触发)
- 时间部分(HH:mm:ss)始终北京时间(跨工程一致)

详见 handoff: docs/handoff/OB对接/2026-05-26-userscript-跨日-handoff.md

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
git tag v0.2.5

# 不要 push,等用户 review
```

## 验收标准

### 单元测试场景(在 OB vault 内手动测,4 个 case)

| # | 场景 | 当前打开 file | 预期 dateContext |
|---|------|--------------|----------------|
| 1 | 跨日 journal | `journals/2026-05-26.md`(Mac PDT 5-26 晚 / 北京 5-27 早) | `2026-05-26`(用 journal 日期)|
| 2 | 当日 journal | `journals/2026-05-27.md`(Mac PDT 5-27 早 / 北京 5-27 早) | `2026-05-27` |
| 3 | 非 journal md | 任意笔记(如 `04 Inbox/task/xxx.md`) | 北京时间日期(fallback)|
| 4 | 无 active file | Obsidian 启动后直接 Cmd+P | 北京时间日期(fallback)|

### 验收 checklist

- [ ] 任务 1:`getDateContext()` 函数已加(正则匹配 `journals/YYYY-MM-DD.md` 严格格式)
- [ ] 任务 2:Step 4 用 `dateContext` 和 `createdISO`,不再用 `bjDate`
- [ ] 任务 3:`today_history` 用 `dateContext`,`created` 用 `createdISO`
- [ ] 任务 4:JSDoc 顶部注释更新
- [ ] 任务 5:CHANGELOG v0.2.5 已加(可选)
- [ ] 任务 6:commit + tag v0.2.5(不 push)
- [ ] 单元测试场景 1-4 验证通过(让用户在 OB 端实测一遍)

## 不包括(OB CC 单独承担)

- 改 OB rules `base-and-frontmatter.md`「时间字段四原则」第 4 条:从「必须北京时间」软化为「优先 journal 日期,fallback 北京时间」
- 改 OB rules `feishu-project-sync.md` 相关 task md frontmatter schema 描述(如有提及 bjDate 处)
- 实测 4 个场景(本机 Obsidian 操作)
- 3 条已落错位的 task md frontmatter 手动修正(已在 OB CC 端完成临时修复 — append today_history)

## 沟通约定

- ✅ 改完在本文件「完成记录」section 填写实际花费 + commit hash + 偏离点
- ✅ 测试时发现的 bug / spec 偏离 → 写「Follow-up」section
- ✅ 不要 push 远端(GitHub `wukongai/feishukanban-ob-sync` + Gitee `teacherai/feishukanban-ob-sync`),等用户 review 后他手动 push
- ❌ 不要主动改 OB vault 内的 task md / journal / rules(那是 OB CC 的活)
- ⚠️ 如对实现方案有异议,写在「Spec 偏离」section,带回 OB CC 决策

## 启动指令(给 feishukanban-ob-sync CC)

执行步骤:

```bash
# Step 1: 切到目标仓库(VS Code 内)
cd /Users/aim5/Documents/CodingProject/feishukanban-ob-sync/

# Step 2: 读 handoff(就是本文件)
cat docs/handoff/OB对接/2026-05-26-userscript-跨日-handoff.md

# Step 3: Read userscript 当前内容
# obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js

# Step 4: 按「实施任务」6 步顺序执行(任务 1-6)

# Step 5: 完成后在本 handoff 文件填「完成记录」+ 改 status: done
```

---

## 完成记录(feishukanban-ob-sync CC 填写)

- 实际花费:~0.3 小时(含 spec 偏离讨论)
- commit hash:**待 commit 后补**(见下方,合并 v0.3.1 块 ④)
- tag:**v0.3.1**(并入,非 v0.2.5 — 见 Spec 偏离)
- 偏离点:**版本号 v0.2.5 → 并入 v0.3.1 块 ④**(原因:v0.2.5 / v0.3.0 已发,且工作树已有 v0.3.1 草稿。已与用户确认。)
- 测试结果:**未实测**(本侧只改代码 + commit;实测 4 场景由用户在 OB vault 操作)

### 实际改动文件

- `obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js`:
  - 顶部新增 `getDateContext(app)` helper(14 行,正则 `^\d{4}-\d{2}-\d{2}\.md$` 严格匹配 journal 命名)
  - Step 4:`bjDate` → `dateContext`,新增 `createdISO = ${dateContext}T${bjISO.slice(11)}`
  - frontmatter:`today_history` 用 `dateContext`,`created` 用 `createdISO`
  - JSDoc 顶部第 6 条行为说明
- `CHANGELOG.md`:v0.3.1 标题改「四块 patch 合并」+ 新增「🕐 块 ④」段 + 升级路径加第 7 步跨日测试
- `README.md`:v0.3.1 banner 改写为四块列表

## Follow-up(实施中浮现的问题,如有)

无。

## Spec 偏离(如有)

### 1. 版本号 v0.2.5 → 并入 v0.3.1 块 ④(已用户拍板)

handoff 写 `v0.2.5`,但实际仓库:
- `v0.2.5` tag 已存在(commit `aa51e28` — `pull-today 自动建 OB 端无对应 task md 完整反向同步`)
- `v0.3.0` tag 已存在(commit `c779ab5` — `today_history 事件流`)
- 工作树有未 commit 的 v0.3.1 草稿(`--vault` / `inject_completion_link` / `today_history 残留清理` 三块)

**决策**(用户 AskUserQuestion 确认):并入 v0.3.1 作为第 ④ 块。

**影响给 OB CC**:
- 未来引用本 patch 应称「v0.3.1 块 ④ 跨日 dateContext」,而非「v0.2.5 跨日」
- OB rules 改第 4 条「必须北京时间」时,版本说明应写 v0.3.1

### 2. 时间部分实现(对照 handoff spec 100% 一致)

handoff spec 写 `createdISO = ${dateContext}T${bjISO.slice(11)}` — 已严格按此实现,**时间部分仍是北京时间**(确保跨工程时间戳一致性)。

## 状态变更记录

- 2026-05-26T19:00:00 — handoff-pending(OB CC 写完)
- 2026-05-26T20:30:00 — done(feishukanban CC 实施完成,4 块并入 v0.3.1)
