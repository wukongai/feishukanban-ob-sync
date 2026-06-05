---
created: 2026-06-04
updated: 2026-06-04
status: reviewed
type: design
topic: 布丁 backlog ↔ OB task md 自动镜像
tags: [design, backlog, task, hook, 自动同步]
related:
  - "[[/Users/aim5/Documents/OB/_OB工程/superpowers/specs/2026-05-17-OB-跨项目需求池系统-设计.md]]"
  - "[[/Users/aim5/Documents/CodingProject/zhixing-game/docs/backlog/README.md]]"
  - "[[../ARCHITECTURE.md]]"
---

# 布丁 backlog ↔ OB task md 自动镜像 — 设计 spec(草案)

> **状态**:草案,等用户 review 后进入实施
> **范围**:zhixing-game 项目的 `docs/backlog/*.md` 与 OB vault `04 Inbox/task/*.md` 双方一对一镜像
> **触发场景**:① OB Cmd+P QuickAdd 新建好奇猫需求 ② zhixing-game CC 在 VS Code 对话中 Write backlog md
> **不在范围**:不推飞书(走现有 sync.py --create-task 流程,用户决定时机)

## 一、背景与动机

### 1.1 触发场景
2026-06-04 用户在 feishukanban-ob-sync CC 会话发起任务「把布丁 backlog 中的任务排查对应,补全 OB task 看板」。排查发现:

- backlog 共 **170+ 条**,OB task md 共 **130+ 条**,没有任何字段关联两边
- 至少 2 条 backlog status 严重滞后(已 done 但 backlog 没改),导致按 status 筛选误差大
- 历史上有过同步,但靠用户脑子记得 → 经常遗漏

用户原话:「如果做一个机制在创建布丁需求的时候,能自动触发也同步 task 看板,这样就不会遗漏了。」

### 1.2 跟既有 spec 的关系(不冲突,互补)

OB vault 有一份 2026-05-17 的「OB 跨项目需求池系统」spec(`/Users/aim5/Documents/OB/_OB工程/superpowers/specs/2026-05-17-OB-跨项目需求池系统-设计.md`,目前 draft 状态部分落地):

| 维度 | 「跨项目需求池系统」spec(2026-05-17) | 本 spec(2026-06-04) |
|---|---|---|
| 范围 | OB 内部跨项目的「想法 → 子项目」孵化代谢 | 布丁 backlog 与 OB task md 两边的事务性镜像 |
| 触发点 | 周日巡检 + 手动 `/inbox-review` | 创建/修改 backlog 时立刻同步 |
| 输出 | ADHD 友好巡检报告(建议非强制) | 文件级 1:1 镜像(无人为干预) |
| 焦点 | 「想法的代谢」(孵化/冷藏/归档) | 「事务的一致性」(backlog ≡ task md) |

**结论**:两者**互补不冲突**。本 spec 复用既有 spec 落地的 `parent_project` / `parent_subproject` frontmatter 字段(OB task md 已有),只新增 `backlog_source` 字段做精确关联。

### 1.3 现状勘察(2026-06-04)

| 元素 | 当前位置 | 性质 |
|---|---|---|
| backlog md | `~/Documents/CodingProject/zhixing-game/docs/backlog/<priority>-<标题>.md` | 仓库内文件 |
| backlog 在 vault 里的可见性 | `/Users/aim5/Documents/OB/01 Project/00 进行中/应用产品/布丁/zhixing-game-docs/` | symlink → zhixing-game/docs/(待最终确认) |
| OB task md | `/Users/aim5/Documents/OB/04 Inbox/task/YYYY-MM-DD-【...】<标题>.md` | vault 内文件 |
| OB QuickAdd「新建好奇猫需求」 | 配置位置待确认,模板在 `03 Resources/素材库/模版/好奇猫开发需求模版.md` | userscript |
| zhixing-game .claude/hooks/ | 已有 11 个 hook 文件(prevent-bash-compound 等),hook 基建齐全 | 可挂新 hook |
| 中间件脚本应放处 | `feishukanban-ob-sync/scripts/`(已有 auto_collect_today.py) | 本仓库 |

## 二、目标与非目标

### 2.1 目标
1. **零遗漏**:任何 backlog 创建/重命名都自动在 task 看板有对应 task md
2. **零摩擦**:用户不需要记得手动同步,系统兜底
3. **幂等**:同一 backlog 反复 Write(CC 多次 Edit)不会产生重复 task
4. **可回溯**:task md 有显式字段指向 backlog 文件
5. **不打扰飞书**:只建本地 task md,推飞书走现有 `--create-task` 用户主动触发
6. **可关闭**:全局 env 变量 / settings flag 一键关同步,失败不阻塞用户工作

