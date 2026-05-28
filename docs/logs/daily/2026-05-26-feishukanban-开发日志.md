---
title: 2026-05-26 feishukanban-ob-sync 开发日志
type: daily-log
date: 2026-05-26
tags: [daily, v0.2.0, v0.2.1, v0.2.2, v0.2.3, v0.2.4, v0.2.5, v0.3.0, 大架构升级, task md化, install.sh, today_history]
related: ["[[../../VERSION]]", "[[../../../CHANGELOG]]"]
---

# 2026-05-26 feishukanban-ob-sync 开发日志

> **凌晨 4 小时一次性产品化重构** + 当日陆续 patch — 一日 7 个版本(v0.2.0 → v0.3.0)。
> 项目从 inline 子弹笔记升级到 task md「first-class entity」+ 完整 Cmd+P 工作流 + 一键 install.sh。

> ⚠️ 本日志为 **2026-05-28 凌晨回写**,基于 git log + CHANGELOG.md 重建,token / 时长无精确记录。

---

## 会话 1:v0.2.0 — task md 化大架构升级 + 完整工作流 + 一键部署(凌晨 4h 一次性重构)

⏱️ 时长:约 4h(凌晨集中)
🎯 主题:**架构级 MINOR bump 跨边界例外**

### 🏗 task 升级为「first-class entity」

**之前**(v0.1.x):task = journal 里的 inline 子弹笔记行(`- [ ] [...]`),用 emoji 携带元数据。
**之后**(v0.2.0):task = 独立 md 文件 + frontmatter 与飞书 22 字段 1:1 对齐。

### ✨ 新增 — 3 大工作流场景全闭环

| 场景 | 流程 | 入口 |
|---|---|---|
| ① **OB 创建 task → 飞书** | 弹优先级 → 输标题 → 自动 CREATE 飞书 record | Cmd+P 「📝 快记任务」 |
| ② **飞书今日 todo → OB 日志** | 飞书 app 勾「是否今日」=true → 拉到 OB today journal 渲染 | Cmd+P 「📥 拉今日 todo」 |
| ③ **完成 task 同步飞书** | 打开 task md → Cmd+P → inline ☑ + frontmatter done + 飞书 UPDATE Done | Cmd+P 「✅ 完成当前 task」 |

### ⌨️ 4 个 QuickAdd UserScripts(Cmd+P 入口)

- 📝 `quickadd-快记任务.js`(v2 task md 版)
- 📥 `quickadd-拉今日todo.js`
- ✅ `quickadd-完成task.js`
- 🎯 「同步今日 task 到飞书」由 Claudian 接管(无独立 userscript)

### 🔧 sync.py 新增

- `--task-md` flag:接受 task md 文件路径,推到飞书 CREATE / UPDATE
- `--pull-today` flag:从飞书拉今日 todo 到 OB
- 22+ 字段映射(完整 frontmatter ↔ 飞书 schema)

### 🤖 `auto_collect_today.py` helper(场景 ③)

跟 Claudian 说「统计今天工作」→ 扫 git + 文件改动 → LLM 归纳 → 写日志「📊 今日自动统计」+ batch CREATE 飞书 Done record。

### 🚀 `install.sh` 一键部署

- symlink scripts(sync.py / auto_collect_today.py)到 vault
- symlink 4 个 UserScripts
- 复制 task 模板 + base 视图 + rules 文档(检查 mtime,默认不覆盖)
- 输出 QuickAdd choices JSON snippet 让用户粘贴
- dry-run + `--apply` 双模式 + `--force` 覆盖

### 🗂 `obsidian-assets/`(新增整套 OB 资产)

```
obsidian-assets/
├─ userscripts/(4 个 QuickAdd UserScripts)
├─ templates/task-template.md
├─ base/_task.base(6 视图全景)
└─ rules/feishu-project-sync.md
```

### 📚 文档大幅扩充

