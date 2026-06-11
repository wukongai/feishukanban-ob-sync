---
title: 2026-06-10 feishukanban-ob-sync 开发日志
type: daily-log
date: 2026-06-10
tags: [daily, v0.9.1, parent_project, active-projects, create-task, quickadd-options]
related: ["[[../../VERSION]]", "[[../../ARCHITECTURE]]", "[[../../../CHANGELOG]]"]
---

# 2026-06-10 feishukanban-ob-sync 开发日志

> 修复 `parent_project` 精确匹配失败时的误导提示,并把产品项目关联表读取改成分页全量 active 项目集合。

---

## 会话 1:v0.9.1 parent_project 全量 active 匹配

⏱️ 时长:约 1.5h
🏷️ commits:(待 commit)
🎯 主题:**`--create-task --parent-project` 候选集合与提示修复**

### 🐛 触发事件

OB handoff 指出:用户在飞书产品项目表中确认 `AI自媒体` 真实存在且 active,但 OB 侧误传:

```bash
--parent-project "AI自媒体项目"
```

旧提示只展示排序前 10 个候选:

```text
可用项目: AI 制作知识卡片, AI 心理深读营..., AIcoding...
```

这会让使用者误以为「飞书里没有 AI自媒体」。实际问题是输入名不精确:`AI自媒体项目` ≠ `AI自媒体`。

### 🔍 Root cause

1. `resolve_link_record_id()` 失败提示只展示 `sorted(index.keys())[:10]`,没有说明这是样例而非全集。
2. `build_link_table_index()` / `_extract_link_table_records()` 都写死单次 `record list --limit 200`,项目表未来超过 200 条时会真实漏匹配。
3. active 语义不统一:QuickAdd 菜单会看 active 字段,但 create-task 的 link 解析旧路径没有显式 active 过滤。

### 🛠 实施

| 文件 | 改动 |
|---|---|
| `sync.py` | 新增 `list_all_bitable_records()` 通用分页 helper,用 `--offset` 聚合全量 records |
| `sync.py` | `build_link_table_index()` 改为 `(link_table_id, name_field, active_field, only_active)` 维度缓存,默认只保留 active=true 项目 |
| `sync.py` | `_extract_link_table_records()` / `query_subprojects_by_parent()` 改走分页 helper,QuickAdd 菜单和子项目查询共享全量数据 |
| `sync.py` | `resolve_link_record_id()` 失败提示改为 active 项目总数 + 前 10 个样例 + 相近候选推荐 |
| `README.md` / `CHANGELOG.md` / `config.example.yaml` / `docs/ARCHITECTURE.md` | bump v0.9.1 并补用户可见行为说明 |

### ✅ 验证

```bash
python3 -m py_compile sync.py
```

通过,且修掉了旧 docstring 里 `\s` 带来的 SyntaxWarning。

真实 OB vault dry-run:

```bash
python3 sync.py --vault /Users/aim5/Documents/OB --create-task \
  --title "parent_project 候选提示测试 20260610" \
  --category 产品项目 --parent-project "AI自媒体项目" \
  --status todo --priority P3 --today-source unplanned --json
```

结果:

```text
共 18 个可用 active 项目（以下仅展示前 10 个样例）...
你可能想用: AI自媒体, 读书自媒体, 心理自媒体
```

精确名 dry-run:

```bash
--parent-project "AI自媒体"
```

payload 正确写出:

```json
"产品项目": ["recvlf0VT3BUDH"]
```

QuickAdd batch 验证:

```bash
python3 sync.py --vault /Users/aim5/Documents/OB --quickadd-options
```

返回 18 个 active 项目,包含 `AI自媒体`。

### 🎯 设计取舍

- **不做模糊自动写入**:相近候选只提示,落库仍需精确匹配,避免挂错项目。
- **active 语义统一**:`--create-task` / `--resolve-project` / `--quickadd-options` 都基于同一张全量关联表。
- **分页兜底 10000 条**:默认 `200 * 50`,触顶会 warning。当前产品项目表远小于上限。

### 📌 工作区注意

会话开始时工作区已有未提交改动:

- `obsidian-assets/userscripts/quickadd-批量推今日-task-md.js`
- `.codex/`
- `AGENTS.md`

本次修复没有改动既有 userscript 改动,只新增/修改 v0.9.1 相关代码和文档。

---

## 🔗 相关

- 飞书任务:[修复 feishukanban parent_project 全量 active 匹配与候选提示](https://vbn7n4vn7h.feishu.cn/base/Vy8ubUWKbad5u1s8BCJcd1TlnFf?table=tblIrLY0nU4sCdRC&view=vewQ4KQITb&record=recvm6DUwB7lMG)
- OB task md:`/Users/aim5/Documents/OB/04 Inbox/task/2026-06-10-【OB飞书项目看板】修复 feishukanban parent_project 全量 active 匹配与候选提示.md`
- [`../../../CHANGELOG.md`](../../../CHANGELOG.md)
- [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md)
- [`../../../README.md`](../../../README.md)
