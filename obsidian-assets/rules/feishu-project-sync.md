# task md 化架构(2026-05-25 上线)

> **核心升级**:从「journal inline task → sync.py 扫日志行」改为「task md 独立笔记 → sync.py 扫 frontmatter」。每个 task = 一个 md 文件,frontmatter 字段和飞书项目看板 **1:1 对齐**。
>
> **Cmd+P 主入口**:`📝 快记任务` (Macro v2):弹优先级 → 输标题 → 自动创 task md + 同步飞书 + journal 加 wikilink。**绕过 dry-run 审核**(铁律 #1 飞书例外,见下方)

## 双流程并存

| 流程 | 入口 | 数据载体 | 飞书同步 |
|------|------|---------|---------|
| **task md(主)** | Cmd+P 「📝 快记任务」(QuickAdd Macro v2) | `04 Inbox/task/YYYY-MM-DD-<标题>.md` | **自动**单条 CREATE(铁律 #1 例外) |
| **journal inline(降级)** | Cmd+P 「📝 快记任务(inline 老版)」(QuickAdd Capture) | `journals/YYYY-MM-DD.md` 的 `- [ ]` 行 | 批处理:Cmd+P 「🎯 同步今日 task 到飞书」走 5 步 SOP |

## task md frontmatter ↔ 飞书 1:1 映射

完整字段表见 [[base-and-frontmatter.md]]「task md frontmatter schema」section。关键映射:

| Task md frontmatter | → 飞书字段 | 类型 | 备注 |
|---|---|---|---|
| `priority` (P0-P3) | 价值优先级 | select | 同时决定 OB 端落「🎯今日计划」(P0-P2) 或「🐿️今日非计划」(P3) |
| `status` | 执行状态 | select | todo/doing/done/block/cancel |
| `category` | 大类 | select | 产品项目/杂务/技能工具/领域学习 |
| `subcategory` (list) | 小类 | select multi | YAML list |
| `adhd_priority` | ADHD优先级 | select | 待抢救/有 DDL/自由待办 |
| `estimate_hours` | 估时 | number | 小时数 |
| `acceptance` (正文段) | 验收条件 | text | 抽自「## ✅ 验收条件」H2 段 |
| `thinking` (正文段) | 执行思路 | text | 抽自「## 💡 执行思路」H2 段 |
| `resources` (正文段) | 相关资料 | text | 抽自「## 🔗 相关资料」H2 段 |
| `retrospective_text` (正文段) | 复盘 | text | 抽自「## 🪞 复盘」H2 段 |
| `execution_summary` (正文段) | 执行概述 | text | 抽自「## 📝 执行概述」H2 段(主体) |
| `feishu_record / feishu_url` | (回写) | — | sync 后自动写入 |
| `iteration_week / month` | 执行迭代周/月 | select | sync 自动 derive |

## sync.py 用法

```bash
# task md 模式(2026-05-25 新增)
python3 sync.py --task-md "04 Inbox/task/2026-05-25-xxx.md"           # dry-run
python3 sync.py --task-md "04 Inbox/task/2026-05-25-xxx.md" --apply   # 真写 + 回写 frontmatter

# journal 模式(老接口,仍可用)
python3 sync.py journals/2026-05-25.md --only-completed --apply
```

## journal dataview 渲染策略(2026-05-25 上线 v2 — TASK 查询 + inline checkbox)

> **设计意图**:用户日常主力飞书移动 app(看板移动方便);OB 本地 task md 是 single source of truth。journal 内 dataview 用 **TASK 查询渲染 inline checkbox**,**三个交互点一行实现**:checkbox 可勾选 + 描述跳飞书 + source link 进 task md。

### task md 必须的「## ✅ 完成标记」section

每个 task md 文件末尾必须有此 section,包含一行 inline task(模板已固化自动生成):

```markdown
## ✅ 完成标记
- [ ] [<H1 title>](<feishu_url>)
```

inline marker 状态(按 frontmatter `status` 决定):

| frontmatter status | inline marker | 后缀 |
|--------------------|---------------|------|
| `todo` | `- [ ]` | (无)|
| `doing` | `- [/]` | (无)|
| `done` | `- [x]` | ` ✅ <done_date>` |
| `cancel` | `- [-]` | ` ❌ <done_date>` |

模板 `03 Resources/素材库/模版/task 模版.md` Templater `<% cleanTitle %>` 自动从文件名脱日期前缀提取 title。

⚠️ **当前缺陷**:模板生成的 inline 是 plain text(`- [ ] <title>`)**没有 markdown link feishu_url**,因为创建时还没 sync。**手动方案**:sync 后跑批量补 link 脚本(参考 2026-05-25 升级时的 Python 脚本);**未来方案**(P2 backlog handoff `feishukanban-ob-sync`):sync.py CREATE/UPDATE 时自动维护 inline 的 markdown link。

### 渲染规则(模板已固化)

「🎯 今日计划」段(P0-P2)+「🐿️ 今日非计划」段(P3)两个 dataview 块:

```
TASK
FROM "04 Inbox/task"
WHERE !contains(file.name, "_说明")
  AND (priority = "P0" OR priority = "P1" OR priority = "P2")
  AND (!completed OR completion = this.file.day)
SORT priority ASC, created DESC
```

### TASK 查询语义

- **`!completed`**:inline 未勾(`- [ ]` 或 `- [/]`)→ 显示
- **`completion = this.file.day`**:inline 今日勾的(`- [x] ... ✅ <today>`)→ 显示
- **历史日勾的**:`completion ≠ this.file.day` → 不显示(跨日浏览旧 journal 自动只显示该日完成的)
- **`priority`**:dataview TASK 自动 inherit 所在 file 的 frontmatter

### 三个交互点一行实现

| 点击位置 | 行为 |
|---------|------|
| **checkbox `☐`** | Tasks 插件勾选/取消勾选,自动改源 task md 的 inline `[ ]` ↔ `[x]` + `✅ date` |
| **task 描述 `[title](url)`** | 点击跳飞书 record(markdown link 嵌入 `feishu_url`)|
| **source file link**(dataview 自动附加) | 进 task md 文件本身 |

### check 后的状态同步 ❗(2026-05-26 升级,P2 backlog 已落地)

**历史缺陷**(2026-05-25):点 dataview 渲染的 checkbox 改 inline status,**frontmatter `status` 字段不自动同步**。需手动跑 sync.py。

**2026-05-26 解决方案 — Cmd+P「✅ 完成当前 task」**(取代原 P2 backlog 方案 A/B):

打开任意 task md → Cmd+P 「完成 task」 → 一键完成全闭环:
1. inline `- [ ]` → `- [x]` + 加 `✅ today` 后缀
2. frontmatter `status: todo/doing` → `done` + `done_date: today`
3. sync.py --task-md --apply 走 UPDATE 飞书(铁律 #1 飞书例外扩展,自动 apply)

UserScript:`02 Area/00 AiCoding/scripts/quickadd-完成task.js`(2026-05-26 上线)
QuickAdd choice:`✅ 完成当前 task`

**剩余 follow-up**(P3 backlog,低优先级):
- 用户直接点 dataview 渲染的 inline checkbox → 现状仍只改 inline 不改 frontmatter(Obsidian 原生行为,Tasks 插件不 hook frontmatter)
- 用户工作流约定:勾完 inline 后,再走 Cmd+P「✅ 完成当前 task」做"补正"(虽然小损失但能用)
- 长期 P3:写 Obsidian 自定义插件 hook checkbox click 事件,完全免 Cmd+P — 当前不值这个工程量

### 反向链接(飞书 → OB)

**目前不做**(2026-05-25 用户决策):OB 本地只是备份,飞书 record 不需要回链 OB。dataview 单向跳飞书已满足移动场景诉求。未来如有需要(飞书桌面端点链接回 OB 看详细 H2 段),可加飞书表「OB 备份路径」text 字段 + `config.yaml` 字段映射 + `sync.py` 写入 — 目前 P3,等真需求出现再做。

### 必须遵守

- ❌ **禁止改 task md 内 inline checkbox 标准格式** — Tasks 插件依赖 `- [ ]` / `- [/]` / `- [x]` / `- [-]`,不能换符号
- ❌ **禁止 task md 内加额外 inline task** — 会污染 dataview TASK 渲染(未来若需要,加 `WHERE task.section.subpath = "✅ 完成标记"` 过滤)
- ❌ **禁止用 JS 三元 `condition ? a : b`** — DQL 不支持(详见 [[dataview-troubleshoot.md]]「禁区」),条件分支用 `choice()` 函数
- ✅ **修改渲染规则时**同步改模板 + 所有在用日志(至少改模板 + 当天日志 4 处)
- ✅ **新建 task md 走 task 模板**自动生成 `## ✅ 完成标记` section
- ✅ **批量给已有 task md 补 inline section** 走 Python 脚本(参考本会话 2026-05-25 升级实施)

### 关联事故 + 演进史

- **2026-05-25 上半场(LIST 方案)**:`LIST WITHOUT ID + choice + markdown link 跳飞书` — 链接可跳飞书,但**不能 check** + 三元 `? :` DQL 解析失败先用 `choice()` 修(详见 [[dataview-troubleshoot.md]]「事故记录」末段)
- **2026-05-25 下半场(TASK 方案,本节)**:用户反馈"不能 check 因此漏到后天功能不可用"→ 升级为 **TASK 查询 + 每个 task md 加 inline checkbox**。三个交互点一行实现(check / 跳飞书 / 进 task md)。代价:模板更复杂 + sync.py 未自动维护 inline link(短期手动补 / 长期 handoff)
- **2026-05-26 进一步简化(撤"漏单"+ 删 inline 老版 + 删 Macro v2 Step 8 wikilink)**:用户决策"每日只做最重要的,不需要跨日漏单"。变更:
    - ❌ 删 journal 模板的 ```tasks 查询块(原 P0/P1/P2 / 非计划三段 Tasks 插件查询) — journal 只剩 dataview TASK 查询,纯粹反映"今天 task md 的优先级状态"
    - ❌ 删 QuickAdd「📝 快记任务(inline 老版)」choice — task 唯一入口是 Macro v2
    - ❌ 删 Macro v2 Step 8 (写 wikilink `- [[task md]]` 到 journal) — 让 dataview TASK 查询独占 journal 渲染,不再冗余
    - ✅ Tasks 插件保留(解析 task md 内 inline checkbox + 点击时加 ✅ 完成日的自动化仍可用)
    - **跨日 task 管理真相源**:飞书项目看板(移动主用)+ `_task.base` 6 视图(本地)
    - **当日 journal**:只看"今天聚焦的 P0-P2 / P3",做完日就消失 — 不再跨日"漏"

## 🎯 今日 todo 双层架构(2026-05-26 上线)

> **背景**:撤销"漏单"后,dataview 查询仍是"未完成永远显示" — 100 个未完成 task 会全部充斥 today journal,ADHD 严重分心。设计目标:**周看板做周迭代规划 + 今日 todo 做日聚焦**,两层互不干扰。

### 架构 3 层

```
飞书项目表 → 周看板视图(周迭代规划用)
              └─ 「是否今日」checkbox 字段(2026-05-26 加,fldD8bn1wU)
                     ↑ 早上 app 内挑 3-5 条勾 ✓ = 今日 todo
                     ↓ sync.py --pull-today --apply
OB task md frontmatter today: true | false
                     ↓ dataview 查询过滤
OB today journal 「🎯 今日计划」段
  WHERE today = true
    AND (priority = "P0" OR "P1" OR "P2")
    AND (!completed OR completion = this.file.day)
```

### 关键决策

| # | 决策点 | 选择 | 理由 |
|---|--------|------|------|
| 1 | 周看板 vs 日视图 | **周看板 + today 字段**(不切换视图) | 日视图切换中断 ADHD 工作流,字段 toggle 原地操作更简洁 |
| 2 | today 字段在哪? | **飞书侧主导 + OB 跟从** | "看板是真相源" — 用户日常主用飞书 app |
| 3 | OB 端字段表达 | frontmatter `today: true | false` 布尔 | 简单 + dataview 友好 |
| 4 | sync 方向 | **飞书 → OB 单向**(--pull-today) | 用户工作流是"飞书 app 挑 → Mac sync → OB 显示" |
| 5 | 跨日清理 | **完全手动**(每日早上重新挑) | ADHD friendly 仪式:强迫每日重评估优先级 |
| 6 | "飞书有 OB 无"场景 | **报告 + 用户手建**(不自动建 task md) | 避免反向映射 priority/category 等多字段易出错;鼓励用户走 Cmd+P 主流程 |

### 工作流(早晚 5 分钟仪式)

```
☀️ 早上(2 分钟,飞书 app):
   周看板 → 看本周 P0/P1 task → 挑 3-5 条今天做的 → 长按 task → 勾「是否今日」=true
   ↓
   Mac 跑:python3 sync.py --pull-today --apply
   ↓
   OB today journal「🎯 今日计划」自动渲染这 3-5 条 ✅

🏃 白天:
   只看 today journal 段下 dataview 渲染的 checkbox(3-5 条,清爽不分心)
   做完一条 → 勾 checkbox → 改 frontmatter status:done → sync 飞书 UPDATE

🌙 晚上收工(1 分钟,飞书 app):
   未完成的"今日" task → 决定:
     A. 保留「是否今日」=true(明天继续)
     B. 取消「是否今日」=false(回到本周待办,改天做)

📅 明早:
   再走一遍仪式 — 强迫重新评估今日优先级(ADHD friendly)
```

### sync.py --pull-today 行为(双向对齐)

| 场景 | 飞书 | OB | 动作 |
|------|------|----|----|
| **新挑 today** | 「是否今日」=true | task md today=false | 改 OB today=true |
| **取消 today** | 「是否今日」=false | task md today=true | 改 OB today=false |
| **飞书 = OB** | 都 true | 都 true | 跳过(无操作) |
| **OB 无对应** | 「是否今日」=true | 无 task md | 报告 + 提示用户手建 |

### dry-run 示例输出

```
============================================================
📥 pull-today: 飞书「是否今日」=true → OB task md today=true
============================================================
⏳ 拉飞书全表 record...
✅ 飞书共 N 条 record
🔍 飞书「是否今日」=true: M 条
⏳ 扫 OB task md(按 feishu_record 建索引)...
✅ OB 共 K 个 task md(有 feishu_record 关联的)

📋 计划摘要:
  ➡️  设 today=true:    A 条
  ⬅️  设 today=false:   B 条
  ⏭️  已是 today,跳过: C 条
  ⚠️  飞书有 OB 无:    D 条
```

### 必须遵守

- ❌ **禁止改飞书表「是否今日」字段名** — config.yaml `reverse.default_filter.field_name = 是否今日` 硬编码,改了 sync.py 找不到字段
- ❌ **禁止删 task md frontmatter `today` 字段** — dataview 查询依赖,删了 journal「🎯 今日计划」段永远空
- ❌ **禁止用 `--pull-today` 同步非项目管理表的 today 字段** — 当前 cli 已硬绑 base/table id
- ✅ **跨日清理走手动** — 每日早上飞书 app 检视昨天「今日」标记 + 重新挑(不要写 cron 自动清,失去重评估仪式)
- ✅ **新增 today=true 必须经飞书 → OB 单向** — 不要在 OB 端直接改 frontmatter today=true,因为下次 pull-today 会被 OB → false 反向覆盖(但飞书侧也勾就 OK)

### 关键 invariant

- 飞书项目表「是否今日」字段必须存在(2026-05-26 创建,id: `fldD8bn1wU`)
- task 模板 `03 Resources/素材库/模版/task 模版.md` frontmatter 必须有 `today: false` 默认字段
- journal 模板「🎯 今日计划」+「🐿️ 今日非计划」段的 dataview 查询必须有 `WHERE today = true` 条件

### 关联事故 + 演进史(本 section)

- **2026-05-26 上线**:用户反馈"撤了漏单后未完成 task 仍在 today journal 充斥分心" → 设计「周看板 + 今日 todo 字段」双层架构 → 3 步实施(task 模板 + journal 模板 + sync.py --pull-today)。
  - 实施前置:发现飞书表「是否今日」字段从未真实创建过(config.yaml 写了但表没建),用 `feishu-cli bitable field create --type checkbox` 一行命令创建,得到 fldD8bn1wU
  - 用户决策跨日清理走 A 手动策略(ADHD friendly 重评估仪式)

## 🤖 场景 ③ 自动统计今日工作 SOP(2026-05-26 上线)

> **触发关键词**(用户在 Claudian 对话说这些时,Claudian 主动走本 SOP):
> - "统计今天工作" / "汇总今日工作" / "auto-stats today" / "自动统计今日"
> - "今天做了什么 → 写日志和飞书" / "复盘今天" / "做了哪些事"
> - 类似自然语言(用户没说"统计"但意图明显时也触发)

### 适用场景

用户没事先做 task 计划,**直接干活**(开发 zhixing-game / OB / 改 handoff / 写 daily / 写 spec 等),工作完成后想:
- ✅ 把"做了什么"汇总到 today journal(复盘用)
- ✅ 把"做了什么"写到飞书项目看板(看板任务全生命周期,Done 状态)
- ✅ 关联工作内容到 daily / 周迭代 / 项目 plan(不是孤立 commit 列表)

### 设计原则(用户拍板)

- ✅ **看板混合 todo/doing/done** — 自动统计走"完成态 task"路径,不分离
- ✅ **写飞书是必须** — "在日志中创建 task 时不就已经写飞书了吗" — 一致性
- ✅ **关联回计划** — 工作 → 对齐 daily / 周迭代 / 项目 plan,不是裸 commit
- ✅ **归纳由 LLM 做**(不是 Python 脚本) — 主题级关联需要语义理解,脚本只能项目级分组

### 5 步 SOP(Claudian 主导,触发关键词后自动走)

```
Step 1: 数据采集(Bash + Python 脚本)
  - git log 从用户已知项目仓库(zhixing-game / OB / feishukanban-ob-sync 等)
  - 今日 mtime 改的 vault .md 文件(跳过 .obsidian / .git / journals / 04 Inbox/cubox 等)
  - 读 today journal + 本周报(可选)
  - 输出原始 JSON / 结构化清单

Step 2: 归纳为主题级清单(Claudian 做)
  - 把零散 commit / 文件 / 段落 归类成 N 个主题
  - 每个主题:标题(2-5 字)/ 描述(1-2 句)/ 关联项目 / 关联计划 wikilink(可选)
  - 推荐 5-10 个主题(太多 = 噪音,太少 = 信息不全)

Step 3: 给用户审 dry-run
  - 列主题清单
  - 用户决定:全部建飞书 / 跳过哪些 / 改标题描述
  - **等明确批准词**("通过/apply/同意")才进 Step 4

Step 4: 写 today journal「📊 今日自动统计」section
  - 在「📝 今日复盘」之前(or 末尾)加新 section
  - 主题清单 + 关联 wikilink + git commit 链接

Step 5: 飞书 batch CREATE
  - 为每个主题在飞书项目表 CREATE 一条 record:
    * 任务标题 = 主题标题
    * 执行状态 = Done
    * 完成时间 = today
    * 价值优先级 = P3(默认,自动统计的工作不抢主动 task 的优先级位)
    * 大类 = 自动判断(开发 / 内容 / 工具)
    * 是否今日 = true(今天做的)
    * 任务来源 = "auto-stats"(避免和主动 task 混 — 如有此字段)
```

### Step 1 helper 脚本

**`auto_collect_today.py`**(`02 Area/00 AiCoding/scripts/auto_collect_today.py`,2026-05-26 上线)

```bash
python3 "02 Area/00 AiCoding/scripts/auto_collect_today.py"
```

输出 JSON 到 stdout,含:
- `git_commits`: list of {repo, hash, message, timestamp}
- `vault_modified_files`: list of {path, mtime, size_change}
- `today_journal_path`: today journal 路径
- `week_report_path`: 本周报 wikilink(可选)

Claudian 读这个 JSON + 做归纳。

### 飞书侧 schema 准备(2026-05-26 待补)

可选(P2):在飞书项目表加一个字段「任务来源」select,选项 `主动 / auto-stats`,避免自动统计 task 和主动 task 混(默认 = 主动)。当前 MVP 不加,所有 auto-stats record 用 `价值优先级 = P3` 隐式区分。

### 必须遵守

- ❌ **禁止跳过 dry-run 直接 batch CREATE** — 主题归纳是 LLM 行为,有不准的可能,必须用户审
- ❌ **禁止把已有飞书 record 的工作再建一次** — Claudian 跑 Step 5 前必须先按标题查重(用 `build_records_title_index`),命中 → 跳过 / 警告
- ❌ **禁止 OB 端不写日志只写飞书** — 双写,journal 是复盘载体,飞书是看板载体
- ✅ **价值优先级默认 P3** — 自动统计的工作没经过"主动评估",不抢 P0/P1/P2 位
- ✅ **每条主题在 today journal 给关联 wikilink** — daily/周报/spec 等(让你回看时点击跳过去)
- ✅ **触发关键词识别要灵活** — 用户没说"统计"但说"今天做了什么" / "总结今天" 等也要识别

### 跨工程边界

git log 跨多个工程仓库(zhixing-game / OB / feishukanban-ob-sync 等)是**只读**操作(`git log` / `git diff` 只读 git 历史),不写代码,不违反铁律 #2「跨工程边界」。

### 关联事故 + 演进史(本 section)

- **2026-05-26 上线**:用户提了 3 个工作场景的需求,场景 ③ 完全没支持。用户纠正 OB CC 的"主动 vs 被动分离"过度设计,明确"看板就是混合 todo/doing/done,自动统计也是 task,要写飞书"。设计 5 步 SOP + Claudian 主导归纳 + helper 脚本采集。

## 🔴 铁律 #1 飞书例外(2026-05-25 固化 + 2026-05-26 扩展)

> **背景**:铁律 #1「sync apply 必须先用户审核」源自 2026-05-06 PUA 案例事故,核心保护是"避免错误覆盖布丁线上数据"。**飞书项目同步本质不同**:目标 = 用户私域工具,无第三方读者;单条操作出错代价 = 飞书后台手动恢复(30 秒-2 分钟)。
>
> **用户拍板**(2026-05-25 / 2026-05-26):**开精确例外**,3 种 Cmd+P 单条操作自动跑(全闭环工作流不打断)。

### 例外条件(3 种自动 apply 场景)

| 场景 | 触发 | 操作类型 | 风险 |
|------|------|--------|------|
| **1. 单条 CREATE 新 task** | Cmd+P「📝 快记任务」 | CREATE | record_id 为空,空白记录新建,无覆盖风险 |
| **2. 单条 UPDATE 完成 task**(2026-05-26 加) | Cmd+P「✅ 完成当前 task」 | UPDATE(改 status:done + done_date) | OB 端主导单条操作,不覆盖飞书后台手编字段(today / 价值优先级 等) |
| **3. pull-today 同步 today 字段**(2026-05-26 加) | Cmd+P「📥 拉今日 todo」 | UPDATE(改 OB 端 frontmatter today) | 只改 OB frontmatter,**不写飞书**(read-only on 飞书) |

3 种场景共同满足:
- ✅ 单条操作(非批量)
- ✅ OB 端主导(用户在 OB 触发,不是飞书侧)
- ✅ 目标 = 飞书项目管理表(用户私域)
- ✅ 失败回滚成本低(2-3 分钟手敲恢复)

### 仍走 5 步 SOP(铁律 #1 默认)

- ❌ 批量同步多条 task(走 Cmd+P 「🎯 同步今日 task 到飞书」走 dry-run + 审)
- ❌ journal 模式 `python3 sync.py path/to/journal.md --apply`
- ❌ 场景 ③「自动统计今日工作」batch CREATE 6+ 条 record(必须 dry-run + 用户审)
- ❌ 任何 sync 到布丁 / 学员前端 / 其他生产数据
- ❌ 飞书表结构变更(加字段 / 改字段类型 / 删字段)

### 实现位置

- UserScript:`02 Area/00 AiCoding/scripts/quickadd-快记任务-v2-task-md.js` Step 7 调 `sync.py --task-md --apply`
- sync.py:`push_task_md` 函数,`is_create = not task.get("record_id")` 自动判断

### 门禁

- ❌ 禁止扩展这个例外到其他场景(布丁 / 批量 / 其他多维表)
- ❌ 禁止跳过 dry-run 走 UPDATE
- ✅ 用户在飞书后台改了字段 → 下次 sync 走 UPDATE → 仍需 dry-run 审核

---

# 飞书项目同步 SOP(2026-05-17 上线 Phase 1)

> **背景**:用户长期用飞书多维表做项目管理看板("项目管理"表),日志里写 task 通过 markdown 链接关联到飞书 record。痛点是:OB 端勾 [x] 完成 → 飞书侧字段(执行状态/完成时间/复盘 wikilink)不会自动联动,需要手动到飞书后台填,容易遗漏。
>
> **方案**:写一个 OB 端 Python 脚本(`sync.py`)+ skill(`/飞书项目同步`),通过 feishu-cli 调用 bitable record upsert,自动把 OB 日志 task 状态 → 飞书字段;同时无飞书链接的新 task 自动建 record + 写回链接到 markdown。
>
> **文档对应关系**:
> - skill 入口:[[01 Project/00 进行中/06 小工具开发/CC命令/飞书项目同步/SKILL.md]]
> - 本文件:SOP 规则 + 8 条架构原则自评 + 事故记录(给未来的 AI 看)

## 核心命令

```bash
python3 "01 Project/00 进行中/06 小工具开发/CC命令/飞书项目同步/sync.py" <journal-path> [--only-completed] [--apply]
```

- 无 `--apply` = dry-run(默认,不写飞书)
- `--only-completed` = 只同步 `[x]` 和 `[-]`(推荐日终复盘用)
- `--apply` = 真实写入飞书 + 自动 Edit markdown 写回 record_id 链接

## 5 步 SOP(铁律 #1 + L2 TodoWrite)

```
Step 1: 识别目标 journal(默认 current_note,非日志要 ask)
Step 2: dry-run 把所有 task 解析 + 字段映射 payload 给用户看
Step 3: 给用户审 dry-run + 等明确批准词("通过/apply/同意/sync")
Step 4: --apply 真实写入 + 自动写回 record_id 链接
Step 5: 验证写入(读飞书 record 字段 + 显示 OB 笔记 diff)
```

**L2 强制 TodoWrite**:5 步对应 5 个 todo,显式 mark in_progress/completed,让用户能中途打断。

## 字段映射(完整 v1.6,2026-05-17 升级)

| OB 信号 | 飞书字段 | 类型 | 备注 |
|---|---|---|---|
| task 标题 | 任务标题 | text | 必填 |
| `[x]/[ ]/[/]/[-]` | 执行状态 | 多选(单值用 list 包裹) | Done/Todo/Doing/Block 四枚举 |
| `✅ YYYY-MM-DD` | 完成时间 | datetime | ms 时间戳;`✅` 无日期时 fallback 到今天 |
| **A/B/C 三路扫产物** | **交付** | **text** | **D 混合架构,详见下方专章** |
| 当前日志路径 | (不再自动填复盘) | — | 用户决策(2026-05-17):复盘留给手填心得 |
| 🔺/⏫/🔼/🔽 | (不映射) | — | 避免覆盖飞书侧"价值优先级"自主评估 |
| ✅ 完成日 → ISO 周 | 执行迭代周 | 单选 enum | 2026-05-18 加 (Phase 2.1). derive 模板 `{YY}W{NN:02d}` + cli `best_match_enum`, 未命中静默跳过(详见已知坑 #6) |
| ✅ 完成日 → 年月 | 执行迭代月 | 单选 enum | 2026-05-18 加 (Phase 2.1). 模板 `{YY} 年 {M} 月`(中英混排有半角空格) |

### 反向同步字段映射(飞书 → OB Tasks 行,2026-05-18 Phase 2.2 上线)

| 飞书字段 | OB Tasks 信号 | 备注 |
|---------|--------------|------|
| 任务标题 | task 文本 + markdown link 的 [text] 部分 | 字符级原样复制 |
| 执行状态 | `[x]/[ ]/[/]/[-]` | Done/Todo/Doing/Block + Idea→[]/cancel→[-] |
| 完成时间 | `✅ YYYY-MM-DD` | **空时 fallback**:不写 ✅ + 状态降级为 [] + dry-run 警告(D7 决策) |
| 价值优先级 | `🔺/⏫/🔼/🔽` | **反向才映射**(与正向"不映射"相反 — 反向需要 emoji 决定写哪段) |
| record_id | wiki 长链 `?record=rec...` | 短链不可批量生成(坑 #5) |
| (统一今日) | `➕ <today>` | 写入位置 today journal,对齐 task-and-habits 出生地规则 |

**写入段**:有优先级 → 「🎯 今日计划」(query 块后空占位之前);无优先级 → 「🐿️ 今日非计划」

## 交付物 D 混合架构(2026-05-17 Phase 1.5 上线)

**核心痛点解决**:用户在 OB 完成 task 后产出多个交付物(教程/脚本/文档),飞书侧只看到「任务完成」,看不到"做出了什么"。

**3 种 OB 端表达方式**(扫描时合并 union 去重,以路径为 key):

### A 路径 — 同行 wikilink(轻,适合简单 task 1-3 个产物)
```markdown
- [x] [task](飞书链接) ✅ 2026-05-16 📎 [[xxx.md]] [[yyy.py]]
```
- 触发:task body 内有 `📎` emoji,后跟一个或多个 `[[wikilink]]`
- 不需要建独立笔记,适合"完成时一句话带产物"的场景

### B 路径 — callout 块(中,适合 2-5 个产物 + 带备注)
```markdown
- [x] [task](飞书链接) ✅ 2026-05-16
  > [!note]- 📎 交付物
  > - [[xxx.md]] 教程文档
  > - [[yyy.py]] 同步脚本
```
- 触发:task 行**紧跟的下一行**是 callout(类型在 `config.yaml` callout_types 列表)
- 内部 list 每行 `- [[xxx]] <备注>` 解析为 1 个产物

### C 路径 — 独立 md frontmatter 反向链接(重,适合 epic 任务)
```yaml
---
title: Mac Mini NAS 配置
delivery_for:
  - recvjLmrOiJ11K
---
```
- 触发:任意 .md 笔记的 frontmatter 字段 `delivery_for` 是 list 含目标 record_id
- sync 时扫全 vault 构建反向索引(首次扫,后续会话内缓存)
- **优点**:笔记天然按 PARA 落位,不依赖 task 行格式约定
- **示例**:[[02 Area/09  obsidian/07 Mac Mini NAS 配置.md]] 和 [[02 Area/09  obsidian/11 OSS 同步与监控通知方案.md]] 都加了 `delivery_for: [recvjLmrOiJ11K]`,作为 macmini-oss 任务的交付物索引

### 飞书侧输出格式(用户决策 2026-05-17)

```
交付物:
- [OSS 同步与监控通知方案](obsidian://open?vault=OB&file=02%20Area/...)
- [Mac Mini NAS 配置](obsidian://open?vault=OB&file=02%20Area/...)

原话备注: <用户在飞书侧已有的手工内容(如完成笔记)>

——自动同步 2026-05-17——
```

### 飞书侧双链格式升级(用户决策 2026-05-19 Phase 1.8)

> **背景**:Phase 1.7 用飞书云文档 URL 替代了 wikilink/obsidian:// 死链,但飞书侧「交付」字段只显示飞书云文档链接,**OB 本地路径丢失**。用户在飞书侧无法快速回到 OB vault 本地原版做编辑/对照。
>
> **升级**:`format_delivery_link` 在飞书云文档 URL 后追加 ` · 📁 {OB 路径}`,**双链一行展示**。

```
交付物:
- [文件显示名](https://feishu.cn/docx/<doc_token>) · 📁 01 Project/.../SKILL.md

——自动同步 2026-05-19——
```

**两个信息位**:
- **左侧** `[文件显示名](feishu URL)` — 飞书云文档可点击链接(任何协作者点开即看)
- **右侧** `· 📁 OB 路径` — OB vault 内相对路径(纯文本,用户复制路径回 OB 内 Cmd+O 直接打开原版)

**实现位置**:`sync.py format_delivery_link` 飞书云文档分支末尾 `return f"- [{display}]({doc_url}) · 📁 {rel_path}"`

**为什么用 ` · ` 分隔而不是换行**:简洁单行 + 不撑高 kanban 卡片 + 飞书 markdown 渲染稳定

**已知 UI 限制**(2026-05-19 实证):飞书周看板(kanban 视图)的**卡片正面默认只显示前几个核心字段**,「交付」字段需要**点开卡片详情**才能看到。这不是 sync.py bug,是飞书 kanban 视图的渲染策略。解决:点 record 卡片详情查看,或切换到「总表」(grid 视图)。

### 边界场景决策矩阵

| 场景 | 策略 | 实现 |
|---|---|---|
| 同一 record 在多个日志被引用 | 去重合并 union(以路径为 key) | `merge_deliveries()` |
| task 未完成但已有产物 | 不同步 | `build_fields_payload` 检查 `task['status_char'] == "x"` |
| 飞书侧"交付"字段被手工修过 | 保护:抽出原话备注,append 模式保留 | `extract_original_note()` + `build_delivery_value()` |
| 第二次 sync(现有值已含 wikilink) | 抽原话备注 → 覆盖列表 → 保留原话 | `extract_original_note()` 模式 2 |

## 飞书云文档同步(2026-05-17 Phase 1.7 上线 — 最终方案)

**痛点**:Phase 1.6 的 obsidian:// 方案被飞书 security 跳转破坏(详见事故记录),完全失效。

**最终方案**:把 .md 推到飞书云文档,「交付」字段用飞书原生 URL `https://feishu.cn/docx/<id>`。

### 工作流程

```
用户跑 sync.py
  ↓
扫日志 task → 找对应 C 路径笔记(delivery_for frontmatter)
  ↓
对每篇笔记:
  - 笔记 frontmatter 已有 feishu_doc_token? → 复用(跳过创建)
  - 没有? → 调 feishu-cli doc import --user-access-token 创建飞书云文档
    → 拿到 document_id
    → 用 update_md_frontmatter 把 token 写回 OB 笔记 frontmatter(append-only)
  ↓
format_delivery_link 用 doc_token 拼 URL
  ↓
飞书 record「交付」字段 = "- [文档名](https://feishu.cn/docx/<id>)"
```

### 前提条件(首次跑必走)

1. **OAuth 加 doc scope**:
   ```bash
   feishu-cli auth login --scope "docx:document docx:document:create"
   ```
   用户去浏览器完成 OAuth 授权(一次性,token 通常 1 年+ 有效)

2. **config.yaml 开关**:
   ```yaml
   feishu:
     enable_doc_sync: true
     doc_folder_token: null   # 默认根目录;指定文件夹 token 自动归档
     doc_url_template: "https://feishu.cn/docx/{doc_token}"
   ```

### OB 笔记 frontmatter 新增字段

```yaml
---
title: Mac Mini NAS 配置
delivery_for:
  - recvjLmrOiJ11K
feishu_doc_token: B6P4dbrPdo4Hexx6C5QcRjh8nj5   # ⭐ 飞书云文档 ID(sync 自动写入)
feishu_doc_synced_at: 2026-05-17T19:38:18       # ⭐ 上次推送时间
---
```

### 性能说明

- **首次推送一篇 .md** 到飞书云文档约 30-60 秒(含 OSS 上传 + 块拆分 + 表格并发填充)
- **复用模式**(笔记已有 doc_token):0 cli 调用,纯字符串拼接 < 10ms
- **优化方向**:用 `mtime > feishu_doc_synced_at` 检测,只在 .md 修改后才重新推(目前每次复用,不重新推)

### 失败降级

`ensure_feishu_doc` 返回 None 时(网络/权限/cli bug),`format_delivery_link` 降级:
1. 飞书云文档 URL(成功)
2. ~~Obsidian URI~~(已知失效,不再使用)
3. wikilink 兜底(死链但至少能看)

## obsidian:// URL Scheme(2026-05-17 Phase 1.6 上线 → ❌ 已废弃)

> **状态:已废弃**。详见事故记录"obsidian:// URL Scheme 被飞书 security 跳转破坏"。
> 当前代码保留 `build_obsidian_uri()` 函数供调试 / 降级使用,默认 `use_obsidian_uri: false`。

**核心痛点**:飞书侧 `[[xxx.md]]` wikilink **看得见但点不动**,失去"飞书查交付"的核心价值。

**方案**:用 Obsidian 原生 URL Scheme 把 wikilink 转换成飞书 markdown 可点击链接:
```
[显示文本](obsidian://open?vault=OB&file=<URL编码路径>)
```

**对照**:

| 配置 | 飞书侧渲染 | Mac 点击 | 手机查飞书 |
|------|----------|---------|----------|
| `use_obsidian_uri: false` | 灰色文字 `[[xxx]]` | ❌ 不可点 | ❌ 看不到内容 |
| `use_obsidian_uri: true`(默认) | **蓝色超链接** | ✅ 自动启动 OB 跳到笔记 | ⚠️ 看到文件名但点不开(手机无 OB) |

**配置位置**:`config.yaml` 的 `ob.vault_name` + `ob.use_obsidian_uri`

**vault_name 查看方式**:
- Obsidian 设置 → About → Vault name
- 或 `cat ~/Library/Application\ Support/obsidian/obsidian.json` 看 `vaults` 字典

## 必须遵守(铁律)

1. ❌ **禁止跳过 dry-run 直接 --apply** —— 类比 pudding sync,bug 早暴露
2. ❌ **禁止凭直觉假设 cli 返回结构** —— v3 API 返回平行数组(`record_id_list: ["rec..."]`),不是嵌套对象。新增 cli 命令调用必须先手动跑一次看返回 JSON 结构(2026-05-17 事故,见下方)
3. ❌ **禁止在 config 里写飞书表不存在的字段** —— 会导致整个 upsert 失败。新增字段映射前必须先 `feishu-cli bitable field list` 确认字段名拼写一致
4. ❌ **禁止用短链 `HrKrrZ1HOeDfu5cdgXMcYDYTnZg` 作为 record_id** —— 那是飞书登录态分享短链,不是 record_id。必须用长 URL `?record=recXXX` 格式
5. ✅ **写新 task 后跑 sync 才能拿到 record_id 链接** —— 不是手动到飞书复制链接。脚本自动写回到 markdown(无感知体验)
6. ✅ **私事 task 排除方式**:暂不加专门 emoji 标记,通过 `--only-completed` + 不打 ✅ 完成日就不会被同步
7. ✅ **跨周/月 enum 缺失** —— 静默跳过,不阻断其他字段写入;后台预建后下次同步会带上

## CREATE 查重(2026-05-17 Phase 1.8 上线)

**痛点解决**:Phase 1 实现"无飞书链接 → 直接 CREATE",**不查重**。导致:
- 同一日志写 2 条同名 task → 飞书出 2 条重复 record
- OB 不知道飞书后台已有手建同名 record → CREATE 第 3 条
- 跨天复制粘贴同名 task → 每次 sync 都新建一条

**Phase 1.8 方案**:dry-run 在每个 CREATE 决策前查重 + 警告(不自动合并)。

### 实施

新增函数 `build_records_title_index(config)`:
- **lazy 调用** — 第一次遇到 CREATE 决策时才调(全 UPDATE 场景不浪费 cli)
- **模块级缓存** `_RECORDS_TITLE_CACHE` — 一次 sync 仅调用 1 次
- **自动分页**:`feishu-cli bitable record list --limit 200 --offset N` 循环(cli 单次上限 200)
- 返回 `{"标题": ["recXXX", "recYYY", ...]}` 索引

### dry-run 报警格式

```
--- Task X: 【XXX】xxx
    🆕 无飞书链接 → 将创建新 record
⏳ 调 cli 拉全表 record 建标题索引(查重用)... ✅ 共 N 条 record, M 个独立标题
    ⚠️  警告:飞书已有 K 条同名 record:
       - recXXX  (打开:https://.../?record=recXXX)
       - recYYY  (打开:https://.../?record=recYYY)
    💡 apply 前你可选:
       ① 取消 sync → 复制飞书 record 长链贴到 OB task 行 → 重跑(走 UPDATE)
       ② 接受 CREATE(飞书将出现 K+1 条同名 record)
```

### 设计权衡

| 取舍 | 选择 | 理由 |
|------|------|------|
| 报警 vs 自动合并 | **仅报警** | 同名不等于同一件事(可能是周期性任务、不同上下文);自动合并风险高 |
| 模糊匹配 vs 精确匹配 | **精确匹配** | 误报多比漏报多更恼人 |
| 全量 list vs search by title | **全量 list 一次缓存** | search 命令有限流(800004135),全量 list 更稳 + 内存查 O(1) |
| Lazy vs 始终拉 | **Lazy(CREATE 时才拉)** | 全 UPDATE 场景节省 1 次 cli 调用(2-3 秒) |

### 已知限制

- 飞书表 > 10000 条时拉全表慢(50 页 × ~2 秒/页 = 100 秒)。当前用户表 402 条,~4 秒搞定
- 标题完全相同但**前后空格** / **中文标点全半角差异** 仍当作不同标题(精确字符串匹配)

## 已知坑 / 边界情况

1. **macOS pyyaml 系统自带 5.4.x,中文 dump 默认不带 unicode escape** —— 已在 config.yaml 加 `allow_unicode=True` 处理
2. **`✅` 无日期时 fallback 到今天** —— Tasks 插件勾对勾会自动加日期,但如果用户手敲 `✅` 后没填日期,脚本会写"今天"。**影响**:日终批量同步昨天日志时,这种 task 完成时间会标"今天",看起来错位
3. **优先级 emoji 不映射飞书"价值优先级"** —— Tasks 插件优先级是"紧急度"(P0=今天必做),飞书"价值优先级"是"商业价值"(P0=战略级)。两者语义不等价,所以脚本不动飞书价值优先级,由用户在飞书后台自主评估
4. **多个新 task 同时 CREATE 后 markdown 写回** —— 用顺序 Edit(找到 task 行 → 加 URL),不并发,避免行号偏移
5. **飞书 record URL 四种格式的浏览器行为不同 + 短链不可程序化生成 + base 长链全自动稳定**(2026-05-18 初版 / 2026-05-19 重大修订):
   - **短链 `feishu.cn/record/<27 位 token>`**:✅ 浏览器点击**直接弹 record 详情面板**。最佳点击体验。从飞书后台右键 record → "复制记录链接"或"分享"按钮获取
   - **🆕 base 长链 `feishu.cn/base/<base_token>?table=<tbl>&view=<view>&record=<rec>`**(2026-05-19 上线,**sync.py 现在写这种**):✅ 浏览器点击**稳定弹 record 详情面板**(用户 3 次刷新测试均稳定),等同短链体验。**完全程序化拼装**(base_token + record_id 都已知),无需任何 cli 调用 / 飞书 UI 手动操作。bitable SDK 单层路径,无 race condition
   - **wiki 长链 `feishu.cn/wiki/<wiki_token>?table=<tbl>&view=<view>&record=<rec>`**(2026-05-19 起 sync.py 不再生成,仅历史兼容):⚠️ 行为**不稳定**——有时弹 record 详情有时不弹。根因:wiki SDK + bitable SDK iframe 嵌入双层 race condition,`?record=` 参数处理依赖 SDK 协同时序,iframe 还没加载完时 wiki 容器已 ready → 参数被忽略或详情面板闪现后被关闭。**2026-05-18 初版描述"只打开表格视图不自动弹详情"不准确**,准确说法是"不稳定"
   - **纯 record_id `recXXX`**:用于 `feishu-cli bitable record upsert/get/delete --record-id`,不是浏览器 URL

   **关键限制**:**短链的 27 位 token 不能从 record_id 反推**(飞书后台 UI 专属生成,`feishu-cli bitable record` 子命令组里**没有** share-link / get-link / create-share-link 之类的命令,WebSearch + WebFetch 双确认飞书 OpenAPI 也没暴露这个 endpoint)。**但 base 长链不需要 share token——base_token + record_id 即可拼装,稳定性等同短链**,所以 2026-05-19 起 sync.py 改写 base 长链作为默认格式,完全程序化、零手动操作。

   **2026-05-19 重大升级 — sync.py 全自动 base URL 落地**:
   - **`build_record_url`(1402 行)**:`wiki/{wiki_node_token}` → `base/{base_token}`,CREATE 新 task 自动写稳定 URL
   - **`extract_record_id`(154 行正则)**:`[?&]record=(rec...)` 不挑路径,base 和 wiki 长链都自动识别(向后兼容历史 wiki 长链)
   - **`scan_vault_record_ids`(1783 行正则)**:加 `base/` 路径 `(?:wiki|base)/`
   - **dry-run 输出**(1271 行):同样改为 base URL 让 dry-run 预览一致
   - **historical backfill**(2026-05-19 已执行):inline Python 扫 journals/ 把 17 条历史 task 行 wiki 长链 → base 长链
   - **wiki node API 怎么拿 base_token**:`feishu-cli` 或 `curl /open-apis/wiki/v2/spaces/get_node?token=<node_token>`,响应里 `obj_token` 字段就是 base_token

   **AI 排障教训**(2026-05-18 OB CC 误判事故 + 2026-05-19 OB CC 浪费用户时间事故):
   - 2026-05-18:**不要把事故记录"短链不能给 cli 用"泛化成"短链不好"**。"不能给 cli 用"只针对程序化层面;**浏览器点击层面短链恰恰是最佳格式**。
   - 2026-05-19 :**OB CC 看到截图说"链接没跳到 record"时,过早信文档(坑 #5 旧版"wiki 长链不弹详情"描述)就直接判定 wiki 长链不 work,没让用户先点一条实测**。教训:**用户报告 URL 行为问题时,第一步应该让用户实测一条**,而不是凭文档下结论。同时,**实验性修改(简化 `record/recXXX` 格式)被实证无效后,应该立刻回滚 + 反思,不要继续假设**。最终通过"wiki node API 看到 obj_token = base_token"发现 base URL 全自动方案,验证三次稳定弹 record → sync.py 改 1 行 + 一次性 backfill 17 条 = 全自动达成。

   **门禁**:
   - 用户提供 `feishu.cn/record/<27 位>` 短链时:
     - ✅ 识别为"用户已经拿到了浏览器点击最佳 URL,**直接保留**写入日志 markdown link"
     - ❌ **禁止"修正"成 wiki/base 长链替换它**(破坏点击体验)
   - sync.py CREATE 新 task 时:**默认写 base 长链**,不再写 wiki 长链
   - OB CC 手写新 task markdown 链接到日志时:**用 base URL 格式**`https://<tenant>/base/<base_token>?table=<tbl>&view=<view>&record=<rec>`,不要凭习惯写 wiki 长链
   - 用户问"链接为什么不弹 record"时:**第一步让用户实测一条**,不要直接基于文档/印象下结论
   - 仅当**需要 cli 操作那条 record** 时,才用 `feishu-cli bitable record list` 按标题反查 `recXXX`(rec 开头的 record_id)
6. **执行迭代周/月 enum best match 用 cli search-options 而非 sync.py 自缓存全 list**(2026-05-18 Phase 2.1 实证):
   - cli `feishu-cli bitable field search-options --field-id <fld> --query <候选词> --limit 10` 飞书原生模糊匹配
   - sync.py 调 `best_match_enum(field_id, query, config)` → 遍历返回的 options,找第一个 `query in option.name` 的(子串校验防误匹)
   - 同会话内对 `(field_id, query)` 缓存(`_ENUM_MATCH_CACHE` 模块级 dict)避免重复 cli 调用
   - **⚠️ cli 返回顺序不保证 best match 优先**(2026-05-18 实证 query="26W20" 返回 5 个 options 第 0 个是 26W21,第 1 个才是 26W20)→ 必须**遍历**而非"取第 0 个"
   - **未命中飞书 enum 时静默跳过**(对齐 `behavior.auto_create_enum: false` 既有模式)
   - **⚠️ ISO week 跨年陷阱**:必须用 `datetime.isocalendar().year` 而非 `dt.year` —— 2026-01-01 落在 ISO 2025 第 53 周,候选词应为 `25W53`(非 `26W53`)
   - **field_id 永久不变**(即使字段重命名),写到 config.yaml 安全;但要在 derive_template 改格式时考虑用户飞书侧 enum 的现有写法是否匹配

7. **短链 task 自动反查 + rec 注释 cache 机制**(2026-05-18 Phase 2.3 上线,**取代 Phase 2.1 的"跳过短链"行为**):
   - **旧问题**(Phase 2.1):sync.py 看到短链 task → `extract_record_id` 返回 27 位 token(非 rec_id) → push 主流程检测到 `is_short_record_id` 直接 skip + 让用户手动改长链。**用户讨厌:每次都得 manage 链接格式**。
   - **新机制**(Phase 2.3):**完全自动化,用户不用 manage 链接**
     1. push 主流程看到 task 是短链(`is_short_record_id` 仍然识别)→ **不再 skip**
     2. 调 `feishu_search_by_short_link(task["title"], config)` —— 实际实现是**按标题反查飞书 record_id**(复用 `build_records_title_index` 的 lazy cache)
     3. 反查命中单一 rec_id → 走 UPDATE;**反查标记 `task["_inject_rec_comment"] = real_rec_id`**
     4. apply UPDATE 成功后 → 在 task 行末尾注入 `<!-- rec=recXXX -->` 注释 cache
     5. 下次 sync:`parse_task_line` 优先读 rec 注释(O(1)),**不再触发反查**(无 cli 调用,O 飞书 API)
   - **写入示例**:
     ```markdown
     - [x] [【财务】联系遵义和桐梓两个投资钱以及客服经理](https://.../record/BtDUrWZLz...) 🔺 ➕ 2026-05-15 ✅ 2026-05-15 <!-- rec=recvjEmwj5sABY -->
     ```
     - 短链保留(点击体验):点击进飞书直接弹 record 详情
     - 行末注释(cache):sync.py 读 rec_id,Obsidian 渲染时不可见(HTML 注释)
   - **反查歧义处理**:同名 record 多条 → 警告 + 跳过(用户人工裁决:改标题让其唯一 / 直接贴长链强制)
   - **反查失败(标题不在飞书表)**:静默跳过 + 警告
   - **关键函数**:`feishu_search_by_short_link` / `inject_rec_comment_into_line` / `parse_task_line` 注释提取分支
   - **设计取舍**:第一次 sync 每条短链反查 1 次(~3 秒,因为复用 title_index lazy cache 实际只调 1 次 cli for 所有短链),之后 0 反查

8. **反向同步(飞书 → OB)查重必须按标题 grep, 不能只查 record_id**(2026-05-18 实证):
   - **现象**:OB CC 反向同步飞书"是否今日"标记的 7 条 task 到 journals/2026-05-18.md, 其中 4 条已经存在于历史日志(5-10 / 5-14 / 5-15)→ 用户截图看到"重复"
   - **根因**:OB CC 用 `grep -rln <record_id>` 检查 vault 现有出现, **0 命中**(虚假安全感)
     - 老 task 用的是 **短链 token**(如 `feishu.cn/record/DzMmrccOoetSUWcrjowcLxTUnue`,详见坑 #5)
     - 新 task 反向同步用的是 **wiki 长链 + record_id**(`recXXX`)
     - 两者**完全不同字符串**, `grep recXXX` 必然 0 命中老 task — 但实际飞书侧是同一条 record
   - **正确查重**:必须按 **任务标题** grep 全 vault journals/, 显示老 task 位置 + 状态, 给用户决策(跳过 / 替换链接 / 强制写新)
     - 标题不需要字符级完全一致, 模糊匹配也能发现近似重复(2026-05-18 实证:"布丁内容**完全**上线**正式发布**" vs "布丁内容**上完**发布" 语义同一件事)
   - **未来 sync.py `pull_from_feishu` 真实实现时必须内置**:
     - 标题正则模糊匹配查全 vault journals/
     - 命中时显示老 task 位置 + 状态 + 链接格式(短链/长链)给用户判断
     - 用户决策:跳过本次拉取 / 把老 task 链接替换为新长链(走 UPDATE 走 sync.py) / 强制写入(知道是不同 task)
   - **门禁**(手动反向同步时):**第一步 grep 必须用标题, 不能用 record_id**;`grep -rln <record_id> journals/` 0 命中**不代表 vault 里无该 task**

9. **sync.py 跑时 cwd 不在 vault root → 用 `find_vault_root()` 找含 `.obsidian/` 的祖先**(2026-05-18 Phase 2.2 实证):
   - **症状**:`pull_from_feishu` 用 `vault_root = Path(".")` 引导出 `journal_dir` 错位(cwd 在工具目录,不是 vault root),`grep journals/` 找到 0 条,全部走"新写"路径(本应有大量"已在今日跳过" / "升级老链")
   - **根因**:Python 脚本被 `python3 path/to/sync.py` 调用时,cwd = 用户调用所在目录,**不是 sync.py 文件所在目录,也不是 vault root**
   - **正确做法**:`find_vault_root()` 函数从 cwd 向上找含 `.obsidian/` 的目录,fallback 到 sync.py 文件位置向上找
   - **门禁**:任何依赖 vault 路径的函数,**不能用 `Path(".")` 假设 vault root**;必须显式 `find_vault_root()` 或接收 vault_root 参数

10. **反向同步标题前缀 N 字 grep 模糊匹配会假阳性, 不能自动 apply 升级**(2026-05-18 Phase 2.2 实证):
    - **症状**:`recvk0vEDk9jo5`(【布丁开发】**直播功能开发**)被识别为升级 5-16.md line 32(【布丁开发】**直播功能选型调研与设计**),前 10 字"【布丁开发】直播功能"一致 → 假阳性
    - 这两个是**不同语义**(选型调研 = 调研工作,Done;开发 = 实际编码,新 task) — 如果 apply 升级会污染 5-16 老 task 的 record_id
    - **根因**:模糊匹配 = 假阳性必然存在(任何前缀长度都会有不同 task 共享前缀)
    - **正确做法**:
      - dry-run **必审**(用户人工裁决每条升级)
      - apply 时**可手动 patch**(用 inline Python 跳过特定 record_id 的升级,改为新写)
      - **未来 fix**:加 cli flag `--exclude-record <rec1,rec2>` 或 `--prompt-on-upgrade`(每条升级前 prompt y/n)
    - **门禁**:`--pull --apply` 前**必须 dry-run + 人工审升级列表**,不能盲信脚本的 best match

11. **反向同步 task 多次跑:今日 journal 内同款 task 视为"已存在,跳过"**(2026-05-18 Phase 2.2 设计):
    - `find_existing_in_vault` 返回 today journal 自己时,不算"升级"也不算"新写",而是"已在今日,跳过"
    - 设计意图:用户手动加 task 到今日 + sync.py 跑,或 sync.py 跑两次 → 都不会重复
    - **实施位置**:`pull_from_feishu` 把 existing 分为 `in_today` + `in_other`,优先级 `in_today > in_other > 新写`
    - **副作用**:今日 journal 同款 task **永远不会被升级老短链**(因为先命中今日 journal 路径)。如果今日 journal 用了短链 task,需要手动升级或下次跑前删掉它

12. **`parse_callout_below` 不容忍前导空格,标准 Obsidian 缩进 callout 被静默忽略**(2026-05-19 实证 + 修复):
    - **症状**:Task 行下用 Obsidian 标准 list-嵌套 callout 写法(`  > [!note]-` 前面 2 空格缩进)时,B 路径产物不抽,dry-run payload 无「交付」字段;但用户在 OB 笔记里渲染看上去完全正常
    - **根因**:
      - `parse_callout_below` line 181 旧 regex `r">\s*\[!(\w+)[+\-]?\s*"` 从字符串开头匹配,**`re.match` 不跳过前导空格** → 缩进 callout 第一行不匹配 → 函数返回 None → B 路径整段被跳过
      - line 190 旧循环 `while lines[i].startswith(">")` 也只看裸 `>`(不看 ` ` + `>` 缩进)→ 即使前一道关过了,后续 callout 行也只能抽到非缩进的
    - **修复**:
      - 正则前加 `\s*` → `r"\s*>\s*\[!(\w+)[+\-]?\s*"`
      - 循环改 `while lines[i].lstrip().startswith(">")`
      - 抽 callout 行内容前先 `stripped = lines[i].lstrip()` 再 `re.sub(r"^>\s?", "", stripped)`
    - **典型触发场景**:用户用 Obsidian 标准 `- [x] task` 行 + 下一行 `  > [!note]-` 写 B 路径 callout(这是 Obsidian Live Preview / Reading mode 的**推荐**写法,任何会用 callout 的用户默认都会缩进)
    - **门禁(新规)**:任何"task 行下的下一行块"解析 regex 必须容忍前导空格——**不能假设块标记从字符串开头开始**;列表嵌套缩进是 Obsidian markdown 的常态

## 8 条架构原则三次自评(2026-05-17 Phase 1.7 飞书云文档升级后)

### 1. 解耦 ✅
- 飞书云文档逻辑独立:`get_user_access_token` / `ensure_feishu_doc` / `parse_cli_output` / `update_md_frontmatter` 各司其职
- format_delivery_link 3 档降级链清晰(飞书云文档 → obsidian:// → wikilink),互不依赖
- run_cli 通过 parse_cli_output 解耦"cli stdout 格式" vs "调用方"(以后 cli 输出格式变化,只改解析层)

### 2. 可扩展 ✅
- 加新交付链接类型(如 OSS .md / Notion / Logseq URL):新增 format_xxx_link 函数 + format_delivery_link 加一档优先级
- 加 doc folder 归档:config.yaml `doc_folder_token` 一行配置
- 加"detect mtime > synced_at 才重推"优化:ensure_feishu_doc 加 mtime 比较分支

### 3. 灵活修改 ✅
- 关闭飞书云文档同步:`enable_doc_sync: false`(回到 wikilink)
- 切换文档归档位置:`doc_folder_token: <token>`
- 修飞书 URL 模板:`doc_url_template: "..."`
- 全部通过 yaml 配置切换,代码 0 改动

### 4. 渐进披露 ✅
- 用户层:dry-run 输出 "⏳ 推送 xxx.md 到飞书云文档... ✅ <id>" 一目了然
- 教学层 SKILL.md(首次跑前提 + 渲染效果 + 工作原理)
- SOP 层本文件(飞书云文档专章 + 3 次升级路径)
- 实现层 sync.py(只在 debug 时看)

### 5. 鲁棒性 ✅(从 Phase 1.5 的 ✅ 持续保持)
- ensure_feishu_doc 失败 → format_delivery_link 自动降级到 wikilink(不阻断)
- run_cli 用 parse_cli_output 兼容混合输出,失败时给具体错误
- update_md_frontmatter 用 append-only 算法,不破坏用户原 frontmatter 格式
- doc_token 缓存在笔记 frontmatter,避免重复创建飞书 doc(防止 doc 库膨胀)

### 6. 人可读 ✅
- 飞书侧输出"交付物 / 原话备注 / ——自动同步——"中文清晰分段
- 飞书云文档 URL 在飞书 markdown 渲染为蓝色超链接,任何人一眼就懂"点这里看交付"
- Python 函数 docstring 解释 3 档降级 + cli 混合输出陷阱

### 7. 高复用 ⚠️ 仍违反(Phase 1 同款)
- base_token / table_id / vault_name 仍硬编码 config.yaml
- 修复路径:多 profile config 切换(等第二张表出现时再做)

### 8. 工程化清晰 ✅
- 文件结构不变(SKILL.md + sync.py + config.yaml + rules)
- Phase 1.7 升级只增量改这 4 个文件(sync.py +5 函数,config.yaml +3 字段),无新增文件
- OAuth scope 升级在 rules 明确记录"首次跑前提"

### 跨 Phase 总结(1 → 1.5 → 1.6 → 1.7)

| Phase | 主要升级 | 8 条评分变化 |
|------|---------|-------------|
| 1.0 | OB → 飞书单向 + 5 步 SOP | 5/8 ⚠️ + 7/8 ⚠️ |
| 1.5 | 交付物 D 混合架构(A/B/C 三路扫) | 5/8 升 ✅ |
| 1.6 | obsidian:// URL Scheme(❌ 已废弃) | 反而下降:看似 5/8 ✅,实测不工作 |
| 1.7 | 飞书云文档(✅ 最终方案) | 5/8 持续 ✅, 6/8 进一步加强(URL 飞书可用) |
| 1.8 | 飞书侧双链格式(OB 路径 + 飞书 URL)+ callout parser 缩进 bug fix | 5/6 ✅ 持续,6/8 进一步强化(双信息位 = 协作者看飞书 + 自己回 OB 都顺手) |

**核心教训(写给未来的我)**:
- 跨平台 markdown 渲染兼容性差异巨大,**必须真实点击测试**才能确认链接有效
- 安全边界(security 跳转 / 协议白名单)是企业 SaaS 的标配,自定义协议大概率被拦
- 不要凭"看起来对"就推 sync.py 改动到 apply 阶段 — **每个新功能加一次"用户真实测试"环节**

## 8 条架构原则二次自评(2026-05-17 Phase 1.5/1.6 升级后)

> Phase 1 自评见后方"完整版"。本节是交付物 D 混合 + obsidian URI 两个升级后的复评。

### 1. 解耦 ✅
- 交付物 3 个 extractor 独立(`extract_inline_deliveries` / `extract_callout_deliveries` / `find_delivery_for_links`)
- URI 生成独立(`build_obsidian_uri` / `format_delivery_link`)
- 原话备注抽取独立(`extract_original_note`)
- **改一处不影响其他** — 例如换 vault 名只改 config.yaml,不动 sync.py

### 2. 可扩展 ✅
- A/B/C 之外加 D 路径只需新增 1 个 extractor + 在 `build_fields_payload` 加一行 merge
- URI scheme 之外想加飞书云文档 / OSS URL,改 `format_delivery_link` 加分支即可
- C 路径反向 frontmatter 字段名可改(`config.yaml` `backlink_field`)

### 3. 灵活修改 ✅
- 飞书侧格式纯模板字符串(`format_template` / `append_template`),改 yaml 即生效
- 用户决策"复盘字段不自动填" — 只改一行 `field_name: null`,Python 代码不动
- `use_obsidian_uri: false` 一键关闭 URI scheme 回退到 wikilink

### 4. 渐进披露 ✅
- 用户层只看 `📎 交付物 (N 个)` dry-run 预览 + 飞书侧渲染效果
- 教学层 SKILL.md(3 种写法 + 渲染示意)
- SOP 层本文件(D 混合本体 + 边界场景矩阵)
- 实现层 sync.py(只在 debug 或扩展时才看)

### 5. 鲁棒性 ✅(从 Phase 1 的 ⚠️ 升级)
- C 路径扫 vault 时跳过 `.obsidian/.git/node_modules/.trash/.claudian`(防误读)
- YAML 解析失败的笔记静默跳过,不阻断主流程
- `extract_original_note()` 双模式覆盖(纯手写 / 已 sync 过),第二次 sync 不丢原话
- cli `fetch_existing_delivery` 失败时降级到 `existing_value=""`,继续 sync(不阻断)

### 6. 人可读 ✅
- 飞书侧输出"交付物 / 原话备注 / ——自动同步——"中文清晰分段
- Python 函数每个都有 docstring 解释 A/B/C 三路区别
- 本文件用 D 混合架构 + 边界矩阵 + 渲染示意一目了然

### 7. 高复用 ⚠️ 仍违反(Phase 1 同款)
- base_token + table_id + vault_name 仍硬编码 config.yaml
- 修复路径:多 profile config 切换(等第二张表出现时再做)

### 8. 工程化清晰 ✅
- 文件结构不变(SKILL.md + sync.py + config.yaml + rules)
- Phase 1.5/1.6 升级只增量改这 4 个文件,无新增文件
- 主 CLAUDE.md skill 索引 + rules 索引保持一行

## 8 条架构原则完成后自评(强制 · 完整版)

### 1. 解耦 ✅
- sync.py 单一职责:扫日志 → 解析 task → 调 feishu-cli。**不直接调飞书 API**(走 cli 黑盒)
- 字段映射在 config.yaml(数据),不在 Python 代码(逻辑)
- OB markdown 格式 vs 飞书 field schema 解耦——两边变化不会传染

### 2. 可扩展 ✅
- 加新字段映射:改 config.yaml 加几行 `field_name: 字段名 + map: {...}`
- 切换不同多维表(其他项目):改 config.yaml 的 `base_token` / `table_id`
- 加新 OB 信号(如时长/估时):在 `parse_task_line()` 加正则 + `build_fields_payload()` 加映射
- **暂未实现的扩展点**:Phase 2 `--pull` 反向同步(已留 stub `feishu_search_by_short_link()`)

### 3. 灵活修改 ✅
- 改字段映射 = 改 yaml 一行
- 改 task 解析正则 = 改 Python 一处
- 改飞书命令 cli 调用 = 改 `run_cli()` 一处
- 回滚:git revert sync.py / config.yaml 单个文件

### 4. 渐进披露 ✅
- 用户层:`/飞书项目同步` 一个命令入口
- 教学层:SKILL.md(命令用法 + 字段映射 + 已知行为)
- SOP 层:本 rule 文件(铁律 + 边界 + 自评)
- 实现层:sync.py + config.yaml(只有需要 debug 或扩展时才看)

### 5. 鲁棒性 ⚠️ 部分违反
- ✅ dry-run + 用户审核默认 SOP
- ✅ apply 失败不会中断其他 task 处理
- ✅ cli 调用失败 raise RuntimeError + Python try/except 在调用方捕获
- ⚠️ **违反:跨周/月 enum 缺失会让单字段写入失败,虽然不阻断其他字段,但用户看不到"哪个字段失败"的明确提示**
- **修复路径**:写一个 `pre_check_enum_exists()` 函数,在 apply 前扫所有要写的 enum 字段,提示用户预建

### 6. 人可读 ✅
- Python 中文注释充分(每个函数有 docstring)
- SKILL.md 给用户看(场景化教学)
- 本 rule 文件给未来 AI 看(SOP + 事故)
- config.yaml 注释解释每个字段映射的语义

### 7. 高复用 ⚠️ 显式违反
- ⚠️ **违反:暂时硬编码 base_token + table_id + wiki_token 到 config.yaml**
- **如果未来要支持多张表**(如不同产品/不同迭代):需要做成"多 profile config"(`config-projects.yaml` / `config-self.yaml`),用 `--config` 切换
- **不影响今天 MVP**:用户只有一张项目管理表
- **未来修复**:第二张表出现时再做拆分

### 8. 工程化清晰 ✅
- 目录在标准位置:`01 Project/00 进行中/06 小工具开发/CC命令/飞书项目同步/`
- 文件分工:SKILL.md(用户入口)+ sync.py(逻辑)+ config.yaml(数据)
- SKILL.md frontmatter 让 Claudian 通过自然语言触发("同步飞书项目")
- 命令暴露层级:CLI 直跑 + Skill 触发 + 主 CLAUDE.md rules 索引引用

## 维护本 rule

发现新坑 / 新事故 → 加到「已知坑」section
扩展 Phase 2 反向同步 → 单独立项写 spec(参考 [[04 Inbox/superpowers/specs/2026-05-17-OB飞书项目同步设计.md]] 待写),完成后回填本文件「飞书 → OB 反向同步」section

## 演示成功记录

**2026-05-17 MVP 首次验收**:
- 文件:`journals/2026-05-16.md` (6 个 [x] task)
- 命令:`python3 sync.py "journals/2026-05-16.md" --only-completed --apply`
- 结果:1 UPDATE(macmini-oss `recvjLmrOiJ11K` 复盘字段 null → `[[journals/2026-05-16]]`)+ 5 CREATE(新建 record + 自动写回链接到 markdown)
- 端到端验证:
  - 飞书侧 6 条 record 字段正确(任务标题 / 执行状态=Done / 完成时间 / 复盘 wikilink)
  - OB 笔记 6 行 task markdown 链接全部自动更新(从无链接 → 长 URL 带 record_id)

## 事故记录

### 2026-05-17:obsidian:// URL Scheme 被飞书 security 跳转破坏 → Phase 1.7 升级飞书云文档

**症状**(用户截图验证):
- Phase 1.6 用 `[文本](obsidian://open?vault=OB&file=...)` 替代死链 wikilink
- dry-run 输出看起来"完美":蓝色超链接 + 中文正确 URL encode
- **但用户点击后**:URL 被飞书改写成 `https://security.feishu.cn/link/safety?target=http%3A%2F%2Fobsidian%3A%2F%2F...` → 浏览器打开空白页

**根因(2 层叠加)**:
1. **飞书 security 跳转**:所有外部链接被强制走 `security.feishu.cn/link/safety` 中间页(防钓鱼)
2. **协议白名单**:中间页只识别 `http://` 和 `https://`,自定义协议 `obsidian://` 被错误地包装成 `http://obsidian://` → 完全失效

**门禁(我犯的错)**:
- ❌ **没实测就推**:我之前推 obsidian:// 方案时,只看 dry-run 输出"看起来对"就让用户 apply。**违反「跨工程行为诊断 3 项核对」**(应该先创建测试 record + 真实点击 + 看跳转效果)
- ❌ **没"≥3 反证"**:看到 URL encode 正确就觉得能工作,没考虑飞书 security 跳转 / Obsidian Surfing 内嵌浏览器协议拦截等可能性

**修复(Phase 1.7 上线,2026-05-17)**:
切换到**飞书云文档 URL**(https,绕过 security 拦截):
- 加 `ensure_feishu_doc(md_path)` 函数:用 `feishu-cli doc import --user-access-token` 把 .md 推到飞书云文档
- doc_token 写回 OB 笔记 frontmatter `feishu_doc_token` + `feishu_doc_synced_at`(缓存,避免重复创建)
- `format_delivery_link` 优先用飞书云文档 URL `https://feishu.cn/docx/<id>`,失败降级 wikilink

**前提条件**(用户首次跑必走):
1. 飞书 OAuth 加 `docx:document` + `docx:document:create` scope:`feishu-cli auth login --scope "docx:document docx:document:create"`
2. 用户去浏览器完成 OAuth 授权(一次性)

**新增配置**(config.yaml):
- `feishu.enable_doc_sync: true` — 开关
- `feishu.doc_folder_token: null` — 默认根目录,可指定文件夹
- `feishu.doc_url_template: "https://feishu.cn/docx/{doc_token}"`

### 2026-05-17:cli `doc import` 输出混合 progress + JSON 导致 run_cli 解析失败

**症状**:`doc import` 看起来失败("失败:cli 返回无 document_id"),但其实 cli 实际推送成功了(后台手动跑 + grep document_id 能找到)

**根因**:`doc import` 是长任务(60+ 秒),cli 边跑边打印 progress(`已创建文档...` / `=== 阶段 1/3 ===` 等),JSON 结果只在最后。我的 `run_cli` 用 `json.loads(整个 stdout)` 解析失败 → 走 fallback 路径返回 `{"_raw": ...}` → 调用方拿不到 document_id

**修复**:加 `parse_cli_output()` 函数 —— 从 stdout 末尾倒着扫,找最后一个完整 JSON 对象(`{` 到对应 `}`),解析这段

**门禁**:**新 cli 命令调用前必须手动跑一次看 stdout 结构**(可能是纯 JSON / 混合输出 / 多行 JSON)。run_cli 解析失败时要给具体错误信息(stdout 前 200 字符),不要静默吞错

### 2026-05-17:update_md_frontmatter 用 yaml.dump 整体重写导致 frontmatter 格式被扰动

**症状**:`ensure_feishu_doc` 调 `update_md_frontmatter` 写回 `feishu_doc_token` 后,OB 笔记的 frontmatter 被 PyYAML 重新 dump,原有的 list 缩进(2 空格)和引号风格(双引号)全部变成 PyYAML 默认风格(0 空格 + 单引号)

**根因**:用 `yaml.dump(整个 dict)` 重写 frontmatter,会丢失原始格式信息

**修复**:重写为 **append-only 字符串拼接** 算法:
- 已有 key → 用正则替换那一行(只改值,保留行其他格式)
- 新 key → 在 frontmatter `---` 之前追加 `key: value` 行
- 100% 不动其他原有内容

**门禁**:**自动修改用户文件 frontmatter 时不要整体重写**(用 yaml.dump 整个 dict)。只能 append-only / 局部替换。**用户的写作习惯 / 格式偏好优先于代码方便**

### 2026-05-17:首次 sync 「交付」字段被发现是"死链 wikilink"

**症状**:Phase 1 sync 把 `[[xxx.md]]` wikilink 写入飞书,飞书 markdown 渲染显示为灰色文字但不可点击,失去"飞书查交付"的核心价值。

**根因**:wikilink 是 Obsidian 私有语法,飞书原生 markdown 不识别。`[[]]` 在飞书侧只是字面文本。

**修复**:
- 加 `build_obsidian_uri()` 函数生成 `obsidian://open?vault=OB&file=<URL编码路径>`
- 加 `format_delivery_link()` 把 wikilink 转换成飞书可点击的 markdown 链接 `[显示文本](obsidian://...)`
- config.yaml 加 `ob.vault_name` + `ob.use_obsidian_uri` 开关

**门禁**:跨平台 markdown 同步必须考虑各平台**渲染兼容性**(飞书 / 微信公众号 / Notion 等都有自己的 markdown 方言)

### 2026-05-17:第二次 sync "原话备注"丢失风险(已提前修复)

**症状**(预测):第一次 sync 把"交付物 + 原话备注"写入飞书后,第二次 sync 时:
- `fetch_existing_delivery` 读到的值含 wikilink → 走"覆盖模式"
- 覆盖模式只输出新的交付物列表,**丢失了"原话备注"段**

**修复(实施前发现并修复)**:
- 加 `extract_original_note()` 函数支持双模式抽取:
  - 模式 1(首次):纯手写值(无 wikilink + 无锚点)→ 全文作为原话
  - 模式 2(已 sync):用正则 `原话备注[::]\s*(.+?)(?=\n\n——自动同步|\Z)` 抽出
- `build_delivery_value()` 统一调用 `extract_original_note()`,有原话就 append,没有就纯覆盖

**门禁**:跨次 sync 的字段值演化要考虑"我上次写了啥 / 这次怎么不丢用户内容",**写入幂等性 ≠ 数据保留性**

### 2026-05-17:v3 API 返回结构假设错误导致首次 CREATE 全失败

**症状**:首次跑 --apply 时 UPDATE 成功 1/1,但 CREATE 4/4 全部报错 `'list' object has no attribute 'get'`

**根因**:写脚本时凭印象写了
```python
new_id = result.get("data", {}).get("record", {}).get("record_id")
```
但实际 cli v3 API 返回是**平行数组结构**:
```json
{
  "data": [["_test_delete_me"]],
  "field_id_list": ["fldB4X80C1"],
  "fields": ["任务标题"],
  "record_id_list": ["recvjRIs1YZSj0"]
}
```
`result.get("data", {})` 实际是 list `[["..."]]`,不是 dict,继续 `.get("record")` 报错

**修复**:改成 `record_id_list[0]`(参考 [[feishu.md]]「v3 list 返回结构」段)

**门禁**:新增 cli 命令调用前**必须手动跑一次看返回 JSON 结构**,不能凭 v1 印象写解析代码

### 2026-05-17:误以为分享短链 = record_id

**症状**:用户笔记里的 `[task](https://vbn7n4vn7h.feishu.cn/record/HrKrrZ1HOeDfu5cdgXMcYDYTnZg)`,首次尝试用 `HrKrrZ1HOeDfu5cdgXMcYDYTnZg` 当 record_id 调 cli,报 cli 找不到 record

**根因**:飞书后台 `/record/<27 位字符>` 是登录态分享短链,不是底层 record_id。真正的 record_id 是 `rec` 开头(如 `recvjLmrOiJ11K`),拼装在长 URL `?record=rec...` 里

**修复**:
- 临时手动改 OB 笔记:把短链替换成长 URL(用户后续新 task 都通过本脚本自动建,不会再有短链)
- 长期 Phase 2:加 `feishu_search_by_short_link()` 实现按"任务标题文字匹配"反查 record_id

## 关联文件

- skill 入口:[[01 Project/00 进行中/06 小工具开发/CC命令/飞书项目同步/SKILL.md]]
- 主脚本:[[01 Project/00 进行中/06 小工具开发/CC命令/飞书项目同步/sync.py]]
- 配置:[[01 Project/00 进行中/06 小工具开发/CC命令/飞书项目同步/config.yaml]]
- 同类技能参考:[[.claude/rules/pudding-platform.md]]「sync 前类型判断 + 预检 SOP」
- 飞书 API breaking changes:[[.claude/rules/feishu.md]]
- Phase 2 反向同步 spec(待写):`04 Inbox/superpowers/specs/2026-05-17-OB飞书项目同步设计.md`
