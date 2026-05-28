---
title: 常见开发任务 SOP
type: engineering
status: active
created: 2026-05-28
updated: 2026-05-28
tags: [规范, SOP, 开发流程]
related: ["[[README]]", "[[iron-rules]]", "[[git-workflow]]", "[[../../.claude/CLAUDE.md]]"]
---

# 常见开发任务 SOP

> 来源:`.claude/CLAUDE.md`「常见开发任务」section。本文是规范化展开版,加 9 步通用流程顶层框架。

---

## 🎯 通用 9 步流程(任何任务都先想清楚这 9 步)

```
1. 理解需求 → 跟用户对齐(1 句话需求 + 触发事件 + 受影响范围)
2. 翻历史 → 看 CHANGELOG / handoff / git log 了解相关代码上下文
3. 设计前 8 原则反向打分(8-principles.md)
4. 实施代码改动
5. 真实 vault dry-run 测试(铁律 #6)
6. apply 真改 + 看效果(用户确认)
7. 文档同步(CHANGELOG / README / install.sh / ARCHITECTURE / releases / VERSION 索引)
8. 8 原则自评写 CHANGELOG entry 末尾
9. commit + tag(铁律 #1 等用户 review)+ push
```

---

## 任务 1:加新字段映射(OB ↔ 飞书)

### 何时用此 SOP

用户要求 OB 端某字段(如 `today_source`)新增到飞书,或反之飞书新加字段(如 `项目小类` v0.3.8)要 sync 回 OB。

### 步骤

1. ☐ **飞书后台加字段**(或用 cli `feishu-cli bitable field create`)
2. ☐ 查新字段的 `field_id` + `type`(用 `feishu-cli bitable field list`)
3. ☐ **config 加映射**:
   - `config.example.yaml` 加 `task_md_fields.<key>.field_name`
   - 用户的 `config.yaml`(私域)同步加同样的值
4. ☐ **sync.py `parse_task_md` 抽 frontmatter 字段**(line ~960)
5. ☐ **如需特殊处理**(如 wikilink 抽名字 / multi-select list 包裹)→ `build_fields_payload` 加 case(line ~1828)
6. ☐ **task 模板 frontmatter 加字段**:
   - `obsidian-assets/templates/task-template.md` 加注释 + 默认值
   - vault 的 `task 模版.md`(用户私域)同步(走 handoff 流程)
