# 系统架构

> **feishukanban-ob-sync v0.2** 的设计文档。回答"为什么这样设计"+"哪些组件做什么"。

---

## 🎯 核心命题

> **让 Obsidian 笔记和飞书项目看板成为同一个"项目管理大脑"的两个视图,而不是两个孤立系统。**

- **Obsidian** = 知识管理 + 日记 + 思考的中心
- **飞书项目表** = 跨平台移动可访问 + 协作 + 看板视图

两者各有不可替代的优势,**v0.2 用 task md frontmatter ↔ 飞书 record 字段做严格 1:1 映射**,任一端改动自动同步另一端。

---

## 🏗 三层架构

```
┌──────────────────────────────────────────────────────────┐
│  飞书项目管理表(20+ 字段)                                │
│  ├─ 周看板视图(主用,周迭代规划)                       │
│  ├─ 月看板 / 价值优先级看板 / ADHD 看板                 │
│  └─ 「是否今日」checkbox 字段(2026-05-26 加)            │
└───────────────────┬──────────────────────────────────────┘
                    ↑↓ sync.py 双向同步
┌───────────────────┴──────────────────────────────────────┐
│  Python 桥接层(sync.py + auto_collect_today.py)          │
│  ├─ parse_task_md(抽 frontmatter + H2 段)              │
│  ├─ build_fields_payload(1:1 字段映射)                 │
│  ├─ feishu_upsert_record(CREATE / UPDATE)               │
│  ├─ pull_today_from_feishu(飞书 today → OB frontmatter) │
│  └─ auto_collect_today(场景 ③ 数据采集)                │
└───────────────────┬──────────────────────────────────────┘
                    ↑↓ 文件读写
┌───────────────────┴──────────────────────────────────────┐
│  Obsidian Vault(本地)                                   │
│  ├─ 04 Inbox/task/YYYY-MM-DD-<标题>.md(每个 task 一个) │
│  ├─ _task.base(6 视图全景)                            │
│  ├─ journals/YYYY-MM-DD.md(dataview TASK 查询渲染)    │
│  ├─ QuickAdd UserScripts(4 个 Cmd+P 入口)             │
│  └─ Templater + Tasks 插件(协同)                       │
└──────────────────────────────────────────────────────────┘
```

---

## 📋 三大工作流场景

### 场景 ① OB 创建 task → 自动同步飞书

```
用户 → Obsidian Cmd+P 「📝 快记任务」
   ↓
QuickAdd Macro:弹优先级 → 输标题
   ↓
UserScript:
   ├─ 创建 04 Inbox/task/YYYY-MM-DD-<标题>.md
   ├─ frontmatter(priority, status:todo, created, ...)
   ├─ 正文 5 个 H2 段骨架 + 完成标记 inline
   └─ 调 sync.py --task-md --apply
       ↓
       sync.py:
         ├─ parse_task_md(读 frontmatter + H2 段)
         ├─ build_fields_payload(转飞书 JSON)
         ├─ feishu_upsert_record(CREATE,新 record)
         └─ update_md_frontmatter(回写 feishu_record + feishu_url)
       ↓
       ✅ task md frontmatter 已含飞书 record 信息
```

**铁律 #1 飞书例外**:单条 CREATE 自动 apply,跳过 dry-run 审批(为 capture 体验)。

### 场景 ② 飞书今日 todo → OB 日志渲染

```
用户 → 飞书 app 周看板 → 长按 task → 勾「是否今日」=true(挑 3-5 条)
   ↓
用户 → Obsidian Cmd+P 「📥 拉今日 todo」
   ↓
UserScript 调 sync.py --pull-today --apply
   ↓
sync.py pull_today_from_feishu():
   ├─ 拉飞书全表 record(自动分页)
   ├─ filter 「是否今日」=true 的 record
   ├─ scan OB 04 Inbox/task/ 建索引(by feishu_record)
   ├─ 双向对齐:
   │   ├─ 飞书=true, OB today=false → 改 OB today=true
   │   ├─ 飞书=false, OB today=true → 改 OB today=false
   │   ├─ 飞书=true, OB 无对应 task md → 报告(不自动建)
   │   └─ 跳过已对齐的
   └─ update_md_frontmatter(只改 today 字段,append-only 安全)
   ↓
journal 内 dataview TASK 查询:
   `WHERE today = true AND priority = P0-P2 AND !completed`
   ↓
✅ today journal 「🎯 今日计划」段自动显示 3-5 条 checkbox
```

**关键**:今日 todo **由飞书侧主导**(用户日常移动 app 习惯),OB 端只读跟从。

### 场景 ③ 自动统计今日工作 → 写日志 + batch CREATE 飞书

```
用户 → Claudian 对话 "统计今天工作"
   ↓
Claudian:
   ├─ 调 scripts/auto_collect_today.py(数据采集)
   │   ├─ git log --since=1day(配置的项目仓库)
   │   ├─ scan vault 今日 mtime 改动的 .md/.py/.js/.css/.yaml 等
   │   └─ 输出 JSON 结构化数据
   ├─ Claudian 读 JSON + 关联 today journal + 本周报
   ├─ LLM 归纳为主题级清单(5-10 个主题)
   ├─ dry-run 给用户审
   └─ apply(等批准词):
       ├─ 在 today journal 加「📊 今日自动统计」section
       └─ 为每个主题 feishu_upsert_record(CREATE,status=Done,P3)
```

**铁律 #1 默认 5 步 SOP**:batch CREATE 多条 record 必须 dry-run + 用户审批。

---

## 📐 数据模型 — task md frontmatter ↔ 飞书 1:1 映射