### 2.2 非目标
1. ❌ **不自动推飞书**(避免飞书看板被调研期需求污染)
2. ❌ **不双向反写**(task md 改了不反向更新 backlog,避免循环)
3. ❌ **不自动改 status**(只保证文件存在性 + 字段镜像,语义状态用户管)
4. ❌ **不替代 sync.py 现有 4 个 Cmd+P 工作流**(只是新增一个上游触发链)
5. ❌ **不处理 idea/optim 长尾的"该不该建"判断**(用户回答:全部都要,看板靠视图过滤)
6. ❌ **不做跨项目泛化**(本 spec 只覆盖布丁,内容工厂等以后另立 spec)

## 三、架构设计

### 3.1 整体数据流

```
触发点 A: OB Cmd+P QuickAdd "新建好奇猫需求"
   userscript 写 backlog md(路径在 vault zhixing-game-docs/backlog/ 经 symlink 落到仓库)
              ↓ userscript 立即 exec
              ↓
触发点 B: zhixing-game CC Write Tool
   写 docs/backlog/<prefix>-*.md
              ↓ PostToolUse hook 监听
              ↓
   ┌─────────────────────────────────────────────────┐
   │ 统一中间件:                                     │
   │ feishukanban-ob-sync/scripts/backlog_to_task.py│
   │                                                  │
   │ 输入: --backlog <绝对路径>                     │
   │ 流程:                                          │
   │   1. 读 backlog frontmatter(priority/title/   │
   │      status/estimate/related_spec/tags)        │
   │   2. 计算 slug(去掉前缀和扩展名)              │
   │   3. grep vault task 目录有没有                │
   │      backlog_source: "[[<slug>]]"              │
   │   4. 有 → 更新映射字段(priority/标题/related)│
   │           但不动 status/today/feishu_record   │
   │   5. 无 → 新建 task md(YYYY-MM-DD-【布丁开    │
   │           发】<title>.md),frontmatter 套预     │
   │           设模板 + backlog_source 关联         │
   │   6. 输出日志到 ~/.claude/logs/                │
   └─────────────────────────────────────────────────┘
              ↓
   OB vault `04 Inbox/task/` 落新 task md
              ↓(用户后续手动决定推飞书)
   sync.py --create-task --task-md <path>
              ↓
   飞书项目管理多维表
```

### 3.2 核心字段 schema(task md frontmatter 新增)

```yaml
# 现有字段(已存在,不动)
priority: P1
status: backlog          # 新建时默认 backlog,等用户决定
today: false
created: 2026-06-04T...
parent_project: "[[布丁]]"
parent_subproject:       # 来自 OB 跨项目需求池系统(留空,用户填)
parent_task:
adhd_priority:           # 留空,用户填
estimate_hours:          # 从 backlog estimate 字段映射
feishu_record:           # 空(未推飞书)
feishu_url:              # 空
tags: [task, auto-from-backlog]   # 新增 auto-from-backlog 标记

# 本 spec 新增字段
backlog_source: "[[P1-习惯养成打卡]]"   # wikilink,关联 backlog 文件
backlog_path: "docs/backlog/P1-习惯养成打卡.md"   # 仓库相对路径(冗余,grep 友好)
backlog_priority: P1            # 镜像 backlog 的 priority 前缀
backlog_status_seen: todo        # 上次同步时看到的 backlog status(漂移检测用)
backlog_synced_at: 2026-06-04T... # 上次同步时间戳
```

**冗余字段的理由**:
- `backlog_source` 给 OB 用(wikilink 可点击跳转)
- `backlog_path` 给 grep 用(脚本扫看板找镜像关系不依赖 wikilink 解析)
- `backlog_status_seen` 给"漂移检测"用(下次扫看板,如果 task md 看到的 status 跟 backlog 当前 status 不一致 → 触发提醒)

### 3.3 触发机制详解

#### 3.3.1 zhixing-game 端(CC Write)

PostToolUse hook 监听:
- 工具:`Write` / `Edit` / `MultiEdit`
- 路径匹配:`/Users/aim5/Documents/CodingProject/zhixing-game/docs/backlog/*.md`
- 排除:`README.md` / `_index.base`

