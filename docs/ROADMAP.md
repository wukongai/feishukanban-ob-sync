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

## 🏃 当前版本:**v0.5.0**(工作树已完成代码,待 commit + tag + push)

### 内容

- ✨ **task md ↔ 飞书 5 字段补全** — OB ↔ 飞书 1:1 闭环
  - 飞书侧 5 新字段:完成质量(select) / 用时(number) / 父任务(link 自关联本表) / 交付(text) / 用户故事(text)
  - OB 侧表达:frontmatter 3 个(`quality / actual_hours / parent_task`)+ 正文 H2 段 2 个(`## 📦 交付 / ## 👥 用户故事`)
  - sync.py 三处映射:**forward**(OB→飞书)+ **reverse**(飞书→OB pull-today)+ **反向建**(_create_task_md_from_feishu_record)
  - 算法亮点:`parent_task` wikilink ↔ record_id 双向解析;首次反向同步正文 H2 段(新 helper `update_h2_section_in_task_md`)

### 进度

| 项目 | 状态 |
|---|---|
| sync.py 5 字段 forward + reverse + 反向建 | ✅ 工作树完成 |
| config.yaml / config.example.yaml 5 字段配置 | ✅ 工作树完成 |
| docs/feishu-schema.md 27 字段表 | ✅ 工作树完成 |
| CHANGELOG v0.5.0 entry | ✅ 工作树完成 |
| README + install.sh banner v0.5.0 | ✅ README 已改;install.sh 未涉及 |
| dry-run 端到端验证(forward + reverse + parent_task 兜底) | ✅ 通过 |
| 真机 apply 端到端验证 | ⏳ 留给用户在自己 vault 跑 |
| commit + tag + push | ⏳ 待用户确认后做 |

---

## 📦 历史 v0.3.8(已发):Cmd+P 快记任务加 Step 4.5「项目小类」三级分类

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

## 🎯 v0.5.0 候选(目标:跨 macOS / Linux / WSL2 兼容)

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
