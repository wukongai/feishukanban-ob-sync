# Changelog

> `feishukanban-ob-sync` — Obsidian ↔ 飞书项目管理多维表双向同步工具。

## [v0.3.1] - 2026-05-26 — `--vault` 参数 + 完成段裸链转 link + today_history 残留清理 + 快记任务跨日支持

> 四块 patch 合并:`--vault` CLI 参数、`inject_completion_link`、`pull-today` today_history 残留清理、`快记任务` 跨日 dateContext(OB handoff 移交)。

### 🎯 块 ① — `--vault` 参数 + 项目级 settings.json

#### 问题背景

Claude Code 在跑 `cd /Users/aim5/Documents/OB && python3 .../sync.py --pull-today` 这类命令时,**每次都弹 permission 授权窗** — 哪怕给 `Bash(python3:*)` 开了 allow 也没用。根因:Claude Code 的 allowlist 是**前缀匹配**,`cd` 开头会绕过所有 allow 规则。

#### sync.py 新增 `--vault <path>` 参数

```bash
# 新写法(命令开头是 python3,allowlist 友好)
python3 /path/to/sync.py --vault /Users/aim5/Documents/OB --pull-today

# 老写法仍然可用(从 vault 内任意子目录跑,自动找 .obsidian/)
cd /Users/aim5/Documents/OB && python3 /path/to/sync.py --pull-today
```

实现细节:`main()` 最开头若收到 `--vault`,校验 `.obsidian/` 存在后 `os.chdir(vault_path)`,其余代码完全不动 — **100% 向后兼容**,不传 `--vault` 时行为完全等价于 v0.3.0。

#### 4 个 UserScript 同步更新

`quickadd-拉今日todo.js` / `quickadd-完成task.js` / `quickadd-快记任务-v2-task-md.js`(2 处)从 `cd "${vaultRoot}" && python3 "${syncScript}" ...` 改为 `python3 "${syncScript}" --vault "${vaultRoot}" ...`。颗粒度统一,去除对 cwd 的隐式依赖。

#### 新增项目级 `.claude/settings.json`

allow 本项目实际会用到的命令(python3 / pip3 / feishu-cli / 常见 git 子命令 / 只读工具),deny 危险操作(force push / reset --hard / 写 config.yaml)。其他 CC 用户 clone 仓库后开箱即用,无需各自重复授权。

---

### 🔗 块 ② — `inject_completion_link`:完成段裸 checkbox 自动转带链 markdown

#### 问题

`task 模版.md` 的「## ✅ 完成标记」段写了 `- [ ] <title>`,UserScript 文案说"sync 后自动改为带飞书 record URL 的链接",但 sync.py 此前**没实际实现**这一步。结果 dataview TASK 渲染时看不到点击直达飞书的链接。

#### 实现

新增 `inject_completion_link(md_path, title, record_url) -> bool` 函数,在 `push_task_md` CREATE 流程末尾调用:
- 找「## ✅ 完成标记」H2 段标题
- 该段下第一个 `- [ ]` / `- [x]` checkbox 行
- 行 body 替换为 `[<原 body>](record_url)`,变成 dataview 可点击 link
- 幂等:已是 `[text](url)` 形式 → 不动;UPDATE 流程不触发(行可能已被用户手改)

---

### 🧹 块 ③ — `pull-today`:today_history 残留清理

#### 问题

v0.3.0 的 `today_history` append-only 设计有一个未覆盖场景:
- 用户飞书勾「是否今日」→ sync.py set OB `today=true` + append `today_history`
- 用户飞书取消「是否今日」→ sync.py set OB `today=false`,**但 today_history 仍含今日**
- journal dataview 用 `contains(today_history, this.file.day)` → 任务仍渲染在今日 journal
- 用户期望:取消今日 = 今日 journal 不再显示

#### 实现

`_scan_ob_task_md_by_feishu_record` 抽取 `today_history` 字段;`pull_today_from_feishu` 的 `plan_set_false` 触发条件改为 `entry["today"] OR (今日 in today_history)` — 当 OB today_history 含今日但飞书取消今日时,也走 set_false(并清理 today_history 中的今日,若实现细节如此)。`_scan` 返回字典加 `today_history: list[str]` 字段。

> 注:本块完整 spec 详见 sync.py 函数内注释,本 CHANGELOG 主要给版本对齐用。

---

