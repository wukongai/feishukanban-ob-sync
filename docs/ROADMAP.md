---
title: ROADMAP
type: engineering
status: active
created: 2026-05-28
updated: 2026-05-28
tags: [规范, 路线图]
related: ["[[VERSION]]", "[[../CHANGELOG]]"]
---

# Roadmap

> 当前 + 下 1-2 版本计划。历史已发版见 [`CHANGELOG.md`](../CHANGELOG.md) / [`docs/VERSION.md`](VERSION.md) §7 快速索引。

---

## 🏃 当前版本:**v0.3.8**(进行中 / 工作树)

### 内容(根据 README + install.sh + config.example.yaml 工作树状态推断)

- ✨ **Cmd+P 快记任务 Step 4.5「项目小类」** — 三级分类最精细层
  - 数据源:飞书 task 表 `project_minor` multi-select 字段最近 5 条 distinct
  - 多选循环交互(类似 v0.3.5 iteration_* 多选)
  - sync.py 三处同步:`parse_task_md` / `build_fields_payload` / `--quickadd-options`

### 进度

| 项目 | 状态 |
|---|---|
| README + install.sh banner v0.3.8 | ✅ 工作树已改 |
| config.example.yaml 加 `project_minor` 字段定义 | ✅ 工作树已改 |
| sync.py `cmd_quickadd_options` 拉项目小类 distinct | ⏳ 待实施 |
| userscript Step 4.5 多选 helper | ⏳ 待实施 |
| task-template 加 `project_minor` 字段定义 | ⏳ 待实施 |
| CHANGELOG v0.3.8 entry | ⏳ 待写 |
| commit + tag + push | ⏳ 待做 |

---

## 🔮 下版本:**v0.3.9 候选**

### 备选 1:`parent_project` link 字段反向 sync(P0)

v0.3.7 反向字段 diff sync 暂禁了 `parent_project`(v0.2.5 helper 读写死的"项目"字段名,实际是"产品项目" link 字段,反向需要解析 link record → 名字)。

**实施方案**:
- `_extract_fields_from_feishu_row` 加 link record 反查:用 `task_md_fields.parent_project.link_table_id` + `link_table_name_field` 配置
- 拉 link record_id → 调 `feishu-cli bitable record get` 拿 record name
- diff helper:OB 端 strip wikilink + 飞书侧 record name 比较
- 把 `parent_project` 加回 `_REVERSE_SYNC_FIELD_WHITELIST`

**预估**:1h 实施 + 0.5h 测试

### 备选 2:`iteration_week` / `iteration_month` 多选反向 sync(P1)

v0.3.7 反向白名单未含 iteration_*(多选 list + 飞书侧 select_options 复杂)。

**实施方案**:
- `_extract_fields_from_feishu_row` 加 iteration_* multi-select 抽取
- diff 比较 list deep equal
- write 回 OB 时格式化为 inline YAML list(`[26W22, 26W23]`)

**预估**:1h(主要是测试边界 case)

### 备选 3:`pull-today` 默认 dry-run + 加 `--yes` flag(P2)

用户安全增强:`pull-today` 不加 `--apply` 时只 dry-run(现状),但 `--apply` 直接执行没二次确认。考虑改成 `--apply` 也 dry-run + 等用户输入 `y` 确认。或者加 `--yes` 自动批准。

---

## 🎯 v0.4.0 候选(目标:跨 macOS / Linux / WSL2 兼容)

- ⏳ install.sh `sed -i ''` → 抽 helper 适配 BSD / GNU sed
- ⏳ 路径处理统一 `pathlib`(已部分用,审计全文件)
- ⏳ 跨平台 test matrix:macOS 主 / Linux 容器测试 / WSL2 手动测试
- ⏳ 用户文档加「Linux / WSL2 安装注意」section

---

## 🎁 v1.0.0 目标(MVP → 正式版)

| 维度 | 标准 |
|---|---|
| **功能完整度** | 4 个 Cmd+P 命令稳定 / 反向 sync 完整(字段 + parent_project + iteration_*) |
| **跨平台** | macOS + Linux + WSL2 三平台都跑过用户验证 |
| **文档完备** | INSTALL / ARCHITECTURE / feishu-schema / 4 个 tutorial 全部 up-to-date |
| **测试覆盖** | sync.py 至少含 pytest 单元测试(目前 0 测试) |
| **稳定性** | 连续 14 天无 P0/P1 bug |

预估时间:**2026 Q3**(本项目是 side project,节奏取决于真实使用反馈)

---

## 🌱 长期愿景(无版本号绑定)

- 🌍 i18n(英文 README / CHANGELOG / 评论,扩大开源受众)
- 🤝 飞书以外的看板支持(Notion / Lark / Linear?— 评估成本,可能拆独立项目)
- 🔌 obsidian-cli + claude-mem skill 化(把当前的 install.sh 改成 plugin / skill 形态)
- 📊 数据分析维度:`today_source` planned vs unplanned 比例可视化(ADHD 自觉察分析)