- ARCHITECTURE.md(完整架构图)
- feishu-schema.md(22 字段定义 + cli 一键创建命令)
- INSTALL.md(详细安装步骤)
- tutorial/05-task-md-workflow.md(主流程教程)
- README 重写(用户视角主入口)

### ⚠️ Breaking Changes(v0.1 → v0.2)

- task 数据结构从「journal inline 行」迁移到「独立 task md」
- 老 v0.1.x 用户需手动迁移 task(暂无自动 migration 脚本)

### 🤝 跨边界例外

此次大改动是 **OB Claudian 在 OB vault 跨边界做的产品化重构**,经用户显式授权。**一次性例外,v0.3+ 起改回独立 CC 开发**。

### 决策记录

- **为什么凌晨 4h 一次性做**?用户痛点累积已久 + 上线节奏快 + 跨多个文件改 → 一次性产品化重构比拆分上线更顺。
- **为什么 OB CC 跨边界做**?当时只有 OB Claudian 在使用,仓库独立 CC 还没设置好。事后改了 `.claude/rules/cross-project.md`,新规则:**v0.3+ 改回独立 CC**。

---

## 会话 2:v0.2.1 — patch:UserScripts sync.py 路径硬编码修复

⏱️ 时长:估算 0.3h
🎯 主题:**patch hotfix**

### 🐛 bug

v0.2.0 install.sh 新装路径变了(`scripts/feishukanban-ob-sync/`),但 4 个 UserScripts 内 sync.py 路径还是老的(硬编码到 v0.1.x 路径)→ Cmd+P 全部找不到 sync.py。

### 🛠 修法

UserScripts 内 sync.py 路径改成 install.sh 新路径。`install.sh` 同步更新输出的 QuickAdd choices JSON snippet。

---

## 会话 3:v0.2.2 — feat:创建 task 时弹大项目选择,自动归类到飞书「项目」字段

⏱️ 时长:估算 0.5h
🎯 主题:**MINOR feat(凌晨产品化重构延续)**

### ✨ 新功能

`quickadd-快记任务` 在标题输入前**弹大项目选择菜单**(读 OB vault 一级项目列表 `01 Project/00 进行中/*/`),用户选好大项目后自动:
1. task md frontmatter 加 `parent_project: "[[<项目名>]]"`
2. sync.py CREATE 飞书 record 时,把项目名映射到飞书「项目」字段

### 🛠 实施

- `quickadd-快记任务-v2-task-md.js`:加 `quickAddApi.suggester` 弹大项目菜单
- `sync.py`:`parse_task_md` 抽 `parent_project` frontmatter,`build_fields_payload` 映射到飞书

---

## 会话 4-7:v0.2.3 - v0.2.5 + v0.3.0 — task md 化架构持续优化

⏱️ 累积时长:约 3h(全天分散)
🎯 主题:**架构完善 + 关键 bug fix + 历史保真**

### v0.2.3 — parent_project link 字段适配

- 飞书侧「产品项目」是 link 字段(不是 select),需要解析 record_id
- 实施:`sync.py` 加 link 字段处理(去 OB 项目名数字前缀,匹配关联表 record_id)

### v0.2.4 — `today_flag` 字段 + override_map

- task md frontmatter 加 `today: true/false` → 飞书「是否今日」checkbox
- `override_map`:OB 项目名 → 飞书 record 名直接映射(用于 OB 项目名 ≠ 飞书 record 名)

### v0.2.5 — `--pull-today` 自动建 OB 端无对应 task md

- 飞书 today=true 但 OB 端没对应 task md(可能用户在飞书 app 临时建的)→ `pull-today` 自动建 OB task md
- 新增 `_create_task_md_from_feishu_record` 函数
- 同时修 set today=false 时同步从 today_history remove 今日(对称设计)

### v0.3.0 — **历史保真:`today_history` 事件流**