### 🕐 块 ④ — `快记任务`:跨日 dateContext(OB handoff 移交)

#### 问题

Mac 系统时区 `America/Los_Angeles` + 用户在北京工作的跨日场景:
- PDT 5-26 晚 18:26 = 北京 5-27 早 09:26
- 用户在 `journals/2026-05-26.md` 工作(心理上还在 5-26)
- 跑 Cmd+P「📝 快记任务」 → userscript 用 `bjDate` = `2026-05-27`
- 新 task 文件名 `2026-05-27-xxx.md`,frontmatter `today_history: [2026-05-27]`,`日志: [[journals/2026-05-27]]`
- 用户当前 journal(5-26) dataview 查 `contains(today_history, "2026-05-26")` → false → **task 不显示,体验上"消失"**

#### 实现

`obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js` 顶部加 `getDateContext(app)` helper:
- 当前 active file 是 `journals/YYYY-MM-DD.md`(严格正则)→ 用 journal 日期
- 其他场景(task md / 任意 md / 无 active file)→ fallback 北京时间(原 bjDate 行为)

Step 4 把 `bjDate` 替换为 `dateContext`(影响:文件名前缀 / `日志:` wikilink / `today_history` 初值);新增 `createdISO = ${dateContext}T${bjISO.slice(11)}` 替代 `bjISO` 写入 `created` 字段(日期跟随上下文,时间部分始终北京时间,跨工程时间戳一致)。

#### 边界

- 用户在 `journals/2026-05-26.md` → `dateContext = "2026-05-26"`
- 用户从 task md / Inbox / 任意 md 触发 → `dateContext = bjDate`
- Obsidian 启动后直接 Cmd+P(无 active file)→ `dateContext = bjDate`
- 非标准命名 journal(如 `journals/detail/2026-05-26 周二.md`)→ 不匹配正则 → fallback bjDate(保守行为)

详见 `docs/handoff/OB对接/2026-05-26-userscript-跨日-handoff.md`。

---

### 🔧 升级路径(全部四块统一升)

