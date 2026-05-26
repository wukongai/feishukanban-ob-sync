# Changelog

> `feishukanban-ob-sync` — Obsidian ↔ 飞书项目管理多维表双向同步工具。

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
