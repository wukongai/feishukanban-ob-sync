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

## 📌 关键防御机制 + 历史保真

### sync.py 限流退避(v0.7.4)

`run_cli`(所有 feishu-cli 调用的统一入口)遇飞书 base/v3 `code=5000 + msg=空` 自动退避重试:`5s / 15s / 45s × 3 次`,总最长 65s;非限流错误立即抛(行为不变)。dry-run 不调 CLI 不受影响。识别函数 `_is_ratelimit_5000(stderr)` 严格按"`code=5000` 且 `msg=` 后为空 / `(空)` / `（空）`"判定,有 msg 内容的 5000(真实业务错误)不触发重试。

### parent_project 全量 active 匹配(v0.9.1)

`parent_project` 写入飞书「产品项目」link 字段时,候选集合来自关联项目表的分页全量读取,不再受单次 `record list --limit 200` 截断影响。若配置了 `link_table_active_field`,索引和 Cmd+P 项目菜单统一只使用 active=true 项目;精确匹配失败时仍跳过该字段,但会输出 active 项目总数、前 10 个样例和相近候选,避免把"输入名不精确"误判成"飞书里没有这个项目"。

### 今日历史保真(v0.3.0 → v0.7.3 → v0.7.5)

OB 日志「🎯 今日计划 / 🐿️ 今日非计划」按天渲染,要求即便后续日子改动也不污染历史快照。逐次加固:

- **`today_history` 事件流(v0.3.0)**:list,append-only,记录每天进入 today 的轨迹;比 `today: true/false` 单字段能"时间穿越"
- **`today_source_history` 按天来源(v0.7.3)**:list,与 `today_history` 一一对应,`today_source_history[i]` = `today_history[i]` 那天的来源(planned / unplanned)。`plan_set_true` 只 append、`plan_set_false` 不清空 → 历史日 Dataview 渲染按天查不再被后续 `plan_set` 覆盖
- **`getDaySource` 启发式 fallback(v0.7.5,vault 端 dataviewjs)**:救 v0.7.2 之前已损坏数据(`today_source` 已被 `plan_set_false` 清空 / 被 `--pull-today` 覆盖)的历史显示。3 级优先:
  1. `today_source_history[idx]` 存在非空 → 用(v0.7.3 主路径,新数据 100% 准)
  2. `created` 那天 == dateISO 且 dateISO 在 `today_history` → 视为 `unplanned`(Cmd+P 快记任务特征)
  3. fallback 旧 `today_source`(兜底)

> 边缘 case:用户手动把昨天创建的 task 拖到今日并意图为 unplanned(`created < dateISO`)—— 启发式判不出,需手改 task md 的 `today_source_history` 字段。

### skill strict 守卫 — 软段空壳 / select / 执行明细 / 交付路径(v0.7.7+)

`push_task_md` 在调飞书 upsert 前对五段(用户故事 / 验收条件 / 执行思路 / 执行概述 / 复盘)做空段扫描:

- **默认宽松**(`strict_soft=False`):五段全空 → ⚠️ warning + 继续推 / 部分空 → warning / 零空 → 静默。**OB Cmd+P 菜单路径(快记任务 / 批量推今日 / 完成 task 等所有 UserScript)走此路径** —— 兼容用户"快速建骨架后续手工补"的两段式工作流。
- **strict 模式**(`--strict-soft-sections`):五段全空 → ⛔ `_fail` 拒推 + 提示用户补。**Claude/skill 路径走此模式**(由 `~/.claude/skills/同步任务到飞书/SKILL.md` 在 A2 / B3 / C2 的 apply 命令里强制加 flag)—— 兜底 Claude 漏补软段就推。

v0.9.2 同一套 strict 思路继续补三道 skill 防线:

- **`--strict-select`**:select 白名单外值拒推,避免字段被宽松跳过后用户误以为已同步。
- **`--strict-detail-one-per-day`**:扫描「## 📈 执行明细」原始行,同一日期出现多条 `YYYY-MM-DD...` bullet 时拒推。原因:飞书执行明细子表以日期为合并 key,同日拆多行不会逐条进入子表;过程应合并进单条的「复盘=」。
- **`--strict-delivery-paths`**:扫描「## 📦 交付」段,发现 `docs/...` / `src/...` / `.claude/...` / `CHANGELOG.md` 等疑似相对路径时拒推。原因:vault 外文件必须用绝对路径 + 行内 code,否则飞书侧无仓库归属,OB 双链也会断链或误命中。

辨识标记:仅对 `task["_task_md_mode"]=True`(parse_task_md 路径)生效;老 inline journal 路径无 H2 段概念,不触发守卫。Helper `_check_empty_soft_sections(task)` 返回空段中文名 list,守卫逻辑通过 list 长度 + `strict_soft` 联合决策。

> **设计原则**:用 flag 区分调用方意图,而不是用调用者类型(sync.py 不知道调用者是 UserScript 还是 skill)。flag 缺省 = 调用方放弃严格校验(菜单的默认意图);flag 显式 = 调用方主张严格(skill 的默认意图)。

---

## 📋 四大工作流场景

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

### 场景 ④ 外部项目扫尾 → 一条命令写任务到飞书+OB(v0.7.0)

```
外部项目(zhixing-game 等)任务扫尾
   ↓
全局 skill「同步任务到飞书」 / 直接调 sync.py --create-task
   只传业务参数(title / category / status / priority / 估时用时 /
   done-date / description / delivery / log-link / detail /
   user-story / acceptance / thinking / retrospective)
   ↓
sync.py create_task_from_params():
   ├─ _build_task_md_content_from_params(参数 → 规范 task md:
   │    frontmatter 全字段 + today_history + 完整 H2 骨架,简约无注释)
   ├─ dry-run:写临时文件解析看 diff(不污染 vault)
   └─ apply:落 04 Inbox/task/ → push_task_md(CREATE + 回填 + 推执行明细子表)
   ↓
✅ 飞书新 record + OB task md + 执行明细子表;--json 回执含 record_id / url
```

**复用而非另起**:走 push_task_md(场景 ① 同一管线)+ `_create_task_md` 模板骨架,数据源换成外部传参。**状态解耦**:主 task status(整体,人定)≠ 执行明细行状态(当天)。默认 dry-run,`--apply` 才写。详见 `docs/handoff/zhixing-game对接/`。

---

## 📐 数据模型 — task md frontmatter ↔ 飞书 1:1 映射

| Task md frontmatter | 飞书字段 | 类型 |
|---------------------|---------|------|
| `priority` (P0/P1/P2/P3) | 价值优先级 | select |
| `status` (todo/doing/subdone/done/block/cancel/idea) | 执行状态 | select |
| `today` (true/false) | 是否今日 | checkbox |
| `today_source` (planned/unplanned/空) | (OB 私域,不映射飞书) | — |
| `today_source_history` (list,v0.7.3+) | (OB 私域,与 `today_history` 一一对应的按天来源快照,只追加) | — |
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
