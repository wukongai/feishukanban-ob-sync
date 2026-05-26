# 飞书项目管理表字段定义(v0.2)

> 安装 feishukanban-ob-sync 前,你需要在自己的飞书工作区**创建一个多维表**,并按本文档加好 **22 个字段**。

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
```

⚠️ **执行迭代周 / 月**的 enum 选项是 sync.py 根据完成日动态生成的,你只需要建字段 + 加几个起始 enum,后续 sync.py 会按需 best_match。

---

## 📋 完整字段清单(22 个)

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
| 15 | 执行思路 | text | ⚠️ | 抽自 task md `## 💡 执行思路` | `task_md_fields.thinking` |
| 16 | 相关资料 | text | ⚠️ | 抽自 task md `## 🔗 相关资料` | `task_md_fields.resources` |
| 17 | 复盘 | text | ⚠️ | 抽自 task md `## 🪞 复盘` | `task_md_fields.retrospective_text` |
| **周期 2 个**(2026-05-18 上线) |
| 18 | 执行迭代周 | select | ⚠️ | `26W22(5月25日-5月31日)` 等 | `fields.iteration_week` |
| 19 | 执行迭代月 | select | ⚠️ | `26 年 5 月` 等 | `fields.iteration_month` |
| **可选未实现 3 个** |
| 20 | 截止日期 | datetime | ❌ | 飞书表暂无,等用户加 | `task_md_fields.due` |
| 21 | 任务来源 | select | ❌ | 主动/auto-stats(避免自动统计污染) | (P2 待实现) |
| 22 | 备注 | text | ❌ | 用户自由填 | (不映射) |

⚠️ "必填"=v0.2 核心工作流依赖;**未填的字段 sync 时会 silently skip**,不报错。

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