hook 脚本:`zhixing-game/.claude/hooks/post-backlog-sync.py`(新增)
- 接收 PostToolUse JSON 输入
- 提取写入的文件路径
- 匹配则 exec feishukanban-ob-sync/scripts/backlog_to_task.py --backlog <path>
- 失败 exit 0 不阻塞 CC

#### 3.3.2 OB 端(QuickAdd)

需要找/改/新建 userscript:`好奇猫需求新建.js`
- 现有 QuickAdd 的模板在 `03 Resources/素材库/模版/好奇猫开发需求模版.md`
- userscript 收集字段(priority / 标题 / 描述)
- 写入 vault `应用产品/布丁/zhixing-game-docs/backlog/<priority>-<标题>.md`(经 symlink 落到仓库)
- 写完后 `child_process.exec` 调 `python3 ~/Documents/CodingProject/feishukanban-ob-sync/scripts/backlog_to_task.py --backlog <绝对路径>`
- Notice 报告同步成功/失败

#### 3.3.3 幂等性

中间件脚本统一处理:
```python
def find_existing_task(slug):
    # 在 vault 04 Inbox/task/*.md 里 grep
    # ^backlog_source: "\[\[<slug>\]\]"
    # 或 ^backlog_path: ".*<slug>\.md"
    # 返回第一个命中的 task md 路径,无则 None
```

存在 → **更新模式**:只覆盖 `backlog_priority` / `backlog_status_seen` / `backlog_synced_at`,**不动**用户已经填的 `status` / `today` / `adhd_priority` / `feishu_record`。

不存在 → **新建模式**:用 OB task 模板新建,frontmatter 填全。

### 3.4 8 条架构原则自检

| # | 原则 | 落地表现 |
|---|------|---------|
| 1 | 解耦 ✅ | 中间件不耦合飞书(只建本地 task md);hook 不耦合中间件实现(只 exec 一个命令);失败不阻塞触发方 |
| 2 | 可扩展 ✅ | 新增触发点(内容工厂 backlog?)= 加一个 hook 调同一个脚本;新增字段映射 = 改中间件 frontmatter 映射表 |
| 3 | 灵活修改 ✅ | hook 一行不写代码就能关(把 hook 文件改名);中间件加 --dry-run 模式不动文件 |
| 4 | 渐进披露 ✅ | 用户看 task 看板感受零变化,只是不再遗漏;高级用户看 frontmatter 多 5 个字段(都明确语义) |
| 5 | 鲁棒性 ✅ | hook 异常 exit 0;中间件出错不写半成品 task md(用临时文件 + 原子 mv);同步日志独立文件可审计 |
| 6 | 人可读 ✅ | 字段名直白(backlog_source / backlog_synced_at);hook 注释完整;新建 task md 跟现有模板一致 |
| 7 | 高复用 ⚠️ | 现在写死布丁;**未来修复路径**:把 backlog 目录 / vault task 目录 / 项目名都做成 config(scripts/backlog_to_task.yaml) |
| 8 | 工程化 ✅ | 设计文档(本文)+ 实施 plan + handoff 三件套;CHANGELOG / VERSION bump;有 dry-run / debug 日志 |

**显式违反第 7 条**,未来用 yaml config 修复。

## 四、关键决策(已默认,等用户 review 反馈)

| # | 决策点 | 默认选择 | 理由 |
|---|--------|---------|------|
| 1 | 触发方式 | hook 硬拦截(zhixing-game/.claude/hooks/) | 用户已明确选 |
| 2 | 范围 | 全部 backlog(P0/P1/P2/P3/optim/idea/unrated/fix 都触发) | 用户选「全部都要,用视图过滤」 |
| 3 | 是否推飞书 | 不推 | 用户选「不推飞书」 |
| 4 | task 看板 status 默认值 | **`todo`**(2026-06-04 用户拍板) | 用户希望默认进入待办视图,而非"池子" |
| 5 | 历史 170+ 条回填 | **首次部署后跑一次 backfill 脚本**(scripts/backlog_backfill.py) | 否则只新增有效,历史漂移不修 |
| 6 | backlog 删除/重命名 | task md 保留 + 加 `backlog_orphaned: true` 标记,日志告警 | 不级联删,用户决定;trash 友好 |
| 7 | 关联字段命名 | `backlog_source`(wikilink) + `backlog_path`(相对路径) | 冗余给 OB / grep 两个目的 |
| 8 | 中间件位置 | feishukanban-ob-sync/scripts/backlog_to_task.py | 跟 sync.py / auto_collect_today.py 同目录,职责相符 |
| 9 | OB 端如何调中间件 | userscript 通过 child_process.exec | 跟现有 4 个 Cmd+P userscript 一致 |
| 10 | OB QuickAdd 改造范围 | 只改/新建好奇猫需求 userscript,不动模板 | 模板已存在 |
| 11 | 同步日志位置 | `~/.claude/logs/backlog-to-task-YYYY-MM.log` | 跨 vault / 跨仓库可读 |
| 12 | 关闭开关 | env 变量 `BACKLOG_TO_TASK_DISABLE=1` | 紧急关用 |