7. ☐ **UserScript 互动**(可选):若 Cmd+P「📝 快记任务」要弹窗 → `obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js` 加 step + `quickAddApi.suggester/inputPrompt`
8. ☐ **反向 sync 考虑**:若字段也要支持飞书 → OB → 加到 `_REVERSE_SYNC_FIELD_WHITELIST`(参考 v0.3.7)
9. ☐ **真实 vault 测一次 dry-run → apply**(铁律 #6)
10. ☐ **更新文档**:
    - `docs/feishu-schema.md`(字段定义)
    - `docs/ARCHITECTURE.md`(schema 映射表)
    - `CHANGELOG.md`(版本 entry)
11. ☐ commit + tag(patch / minor 看大小)+ push

### 案例:v0.3.8 加 `project_minor` 字段

- 飞书侧:task 表加「项目小类」multi-select 字段
- config.example.yaml:`task_md_fields.project_minor.field_name: 项目小类`
- sync.py:`parse_task_md` 抽 `fm.get("project_minor")`,`build_fields_payload` 加 list 处理,`cmd_quickadd_options` 拉最近 5 distinct
- userscript:Step 4.5 多选循环 helper
- task-template:加 `project_minor:` 注释
- (尚未完成 — 工作树进行中)

---

## 任务 2:加新 Cmd+P 命令

### 何时用此 SOP

用户希望加新的 Obsidian 命令面板入口(如 v0.2.0 加的 4 个命令)。

### 步骤

1. ☐ **新建 `obsidian-assets/userscripts/quickadd-XXX.js`**(沿用现有模式:exec sync.py / read frontmatter / Notice 报告)
2. ☐ **`install.sh` Step 6** 输出的 `.quickadd-choices.json` 加新 choice(让用户粘贴到 vault QuickAdd 配置)
3. ☐ **如需 sync.py 支持**:加新 CLI flag(`--xxx`)+ 处理函数
4. ☐ **真实 vault 测**:
   - 用户手动加 choice 到 QuickAdd `data.json`
   - `Cmd+Q` 重启 Obsidian
   - `Cmd+P` 触发新命令
5. ☐ **文档更新**:
   - `README.md` 顶部 v0.X.Y 上线 section
   - `INSTALL.md`(详细步骤)
   - `docs/tutorial/05-task-md-workflow.md`(主流程教程)
   - `CHANGELOG.md`
6. ☐ commit + tag + push

### 案例:v0.2.0 加的 4 个命令

- 📝 快记任务 → `quickadd-快记任务-v2-task-md.js`
- 📥 拉今日 todo → `quickadd-拉今日todo.js`
- ✅ 完成当前 task → `quickadd-完成task.js`
- 🎯 同步今日 task 到飞书 → Claudian 接管(无独立 userscript)

---

## 任务 3:修 bug

### 何时用此 SOP

用户报 bug(如 v0.3.4「__filename 推导失败」)或自己 dogfood 发现的。

### 步骤

1. ☐ **复现** → 让用户在真实 vault 跑一遍,截图 / 终端输出
2. ☐ **定位** → 看 sync.py / userscript 哪里出问题(用 grep / 看 stacktrace)
3. ☐ **分析 root cause** → 不只是「能 work 就行」,写到 CHANGELOG「根因」段
4. ☐ **修法设计**:
   - 优先「不改老接口」(向后兼容)
   - 若必须改:bump MINOR + breaking changes 显式标注
5. ☐ **实施代码改动**
6. ☐ **真实 vault 测验证**(铁律 #6 — 必须真实 vault,不能 mock)
7. ☐ **patch bump**(v0.X.Y+1)
8. ☐ **文档更新**:
   - `CHANGELOG.md` 「修复」section,含「根因」段
   - 若涉及 schema 行为 → `docs/ARCHITECTURE.md`
9. ☐ commit + tag + push

### 案例:v0.3.4 修 `__filename` bug

- 复现:Cmd+P 全部报错 "can't open file '/Applications/Obsidian.app/.../sync.py'"
- 定位:Node `__filename` 在 QuickAdd userscript 上下文指向 Electron asar bundle,不是 vault
- root cause:v0.3.2 设计「__filename 自适应」在 Obsidian 上下文里根本不成立
- 修法:install.sh `cp + sed` 注入 sync.py 绝对路径
- 详见 CHANGELOG v0.3.4 entry

---

## 任务 4:大改动 / MINOR bump(架构升级)

### 何时用此 SOP

如反向 status 同步 / 多 profile config / 跨平台兼容 / 等架构级改动。

### 步骤

1. ☐ **看 ROADMAP** 确认这是用户计划内的(`docs/ROADMAP.md`)
2. ☐ **8 原则反向打分**(`8-principles.md` §「设计前」)
3. ☐ **在 `docs/superpowers/specs/` 加 spec 文档**(可选 — 改动巨大 / 跨多版本时)
4. ☐ **拆分实施步骤**:用 TodoWrite 列分阶段任务
5. ☐ **逐步实施 + 每步 dry-run 验证**
6. ☐ **真实 vault 完整测试**(覆盖正常路径 + 边界 case + 回归老功能)
7. ☐ **文档同步全套**(CHANGELOG / README / install.sh / ARCHITECTURE / feishu-schema / tutorial / releases / VERSION 索引)
8. ☐ **8 原则自评**写 CHANGELOG entry 末尾
9. ☐ **若涉及跨工程**(影响 vault 端 dataview / template / rules)→ 写 handoff 文档
10. ☐ MINOR bump → commit + tag + push

### 案例:v0.2.0 task md 化大架构升级

- ROADMAP 确认:从 inline 子弹笔记 → task = first-class entity
- spec:不存,直接在 CHANGELOG 详细写架构图
- 实施:4 个 Cmd+P 命令 + sync.py `--task-md` flag + auto_collect_today.py + install.sh + obsidian-assets/
- 测试:真实 vault dogfood 1 天
- 文档:CHANGELOG 含完整架构图 + README 重写 + INSTALL 重写 + tutorial/05
- handoff:无(用户自己跑 install.sh 即可)

---

## 任务 5:dogfood 自己发现的 bug / 小优化

### 何时用此 SOP

你既是 dev 又是 user,日常使用发现的 papercut(如 v0.3.6 dataview truthy 误判)。

### 步骤(精简版)

1. ☐ 直接修
2. ☐ patch bump
3. ☐ CHANGELOG 加 entry
4. ☐ commit + tag + push

无需 review meeting / spec — 你既知需求又知实现。但**铁律 #5 文档同步 + 铁律 #6 真实 vault 测**仍然适用。

---

## 🔗 相关

- 8 原则自评:[`8-principles.md`](8-principles.md)
- 6 条铁律:[`iron-rules.md`](iron-rules.md)
- git 工作流:[`git-workflow.md`](git-workflow.md)
- Bash 命令约定:[`bash-conventions.md`](bash-conventions.md)
- 版本号规则:[`../VERSION.md`](../VERSION.md)
- 路线图:[`../ROADMAP.md`](../ROADMAP.md)
- 项目入口:[`../../.claude/CLAUDE.md`](../../.claude/CLAUDE.md)