老用户拉了 v0.3.1 后需要:
1. `git pull`(只动 sync.py / userscript / settings.json,不动 config.yaml)
2. **重装 UserScripts**:`bash install.sh --apply --force`(覆盖 vault 里的 4 个 userscripts/*.js)
3. 重启 Obsidian(QuickAdd 重新加载 userscripts)
4. 重启 Claude Code(项目级 settings.json 在会话启动时加载)
5. 新建 task md 验证:`inject_completion_link` 是否把「✅ 完成标记」段裸 checkbox 自动改成带链 link
6. 飞书勾今日 → 跑 `python3 sync.py --vault /OB --pull-today --apply` → 再取消飞书今日 → 再跑一次 → 验证 today_history 中的今日被清,journal 不再渲染
7. 跨日测试:在 `journals/<昨天>.md` 中跑 Cmd+P「📝 快记任务」 → 验证新 task 文件名前缀 / `today_history` / `日志` 都是「昨天」日期

### 📊 已知 follow-up

- sync.py line 180 有个 `\s` regex SyntaxWarning(无功能影响),P3 修
- `scan_vault_record_ids` (老 `--pull` 流程)的 `vault_root = Path(".")` 仍是 hard-code,但因 `--vault` 已 chdir,实际行为正确;P3 改成 `find_vault_root()`

---

## [v0.3.0] - 2026-05-26 — **今日聚焦历史保真:`today_history` 事件流**

### 🎯 问题背景

v0.2.0 用 `today: true/false` 单字段管理"是否今日"。痛点:**全局 single source of truth,改 1 次影响所有历史 journal**。场景:
- 5/26 标 today=true,做了一半
- 5/27 早上飞书取消「是否今日」+ `sync.py --pull-today` → OB today=false
- 回看 5/26 journal,dataview 查 `WHERE today=true` → **task 消失**,历史丢失

dataview 是实时投影,无法做"时间穿越"。

### ✨ 解决方案:事件流持久化

task md frontmatter 新增 `today_history` 字段(YAML inline list,append-only,去重):

```yaml
today: false                  # 当前状态(动态)
today_history:                # 事件流:曾经 today=true 的日期列表
  - 2026-05-26
  - 2026-05-27
```

dataview 查询改为 `contains(today_history, this.file.day)` → **5/26 journal 永远显示曾经在 5/26 聚焦过的 task**,不论后续 today 字段如何变化。

### 🔧 实施细节

#### sync.py 改动

1. **`_format_yaml_value`** 加 list 支持(`[a, b, c]` inline 格式),底层 enabler 让 `update_md_frontmatter` 能写 list 字段
2. **`pull_today_from_feishu`** 在 set OB today=true 时,read 当前 today_history → append 当日(去重)→ 一次性 update both fields
3. **`_create_task_md_from_feishu_record`**(`--pull-today --apply` 自动建 task md 时)初始化 `today_history: [{today_date}]`
4. **设 today=false 时**:**不动 today_history**(历史保留)

#### Obsidian assets 改动

- **`quickadd-快记任务-v2-task-md.js`**:创建 task md 时 init `today_history: []`(空 list,等用户飞书勾今日时 sync.py 自动 append)

### 🔄 OB 端配套(独立改动)

OB CC 同步改:
- **task md 模板**(`03 Resources/素材库/模版/task 模版.md`)加 `today_history` 字段定义
- **journal 模板 + 今日 journal**:「🎯 今日计划」+「🐿️ 今日非计划」dataview 查询从 `today = true` 改为 `contains(today_history, this.file.day)`
- **历史 task 批量 backfill**:扫 12 个 today=true 的 task md,根据 created 日期 init today_history
- **rules 更新**(`feishu-project-sync.md`「今日 todo 双层架构」section 加事件流持久化说明)

### 📐 设计要点

- **append-only**:取消 today 不删除历史(允许"曾经"语义)
- **去重**:同一天反复设 today=true 只 append 1 次
- **类型安全**:`_format_yaml_value` 递归处理 list 元素,纯日期 → 无引号,符合 dataview 类型推断
- **向后兼容**:无 today_history 字段的旧 task md → `contains` 返回 false → 不显示(自然降级,需 backfill 或 sync.py 自动维护)

### 🆙 升级路径(OB 端)

1. 拉新版 sync.py(symlink 用户自动同步)
2. 跑一次 `sync.py --pull-today --apply` → 所有飞书侧 today=true 的 task 自动 init today_history
3. 历史 task 跑 backfill 脚本(参考 OB CC 实施记录)
4. 模板 + journal 模板 + 今日 journal 改 dataview 查询条件

### 🐛 已知边界

- task md 创建时 today_history=[],只有走过 `sync.py --pull-today` 才会 append。如果用户跳过 sync 直接手敲 `today: true` → today_history 不变,需手动维护或下次 pull-today 自动修复
- dataview `contains([2026-05-26], this.file.day)` 当 list 元素为 string 时,this.file.day 是 date 对象,dataview 内部做类型匹配(实证可行)

---

## [v0.2.0] - 2026-05-26 — **task md 化架构 + 完整工作流 + 一键部署**

### 🎯 重大架构升级 — task 升级为 "first-class entity"

v0.1 是 inline 子弹笔记式(`- [ ]` 在 journal 内,emoji 元数据),v0.2 把每个 task 升级为**独立 md 文件**,frontmatter ↔ 飞书 20 字段 **1:1 对齐**:

- 每个 task = `04 Inbox/task/YYYY-MM-DD-<标题>.md` 独立笔记
- frontmatter 18 字段:`priority` / `status` / `today` / `category` / `subcategory` / `adhd_priority` / `estimate_hours` / `feishu_record` / `feishu_url` / `iteration_week` / 等
- 正文 5 个 H2 段:`📝 执行概述` / `✅ 验收条件` / `💡 执行思路` / `🔗 相关资料` / `🪞 复盘`
- 跨日全景视图 — `_task.base` 6 个视图(🎯今日计划 / 🐿️今日非计划 / 🔥待抢救 / ⏰有 DDL / ✅已完成 / 📋全部)

### ✨ 新增功能

#### 1. 🎯 三大工作流场景全闭环

| 场景 | 工作流 | 触发 |
|------|--------|------|
| ① **OB 创建 task → 飞书** | 弹优先级 → 输标题 → 自动 CREATE 飞书 record | Cmd+P 「📝 快记任务」 |
| ② **飞书今日 todo → OB 日志** | 飞书 app 勾「是否今日」=true → 拉到 OB today journal 渲染 | Cmd+P 「📥 拉今日 todo」 |
| ③ **自动统计今日工作** | git commit + 文件改动 → LLM 归纳为主题 → 写日志 + batch CREATE 飞书 | Claudian 对话关键词 |

#### 2. ⌨️ 4 个 QuickAdd UserScript(Cmd+P 入口)

存放于 `obsidian-assets/userscripts/`:
- `quickadd-快记任务-v2-task-md.js` — 场景 ①(主入口,2026-05-25)
- `quickadd-拉今日todo.js` — 场景 ②(2026-05-26)
- `quickadd-完成task.js` — task 完成 + sync 飞书一键闭环(2026-05-26)
- `quickadd-同步飞书项目.js` — 批量 sync(走 dry-run + 审批)

#### 3. 🔧 `sync.py` 新增 `--task-md` 和 `--pull-today` 模式

```bash
# task md 模式(2026-05-25):单条 task md 推送飞书 CREATE/UPDATE
python3 sync.py --task-md path/to/task.md --apply

# 今日 todo 同步(2026-05-26):飞书「是否今日」=true → OB frontmatter today=true
python3 sync.py --pull-today --apply
```

#### 4. 🤖 `auto_collect_today.py` helper(场景 ③)

`scripts/auto_collect_today.py` — 扫今日 git commits + vault 文件改动,输出 JSON 给 LLM 归纳。

#### 5. 🚀 `install.sh` 一键部署

新用户从 0 到能用的 onboarding 从 30 分钟降到 5 分钟:
- 自动 symlink scripts 到 vault
- 复制 templates / base / rules 模板到 vault
- 生成 QuickAdd choices JSON snippet 让用户粘贴

### 🔴 铁律 #1 飞书例外扩展(3 种自动 apply 场景)

| 场景 | 触发 | 操作类型 | 风险 |
|------|------|--------|------|
| 单条 CREATE 新 task | Cmd+P「📝 快记任务」 | CREATE | 空 record,无覆盖 |
| 单条 UPDATE 完成 task(新) | Cmd+P「✅ 完成当前 task」 | UPDATE | 只改 status/done_date |
| pull-today 同步 today 字段(新) | Cmd+P「📥 拉今日 todo」 | UPDATE OB frontmatter | 不写飞书,无破坏 |

### 🗂 obsidian-assets/(新增整套 OB 资产)

```
obsidian-assets/
├── userscripts/   (4 个 QuickAdd UserScripts)
├── templates/     (task 模版)
├── base/          (_task.base 6 视图)
└── rules/         (feishu-project-sync.md 主规则)
```

### 📚 文档大幅扩充

- `docs/ARCHITECTURE.md`(新)— 系统架构 + 数据流图
- `docs/feishu-schema.md`(新)— 飞书表 22 字段定义 + 一键创建命令
- `docs/tutorial/05-task-md-workflow.md`(新)— v0.2 主流程教程

### ⚠️ Breaking Changes(v0.1 → v0.2)

- **配置文件结构变化**:`config.yaml` 加 `task_md_fields` section(原 `fields` section 不变)
- **新增飞书字段依赖**:必须先用 `feishu-cli bitable field create` 加「是否今日」字段(参考 `docs/feishu-schema.md`)
- **老 `--pull` 模式标记 legacy**:仍可用,但建议改用 `--pull-today`(写到 task md frontmatter 而不是 journal inline)

### 🛠 修复

- `_format_yaml_value` 加 boolean 支持(原 `str(True)` = "True" 大写,改为 "true" 小写,符合 YAML 标准 + dataview 解析)

---

## [v0.1.0] - 2026-05-19 — **初版开源**

### 核心功能

- `sync.py`:OB journal task ↔ 飞书 record 双向同步
  - 正向 sync:OB 勾 [x] → 飞书自动填字段
  - 反向 pull:飞书「是否今日」→ OB 日志写 inline
  - 短链自动反查 + record_id O(1) cache
  - 字段映射 yaml 配置驱动
- 4 篇 tutorial(`docs/tutorial/01-04`)
- skill-claude-code.md(让 Claude Code 用户一键调用)
- 完整 README + INSTALL(30 分钟新手 onboard)

### 关键 bug 修复(对比内部版本)

- `inject_url_into_line` 保留所有 emoji 到行尾(原正则只匹配第一个 emoji 前空白)
- base URL 替代 wiki 长链(wiki SDK + bitable SDK iframe race condition 修复)
- 短链自动反查机制(用户不再需要管短链/长链转换)

---

## 设计哲学

详见 `docs/ARCHITECTURE.md`「8 条架构原则反向打分」section。