## 五、实施 Phase 划分(2026-06-04 用户拍板顺序)

> **顺序原则**:① 先中间件(双触发点共用) → ② 先 OB 端 QuickAdd(触发点 A,日常使用频次更高) → ③ 后 zhixing-game CC hook(触发点 B,CC 写 backlog 较少) → ④ 历史回填 → ⑤ 漂移检测 → ⑥ 文档 → ⑦ dogfood

| Phase | 内容 | 预估 | 可中断点 |
|-------|------|------|---------|
| **0** | 等 zhixing-game backlog status 全量对齐回执(handoff 已发) | 30~60 min(对方做) | - |
| **1** | 中间件 `scripts/backlog_to_task.py` MVP(create/update/scan 三模式,dry-run 默认) | 2-3 h | dry-run 跑通即可交付 |
| **2** | OB QuickAdd「🎮 新建布丁需求」**从 Template 升级为 Macro**(组合 Template step + UserScript step exec 中间件)+ vault userscripts 目录加 `quickadd-新建布丁需求-后处理.js` | 1.5-2 h | UI 配置 + js 文件,用户实测 Cmd+P 走全链路 |
| **3** | zhixing-game `.claude/hooks/post-backlog-sync.py` + settings.json 挂 PostToolUse hook | 1 h | 单独可交付 |
| **4** | 历史 170+ 条 `scripts/backlog_backfill.py`(--report-only → --dry-run → --apply 三档) | 1.5 h(脚本) + 跑批 review | 不影响 1-3 |
| **5** | 漂移检测 `scripts/backlog_drift_check.py`:扫看板 `backlog_status_seen` ≠ 当前 backlog status 的列差,产出 weekly report | 1.5 h | 可暂缓 |
| **6** | 文档对齐(README / CHANGELOG / ARCHITECTURE / tutorial/) | 1 h | 必走 |
| **7** | 真实 vault dogfood 1 周 + 反馈调整 | 1 周观察 | - |

**总预估**:7-9 小时实施 + 1 周观察。**建议节奏**:Phase 0 并行,Phase 1-3 一天内完成(MVP 可用),Phase 4-7 后续补齐。

### ⚠️ Phase 2 新发现(Template 类型限制)

勘察发现:OB QuickAdd「🎮 新建布丁需求」当前是 **Template 类型**(`.obsidian/plugins/quickadd/data.json` 实证):
- templatePath: `03 Resources/素材库/模版/好奇猫开发需求模版.md`
- fileNameFormat: `idea-{{NAME}}`
- folder: `应用产品/布丁/zhixing-game-docs/backlog/`(经 symlink)

**Template 类型的限制**:不能直接 exec 外部命令,所以「写文件 + 触发同步」原子化做不到。

**Phase 2 升级路径**:
1. 在 QuickAdd UI 里把「🎮 新建布丁需求」改成 **Macro 类型**
2. Macro 第 1 步:复用原 Template(参数迁移)
3. Macro 第 2 步:UserScript 调中间件
4. UserScript 文件:`feishukanban-ob-sync/obsidian-assets/userscripts/quickadd-新建布丁需求-后处理.js`(也复用现有 install.sh 安装链)

**降级 fallback**:如果用户暂时不想升级 QuickAdd,Phase 5 漂移检测会在每日扫描时兜底补建,只是有最多 24 小时延迟。

## 六、风险与缓解

### 风险 1:hook 失败阻塞 CC 写文件
- 概率:低
- 缓解:hook 内部所有异常 `exit 0`,跟现有 prevent-bash-compound / lang-guard 同模式
- 兜底:用户随时可用 env `BACKLOG_TO_TASK_DISABLE=1` 关同步

### 风险 2:中间件写错 task md 污染看板
- 概率:中
- 缓解:写之前先 grep 看有没有同名,有就走更新模式;dry-run 默认开;新建用临时文件 + 原子 mv
- 兜底:第一周强制 dry-run,跑日志观察实际行为

