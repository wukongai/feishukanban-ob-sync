# 飞书项目管理表字段定义(v0.4)

> 安装 feishukanban-ob-sync 前,你需要在自己的飞书工作区**创建一个多维表**,并按本文档加好 **27 个字段**。
>
> v0.5.0(2026-05-28)新增 5 字段:**完成质量 / 用时 / 父任务 / 交付正文段 / 用户故事正文段**。

---

## 🚀 快速创建(用 feishu-cli)

如已装 [feishu-cli](https://github.com/feishu-cli/feishu-cli) 且 OAuth 完成 base scope,直接复制以下命令逐条跑:

```bash
# 前置:替换 <YOUR_BASE_TOKEN> 和 <YOUR_TABLE_ID> 为你的实际值
BASE=<YOUR_BASE_TOKEN>
TABLE=<YOUR_TABLE_ID>

# 必填字段(7 个)
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"任务标题","type":"text"}'
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"执行状态","type":"select","property":{"options":[{"name":"Todo"},{"name":"Doing"},{"name":"Done"},{"name":"Block"},{"name":"Idea"}]}}'
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"价值优先级","type":"select","property":{"options":[{"name":"P0"},{"name":"P1"},{"name":"P2"},{"name":"P3"}]}}'
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"完成时间","type":"datetime"}'
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"创建时间","type":"datetime"}'
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"是否今日","type":"checkbox"}'
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"交付","type":"text"}'

# task md 化字段(8 个 — 2026-05-25 上线 task md 化架构必需)
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"大类","type":"select","property":{"options":[{"name":"产品项目"},{"name":"杂务"},{"name":"技能工具"},{"name":"领域学习"}]}}'
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"小类","type":"select","property":{"multiple":true,"options":[]}}'
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"ADHD优先级","type":"select","property":{"options":[{"name":"待抢救"},{"name":"有 DDL"},{"name":"自由待办"}]}}'
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"估时","type":"number","property":{"formatter":"0.0"}}'
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"完成效率","type":"select","property":{"options":[{"name":"高"},{"name":"中"},{"name":"低"}]}}'
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"执行概述","type":"text"}'
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"验收条件","type":"text"}'
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"执行思路","type":"text"}'
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"相关资料","type":"text"}'
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"复盘","type":"text"}'

# 周期字段(2 个)
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"执行迭代周","type":"select","property":{"options":[{"name":"26W22(5月25日-5月31日)"}]}}'
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"执行迭代月","type":"select","property":{"options":[{"name":"26 年 5 月"}]}}'

# v0.5.0(2026-05-28)新增 5 字段:OB ↔ 飞书 1:1 闭环
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"完成质量","type":"select","property":{"options":[{"name":"高"},{"name":"中"},{"name":"低"}]}}'
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"用时","type":"number","property":{"formatter":"0.0"}}'
# 相关任务 link 字段自关联到本表(选当前表为 link_table,飞书会自动反向显示"子任务")
# ⚠️ 飞书表实际字段名是「相关任务」(双向 link),不是「父任务」 — v0.5.0 Step 2 一手 API 验证
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"相关任务","type":"link","property":{"table_id":"<本表 table_id>"}}'
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"交付","type":"text"}'
feishu-cli bitable field create --base-token $BASE --table-id $TABLE --config '{"field_name":"用户故事","type":"text"}'
```

⚠️ **v0.5.0 字段说明**:
- 「完成质量」/「用时」:完成 task 时回填,反向 pull-today 也会拉回 OB(`quality` / `actual_hours` frontmatter)
- 「父任务」:link 自关联本表;forward 时 sync.py 会从 OB `parent_task: "[[<父 task 文件名>]]"` 查 vault → 反查父 task 的 `feishu_record` → 写 link;父 task 未 sync 时跳过该字段(不阻断其他字段)
- 「交付」(v0.4 区别于 v0.1 的同名字段):正文 H2 段同步,**双向**(forward 推 task md「## 📦 交付」段 → 飞书 text 字段;reverse 飞书 → OB 段;飞书侧空 → 保留 OB 防御误清)
- 「用户故事」:同上,产品类 task 的「作为 X,我希望 Y,以便 Z」句式

⚠️ **执行迭代周 / 月**的 enum 选项是 sync.py 根据完成日动态生成的,你只需要建字段 + 加几个起始 enum,后续 sync.py 会按需 best_match。

---

## 📋 完整字段清单(27 个,v0.5.0 起)

| # | 字段名 | 类型 | 必填? | 用途 | sync.py 字段映射 |
|---|--------|------|------|------|----------------|
| **核心 7 个** |
| 1 | 任务标题 | text | ✅ | task 标题 | `fields.title` |
| 2 | 执行状态 | select | ✅ | todo/doing/done/block/idea | `fields.status` |
| 3 | 价值优先级 | select | ✅ | P0-P3(task md 化必需) | `task_md_fields.priority_str` |
| 4 | 完成时间 | datetime | ✅ | 完成日 | `fields.done_date` |
| 5 | 创建时间 | datetime | ⚠️ 可选 | task 创建日 | `fields.created_date` |
| 6 | 是否今日 | checkbox | ✅ | 今日 todo 标记(v0.2 必需) | `reverse.default_filter.field_name` |
| 7 | 交付 | text | ⚠️ 可选 | 交付物 wikilink | `fields.delivery` |
| **task md 化 8 个**(2026-05-25 上线) |
| 8 | 大类 | select(单) | ⚠️ | 产品项目/杂务/技能工具/领域学习 | `task_md_fields.category` |
| 9 | 小类 | select(多) | ⚠️ | 灵活分类 | `task_md_fields.subcategory` |
| 10 | ADHD优先级 | select(单) | ⚠️ | 待抢救/有 DDL/自由待办 | `task_md_fields.adhd_priority` |
| 11 | 估时 | number | ⚠️ | 小时数 | `task_md_fields.estimate_hours` |
| 12 | 完成效率 | select | ⚠️ | 高/中/低 | `task_md_fields.efficiency` |
| 13 | 执行概述 | text | ⚠️ | 抽自 task md `## 📝 执行概述` | `task_md_fields.execution_summary` |
| 14 | 验收条件 | text | ⚠️ | 抽自 task md `## ✅ 验收条件` | `task_md_fields.acceptance` |
| 15 | 执行思路 | text | ⚠️ | 抽自 task md `## 💡 执行思路`(v0.5.0 Step 2 加双向同步)| `task_md_fields.thinking` |
| 16 | 相关资料 | text | ⚠️ | 抽自 task md `## 🔗 相关资料`(v0.5.0 Step 2 加双向同步)| `task_md_fields.resources` |
| 17 | 复盘 | text | ⚠️ | 抽自 task md `## 🪞 复盘` | `task_md_fields.retrospective_text` |
| **周期 2 个**(2026-05-18 上线) |
| 18 | 执行迭代周 | select | ⚠️ | `26W22(5月25日-5月31日)` 等 | `fields.iteration_week` |
| 19 | 执行迭代月 | select | ⚠️ | `26 年 5 月` 等 | `fields.iteration_month` |
| **v0.5.0 5 字段补全**(2026-05-28 — OB ↔ 飞书 1:1 闭环) |
| 20 | 完成质量 | select(单)| ⚠️ | 高/中/低,完成 task 时回填 | `task_md_fields.quality` |
| 21 | 用时 | number | ⚠️ | 实际花费小时数,完成 task 时回填 | `task_md_fields.actual_hours` |
| 22 | **相关任务**(不是「父任务」!) | link 双向(自关联本表)| ⚠️ | task 拆分关系,wikilink ↔ record_id 双向解析;飞书自动反向显示"子任务" | `task_md_fields.parent_task` → `field_name: 相关任务` |
| 23 | 交付 | text | ⚠️ | ⭐ 抽自 task md「## 📦 交付」H2 段,**双向同步** | `task_md_fields.delivery` |
| 24 | 用户故事 | text | ⚠️ | 抽自 task md「## 👥 用户故事」H2 段,双向同步 | `task_md_fields.user_story` |
| **可选未实现 3 个** |
| 25 | 截止日期 | datetime | ❌ | 飞书表暂无,等用户加 | `task_md_fields.due` |
| 26 | 任务来源 | select | ❌ | 主动/auto-stats(避免自动统计污染) | (P2 待实现) |
| 27 | 备注 | text | ❌ | 用户自由填 | (不映射) |

⚠️ "必填"=v0.2/v0.4 核心工作流依赖;**未填的字段 sync 时会 silently skip**,不报错。

⚠️ **v0.5.0 字段#23「交付」与 v0.1 旧字段同名但语义不同**:
- v0.1 顶层 `fields.delivery`:D 混合架构,扫 OB 多种 wikilink/callout 表达后合并写入(journal inline 模式专用,单向 OB→飞书)
- v0.4 `task_md_fields.delivery`:直接抽 task md「## 📦 交付」H2 段(task md 模式专用,双向)
- 两种配置可共存:journal inline 模式走 v0.1 路径,task md 模式走 v0.4 路径(优先级:H2 段值非空时覆盖 D 混合结果)

---

## 🔧 字段类型详解

### checkbox(是否今日)

```json
{"field_name": "是否今日", "type": "checkbox"}
```

- 飞书侧:显示为复选框 ☐ / ☑
- API 值:`true` / `false`
- sync 行为:`pull_today_from_feishu` 拉所有 `=true` 的 record

### select(单选 vs 多选)

```json
// 单选
{"field_name": "大类", "type": "select", "property": {"options": [{"name": "产品项目"}, ...]}}

// 多选(加 "multiple": true)
{"field_name": "小类", "type": "select", "property": {"multiple": true, "options": [...]}}
```

### datetime

```json
{"field_name": "完成时间", "type": "datetime"}
```

- API 值:13 位 ms timestamp(`1779724800000` = 2026-05-26)
- sync.py 自动转换 task md 的 `YYYY-MM-DD` → ms

### number

```json
{"field_name": "估时", "type": "number", "property": {"formatter": "0.0"}}
```

---

## 🎯 视图建议(在飞书后台手动建)

v0.2 推荐 4 个视图:

| 视图名 | 类型 | 过滤 | 用途 |
|--------|------|------|------|
| **周看板** | 看板 | (无,显示全部) | 周迭代规划主用 |
| **今日 todo** | 看板 | 是否今日 = true | 早上挑今日 todo |
| **本周已完成** | 表格 | 执行状态 = Done AND 执行迭代周 = 当前周 | 周复盘 |
| **ADHD 待抢救** | 表格 | ADHD优先级 = 待抢救 | 高紧急救火 |

---

## 🔗 关联

- [README.md](../README.md) — 主入口
- [INSTALL.md](../INSTALL.md) — 安装步骤(含 config.yaml 填写 base_token)
- [ARCHITECTURE.md](./ARCHITECTURE.md) — 系统架构
- [config.example.yaml](../config.example.yaml) — 配置模板