🏷️ commit:`c779ab5`
🎯 主题:**架构升级(dataview 时间穿越)**

#### 🎯 问题背景

dataview 是**实时投影**,无法做「时间穿越」。v0.2.0 用 `today: true/false` 单字段管理「今日」,取消后历史 journal **消失** — 用户翻 5-26 journal 看不到当时挑的今日 task。

#### ✨ 解决方案:事件流持久化

加 `today_history` append-only list 字段:
- 每次 set today=true → append 今天到 list
- 每次 set today=false → remove 今天 from list
- dataview 用 `contains(today_history, this.file.day)` 判断渲染 → **5/26 journal 永远显示曾经在 5/26 聚焦的 task**

#### 🔧 实施细节

**sync.py 改动**:
- `_create_task_md_from_feishu_record`:模板加 `today_history: [{today_date}]`
- `pull_today_from_feishu` plan_set_true:append today 到 history
- `pull_today_from_feishu` plan_set_false:remove today 从 history(对称)

**Obsidian assets 改动**:
- task-template 加 `today_history: []`
- journal 模板 dataview 改 `contains(today_history, this.file.day)`

#### 📐 设计要点

- **append-only**(事件流):不允许任意编辑,只允许 append / remove 一项
- **dataview 友好**:list 比 datetime 适合 `contains` 查询
- **对称操作**:set true 加 / set false 减,保持 history 真实反映「曾经聚焦」

#### 🐛 已知边界(v0.3.1 修)

- 跨日 task(在昨天 journal 跑 Cmd+P 快记任务)→ 用 today 日期(不是 journal 日期)→ today_history 进了今天而不是昨天 → 昨天 journal 看不到
- **v0.3.1 块 ④ 修**:userscript 拿 active file 的 journal 日期作为 dateContext

---

## 📊 当日总成果

| 维度 | 数量 |
|---|---|
| 版本上线 | 7 个(v0.2.0 / v0.2.1 / v0.2.2 / v0.2.3 / v0.2.4 / v0.2.5 / v0.3.0) |
| 架构级升级 | 2 次(v0.2.0 task md 化 + v0.3.0 today_history 事件流) |
| sync.py 累积改动 | ~1500 行(v0.2.0 ~1100,后续 patch ~400) |
| 跨工程性质 | OB CC 跨边界产品化重构(一次性例外)+ 用户实测落地 |

---

## 🔮 5/26 关键教训

1. **架构升级前先想数据迁移**(v0.2.0 → v0.3.0):today 单字段 → today_history 事件流,老 task md 没字段会被 dataview 漏掉 → 历史 task md 默认归非渲染。可接受,但说明 schema migration 是真实成本。
2. **DataView 是 read-only view,不是 source of truth**(v0.3.0):依赖 dataview 做「时间穿越」会失败,需要 frontmatter 层用事件流持久化。
3. **跨工程一次性例外要写清楚边界**(v0.2.0):事后修改 `cross-project.md` 加例外条款 + 标「v0.3+ 起改回独立 CC」。**例外不是约定,只是事件**。
4. **install.sh 是用户体验关键**(v0.2.0):一键部署比文档好 10 倍。但要考虑 dry-run / --force / --scripts-dir 等 flag,降低用户犯错成本。
5. **dataview 跨日要靠 frontmatter 数组而非时间戳判断**(v0.3.0 + 5/27 v0.3.4):`contains(today_history, this.file.day)` 比 `done_date = this.file.day` 鲁棒得多。

---

## 🔗 相关

- [`../../../CHANGELOG.md`](../../../CHANGELOG.md) v0.2.0 - v0.3.0 entry
- [`2026-05-27-feishukanban-开发日志.md`](2026-05-27-feishukanban-开发日志.md) 次日(v0.3.1 - v0.3.5)
- 项目身份与铁律:[`../../../.claude/CLAUDE.md`](../../../.claude/CLAUDE.md)