### 风险 3:OB symlink 跨 vault 不工作 / vault QuickAdd 路径错乱
- 概率:中
- 缓解:Phase 3 前先确认 `应用产品/布丁/zhixing-game-docs/` 是 symlink 且双向可写;userscript 拿 `path.resolve()` 求绝对路径,不依赖 vault 内引用
- 兜底:OB 端 userscript 直接写绝对路径(`~/Documents/CodingProject/zhixing-game/docs/backlog/`),不经 symlink

### 风险 4:170+ 历史 backlog 回填碰撞现有 task md
- 概率:高(已知至少 3 条主题重叠 — 学员侧 Skill / 视频付费试看 / 微信双刷新)
- 缓解:backfill 脚本做"主题模糊匹配"(标题关键词 + tags 交集),候选用 dry-run 列出来给用户人工选(yes/no/skip)而非全自动
- 兜底:回填用 `--report-only` 模式先出对比表,用户拍板再执行

### 风险 5:CC 频繁 Edit 同一 backlog 触发 hook 高频
- 概率:高(写 backlog 描述时多次微调)
- 缓解:中间件做去重 — 30 秒内同一 backlog 文件只同步一次(读 sidecar 缓存 last_synced_at)
- 兜底:同步是幂等的,即使触发 100 次结果也一致,只是浪费 CPU

### 风险 6:跟「OB 跨项目需求池系统」spec 字段冲突
- 概率:低(本 spec 只加 `backlog_*` 前缀字段,既有 spec 用 `parent_*` 前缀)
- 缓解:回填脚本不动 `parent_subproject`(用户手动填),只填 `parent_project: "[[布丁]]"`
- 兜底:文档明示两者各管什么,不交叉

## 七、✅ 决策已收敛(2026-06-04 用户 review 反馈)

| # | 问题 | 用户答 | 落地动作 |
|---|------|------|---------|
| 1 | symlink 是否就绪 | ✅ 已就绪 | `应用产品/布丁/zhixing-game-docs` → `~/Documents/CodingProject/zhixing-game/docs`(2026-05-14 建,实证 lrwxr-xr-x) |
| 2 | OB QuickAdd 现状 | ✅ 已改名「新建布丁需求」+ 自动落 symlink backlog/ | 但发现是 Template 类型 — Phase 2 升级 Macro |
| 3 | task md 默认 status | `todo` | 中间件 frontmatter 模板默认 `status: todo` |
| 4 | 关联字段命名 | OK(backlog_source / backlog_path) | 按设计第 3.2 节 schema |
| 5 | 是否做漂移检测 | ✅ 要做 | Phase 5 实施 |
| 6 | Phase 顺序 | ✅ 先 OB 然后 zhixing-game | Phase 2/3 调换(已更新 Phase 表) |
| 7 | 历史 170+ 条处理 | ✅ 要做 | Phase 4 backfill 脚本 |

## 八、关联文档

- 本 spec:`/Users/aim5/Documents/CodingProject/feishukanban-ob-sync/docs/design/backlog-to-task-mirror.md`
- 现有 handoff(前置):`/Users/aim5/Documents/CodingProject/zhixing-game/docs/superpowers/handoff/2026-06-04-backlog-status-对齐-handoff.md`
- 既有 OB spec(互补):`/Users/aim5/Documents/OB/_OB工程/superpowers/specs/2026-05-17-OB-跨项目需求池系统-设计.md`
- backlog 规范:`/Users/aim5/Documents/CodingProject/zhixing-game/docs/backlog/README.md`
- 本仓库架构:`/Users/aim5/Documents/CodingProject/feishukanban-ob-sync/docs/ARCHITECTURE.md`
- 主工具 sync.py:`/Users/aim5/Documents/CodingProject/feishukanban-ob-sync/sync.py`

## 九、状态变更记录

| 日期 | 状态 | 变更 |
|------|------|------|
| 2026-06-04 | draft | 初稿,等用户 review |
| 2026-06-04 | reviewed | 用户 review 7 条问题全收敛(详见第七节);发现 QuickAdd 是 Template 类型,Phase 2 改为 Macro 升级;Phase 顺序调成 1→2→3 |
| 待定 | plan-ready | 拆细 plan 文档完成 |
| 待定 | implementing | Phase 1 开工 |
| 待定 | done | Phase 7 1 周观察通过 |