| Task md frontmatter | 飞书字段 | 类型 |
|---------------------|---------|------|
| `priority` (P0/P1/P2/P3) | 价值优先级 | select |
| `status` (todo/doing/subdone/done/block/cancel/idea) | 执行状态 | select |
| `today` (true/false) | 是否今日 | checkbox |
| `today_source` (planned/unplanned/空) | (OB 私域,不映射飞书) | — |
| `created` (ISO 8601) | (不映射,OB 私域) | — |
| `done_date` (YYYY-MM-DD) | 完成时间 | datetime |
| `due` (YYYY-MM-DD) | 截止日期 | datetime |
| `category` | 大类 | select |
| `subcategory` (list) | 小类 | select multi |
| `adhd_priority` | ADHD优先级 | select |
| `estimate_hours` (number) | 估时 | number |
| `efficiency` | 完成效率 | select |
| `acceptance` (正文段) | 验收条件 | text |
| `thinking` (正文段) | 执行思路 | text |
| `resources` (正文段) | 相关资料 | text |
| `retrospective` (正文段) | 复盘 | text |
| `execution_summary` (正文段) | 执行概述 | text |
| `feishu_record` | (sync 自动回写) | — |
| `feishu_url` | (sync 自动回写) | — |
| `iteration_week` | 执行迭代周 | select |
| `iteration_month` | 执行迭代月 | select |

完整字段定义见 `docs/feishu-schema.md`。

---

## 🔴 8 条架构原则反向打分

| # | 原则 | 评 | 落地表现 |
|---|------|---|---------|
| 1 | 解耦 | ✅ | task md / journal / sync.py / 飞书 四层独立;改一层不动其他 |
| 2 | 可扩展 | ✅ | 加飞书字段 → config.yaml 一行;加场景 ④ → 加 helper + Cmd+P 入口,不动核心 |
| 3 | 灵活修改 | ✅ | 老接口保留作降级;config 改字段名一行即可启用/禁用映射 |
| 4 | 渐进披露 | ✅ | 入门 2 步(优先级 + 标题)→ 高级(编辑 task md H2 段)→ 开发者(读 sync.py) |
| 5 | 鲁棒性 | ✅ | sync 失败 task md 仍保留;铁律 #1 例外仅 CREATE/UPDATE 单条;cli timeout fallback |
| 6 | 人可读 | ✅ | 文件路径直观;模板带注释;rules / tutorial 详细 |
| 7 | 高复用 | ⚠️ 接受违反 | base_token + table_id 硬编码到 config.yaml;**修复路径**:多 profile config 切换 |
| 8 | 工程化 | ✅ | 标准目录 + git 可追踪 + install.sh 一键部署 + CHANGELOG |

---

## 🗂 仓库目录结构

```
feishukanban-ob-sync/
├─ sync.py                       # 主代码,~2300 行
├─ scripts/
│  └─ auto_collect_today.py     # 场景 ③ 数据采集 helper
├─ obsidian-assets/             # OB vault 安装资产
│  ├─ userscripts/              # 4 个 QuickAdd UserScripts
│  │  ├─ quickadd-快记任务-v2-task-md.js
│  │  ├─ quickadd-拉今日todo.js
│  │  ├─ quickadd-完成task.js
│  │  └─ quickadd-同步飞书项目.js
│  ├─ templates/                # task 模版
│  │  └─ task-template.md
│  ├─ base/                     # task base 视图
│  │  └─ _task.base
│  └─ rules/                    # 主规则(给 Claudian 读)
│     └─ feishu-project-sync.md
├─ install.sh                   # 一键部署到 vault
├─ uninstall.sh                 # 卸载脚本(可选)
├─ docs/
│  ├─ ARCHITECTURE.md           # 本文档
│  ├─ feishu-schema.md          # 飞书表 22 字段定义 + 创建命令
│  ├─ skill-claude-code.md      # Claude Code 用户专用入门
│  └─ tutorial/
│     ├─ 01-basic-push-sync.md
│     ├─ 02-short-link-auto-lookup.md
│     ├─ 03-reverse-pull.md(v0.1 legacy)
│     ├─ 04-field-mapping-customization.md
│     └─ 05-task-md-workflow.md(v0.2 主流程)
├─ README.md                    # 主入口
├─ INSTALL.md                   # 安装指南
├─ CHANGELOG.md                 # 版本变更日志
├─ LICENSE                      # MIT
├─ config.example.yaml          # 配置模板
└─ .gitignore
```

---

## 🚀 部署模式 — "客户端 / 服务" 架构

**OB vault 端**(用户私域):
- 只保留 `config.yaml`(含 base_token + 用户私域字段)
- 通过 symlink 引用独立仓库的 scripts / userscripts / rules
- 用户数据:`04 Inbox/task/*.md`(私域)

**独立仓库端**(产品):
- 所有产品级代码 + 文档 + 资产
- 多 vault 复用同一份代码(未来支持多用户)

**install.sh 做的事**:
- symlink `feishukanban-ob-sync/scripts/` → `<vault>/scripts/feishukanban-ob-sync/`
- symlink userscripts 到 vault
- 复制模板(`templates/task-template.md` → `<vault>/03 Resources/.../task 模版.md`)
- 复制 rules(`rules/feishu-project-sync.md` → `<vault>/.claude/rules/feishu-project-sync.md`)
- 输出 QuickAdd choices JSON snippet 让用户手动加入 `.obsidian/plugins/quickadd/data.json`(避免误改用户已有 choices)

---

## 🔗 关联

- [INSTALL.md](../INSTALL.md) — 用户安装步骤
- [feishu-schema.md](./feishu-schema.md) — 飞书表字段一键创建
- [05-task-md-workflow.md](./tutorial/05-task-md-workflow.md) — v0.2 主流程教程
- [CHANGELOG.md](../CHANGELOG.md) — 版本变更
