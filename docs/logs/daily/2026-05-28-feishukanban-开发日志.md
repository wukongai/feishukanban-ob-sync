---
title: 2026-05-28 feishukanban-ob-sync 开发日志
type: daily-log
date: 2026-05-28
tags: [daily, v0.3.6, v0.3.7, v0.3.8, today_source, 反向sync, project_minor, 工程规范]
related: ["[[../../VERSION]]", "[[../../ROADMAP]]", "[[../../../CHANGELOG]]", "[[../../handoff/OB对接]]"]
---

# 2026-05-28 feishukanban-ob-sync 开发日志

> 凌晨连续会话,3 个版本上线 + 工程规范文档体系建立。

---

## 会话 1:v0.3.6 today_source 字段(凌晨)

⏱️ 时长:约 1h
📊 Token:(未记录)
🏷️ commits:`2af5d3b` + `83d50d1`

### 🎯 完成

#### ✨ 新功能

**`today_source` frontmatter 字段** — ADHD 自觉察「计划 vs 非计划」

| 值 | 含义 | 写入触发 |
|---|---|---|
| `planned` | 早晨规划好的 | `pull-today` 设 today=true(plan_set_true / `_create_task_md_from_feishu_record`) |
| `unplanned` | 当天临时插入 | Cmd+P「📝 快记任务」+「是否今日」=是 |
| 空 | 不在今日 / 历史 task | pull-today 设 today=false 时清空(对称) |

**配套 sync.py bug 修复**:
- `update_md_frontmatter` 加**空字符串特例**(`value == ""` → 写 `key:` 而非 `key: ''`,避免 dataview 把 `''` 当 truthy 漏过滤)

### 📚 文档对齐

- CHANGELOG.md v0.3.6 entry(含 8 原则自评 ⭐⭐⭐⭐⭐ × 5)
- README.md badge + 顶部 v0.3.6 上线段
- ARCHITECTURE.md 数据模型加 `today_source` 行
- install.sh banner v0.3.5 → v0.3.6

### 🔗 跨工程 handoff

写 `docs/handoff/OB对接/2026-05-27-v0.3.6-today_source-handoff.md`,通知 OB CC 改 vault 端 4 件事:
1. journal 模板 dataview 用 `today_source` 替代 `priority` 区分计划/非计划段
2. 历史 journal 同步改(grep 命令已附)
3. 用户实测 4 场景
4. 历史 task md 不 backfill(null 默认归计划段)

### 决策记录

**Q**:为什么 hook 输出 `sessionTitle` 实测无效但仍保留代码?
**A**:试探 Claude Code 升级是否会启用,边界成本低。

**Q**:CHANGELOG/README 的 v0.3.6 段已被用户编辑加 Part 2 描述,与我「v0.3.5 范围之外」的认知矛盾,怎么办?
**A**:用 AskUserQuestion 明确询问 — 用户选「2 块 patch 合并」(v0.3.5 包含 Part 1 status + Part 2 Cmd+P 9 步)。教训:**用户的 intent 通过文档编辑表达,有时比口头答案更准确**。

---

## 会话 2:v0.3.7 pull-today 反向字段 diff sync(凌晨偏早晨)

⏱️ 时长:约 1.5h
📊 Token:(未记录)
🏷️ commits:`a531587`

### 🎯 用户痛点(触发事件)

用户截图反馈:
> "拉回状态的时候还是修改过的执行状态没有拉回,5月28日AI日报已经是 done,但依然显示的是 todo,改成 subdone 也不行,问题在于看板是实时修改状态,需要在修改后拉回新的状态"

### 🐛 Root cause

`pull_today_from_feishu` 设计上**只同步 `today` 字段**(sync.py docstring 明说),对现存 task md 走 `plan_set_true` / `plan_skip` / `plan_set_false` 分支,**完全不动 status / priority / 其他字段**。ADHD 友好「飞书是真相源」体验完全破坏。

### 🛠 实施

**3 个新 helper(DRY)**:

| helper | 职责 |
|---|---|
| `_extract_fields_from_feishu_row` | 从飞书 row 抽 OB frontmatter 同步字段 dict(从 `_create_task_md_from_feishu_record` 拆出共享) |
| `_strip_wikilink` | OB wikilink 形态 → 裸名字 |
| `_diff_frontmatter_with_feishu` | 读 OB frontmatter + 飞书字段 diff + 防误清 + summary |

**`_REVERSE_SYNC_FIELD_WHITELIST` 8 字段**:`priority / status / category / subcategory / adhd_priority / estimate_hours / due / done_date`

**防误清逻辑**:`PRESERVE_OB_IF_FS_EMPTY = {category, subcategory, adhd_priority, estimate_hours, due, done_date}` — 飞书侧空 + OB 有值 → 保留 OB(避免误清用户手填数据)。`status / priority` 例外(必有值)。

**`pull_today_from_feishu` 扩展**:
- Step 4.5 预计算 `field_diffs[rid]`(3 分支统一处理)
- 三分支(plan_set_true / plan_skip / plan_set_false)合并 today_* updates + 字段 diff updates,一次 `update_md_frontmatter`
- dry-run 必显示 `field: ob_val → fs_val` 格式

**`_format_yaml_value` 加 wikilink 双引号特例**:`[[xxx]]` 形态写回时用双引号包裹(`"[[xxx]]"`),与 OB 端约定一致。

### 🚧 实施中浮现的 false positive

dry-run 后发现 2 个 false positive,**修正**:

1. **`due` 字段被清空**(2 条 task)— OB 有值,飞书空 → 误清 → 加 `PRESERVE_OB_IF_FS_EMPTY` 防御
2. **`parent_project` 全部改成「00 布丁」**(7 条 task)— v0.2.5 helper 读写死的"项目"字段,实际是"产品项目" link 字段 → **从白名单移除**,留 v0.3.8 修

修正后 dry-run:**0 false positive,5 条真实 diff 全检出**。

### ✅ 用户实测通过(2026-05-28 早晨)

| task | sync 结果 |
|---|---|
| `5月28日AI日报` | status: todo → **done** ✅ |
| `日常习惯打卡` | status: doing → **subdone** ✅(SubDone case 也通了) |
| `上传pdfAI教育报告` | priority: P1→P2, status: todo→**done** ✅ |
| `JWT的token过期方案` | status: todo → **doing** ✅ |
| `案例文章付费看` | priority: P1→P2, status: todo→**doing** ✅ |

**端到端验证**:用户截图「【布丁开发】案例文章付费看 · 🔼 P2 · 🔄 Doing」+ 飞书看板「P2 / Doing / 是否今日 ✅」**两端完全一致**。

### 📚 文档对齐

- CHANGELOG.md v0.3.7 entry(含 8 原则自评 + v0.3.8 候选)
- README.md badge v0.3.7 + 顶部 v0.3.7 上线段
- install.sh banner v0.3.7
- ARCHITECTURE.md 无需改(无新 schema 字段,只改 sync 行为)

### 决策记录

**Q**:范围扩到 plan_skip(原本设计上「真跳」的分支)是不是 over-engineering?
**A**:不是。用户痛点案例 `5月28日AI日报` 恰好是 plan_skip 路径(OB 端 today=true,飞书也 today=true,但 status 改了)。**不扩到 plan_skip 就解决不了用户痛点**。

**Q**:为什么 parent_project 不一起修?
**A**:v0.2.5 _create_task_md_from_feishu_record 的字段抽取就有读"项目"字段写死 bug(应该读 config 里的 "产品项目")。修这个需要解析 link record_id → record name,工作量不小。v0.3.7 范围已经够大,把 parent_project 留 v0.3.8 清晰。

**Q**:`PRESERVE_OB_IF_FS_EMPTY` 这个集合涵盖了 status / priority 之外的所有字段,理论上 status / priority 也可能误清,要不要加进去?
**A**:status / priority 飞书侧必有值(默认 Todo / P3),空是异常 case。如果真触发空,可能是数据损坏,这时让飞书覆盖 OB(就算覆盖成"todo")反而能修复数据状态。保留例外。

---

## 会话 3:工程规范文档体系建立(早晨)

⏱️ 时长:约 1.5h(进行中)
📊 Token:(未记录)
🏷️ commits:(待 commit)

### 🎯 完成(进行中)

参考 zhixing-game 工程规范,适配 feishukanban-ob-sync 的「开源单脚本工具 / 个人 / patch 节奏」特点,建立 MVP + engineering 规范完备版。

**Phase 1 顶层 2 文件**:
- ✅ `docs/VERSION.md` — SemVer + bump 触发条件 + 操作清单 + 版本历史索引
- ✅ `docs/ROADMAP.md` — 当前 v0.3.8 进行中 + v0.3.9 候选 3 个 + v0.4 + v1.0 + 长期愿景

**Phase 2 engineering 5 文件**:
- ✅ `docs/engineering/README.md` — 索引
- ✅ `docs/engineering/iron-rules.md` — 6 条铁律展开版
- ✅ `docs/engineering/8-principles.md` — 8 条架构原则 + 已知违反 / 技术债 + 实例库
- ✅ `docs/engineering/git-workflow.md` — commit message / tag / 双推 / 跨工程 git 边界
- ✅ `docs/engineering/bash-conventions.md` — 复合命令禁用 + Read/Grep/Edit 工具优先 + hook 失败示例
- ✅ `docs/engineering/dev-sop.md` — 通用 9 步流程 + 5 个常见任务 SOP

**Phase 3 daily 日志**:
- 🔄 2026-05-28(本文件,撰写中)
- ⏳ 2026-05-27 回写 v0.3.1-v0.3.5
- ⏳ 2026-05-26 回写 v0.2.0-v0.3.0

### 决策记录

**Q**:CHANGELOG.md 是搬到 `docs/logs/CHANGELOG.md` 还是保留根目录?
**A**:**保留根目录**。开源项目惯例(GitHub / Gitee 自动渲染顶层 CHANGELOG),且 README 多处链接 `CHANGELOG.md` 相对路径。zhixing-game 是商业项目可以下沉,本项目不一样。

**Q**:要不要建 `docs/sprints/` / `BACKLOG.md` / `BUGS.md`?
**A**:**不建**。单人项目无 sprint,ROADMAP 够用。BUGS 用 GitHub issues 即可。zhixing-game 那套是多人商业项目复杂度,小工具不需要。

**Q**:engineering 5 文件是否重复 `.claude/CLAUDE.md`?
**A**:**有意重复**。`.claude/CLAUDE.md` 是 CC 上下文入口(每次会话自动加载),engineering/ 是规范化的可索引版本(wikilink 网络 / 跨工程查阅 / 与 ROADMAP-CHANGELOG-handoff 联动)。两者互补。

---

## 📊 当日总成果

| 维度 | 数量 |
|---|---|
| 版本上线 | 3 个(v0.3.6 / v0.3.7 / v0.3.8 工作树进行中) |
| sync.py 净改动 | ~400 行(v0.3.6: 24, v0.3.7: ~330, v0.3.8: 工作树未 commit) |
| 文档新增 | 7 个工程规范文件(VERSION + ROADMAP + engineering 5 件) |
| handoff | 1 个(v0.3.6 today_source OB 对接) |
| commits | 3 个(2af5d3b / 83d50d1 / a531587)+ 工程规范 commit 待做 |
| 用户实测 | v0.3.7 端到端通过,5 条 task md 反向字段 sync ✅ |

---

## 🔮 明日候选

- 写 v0.3.8 完整实施(`project_minor` 字段)+ commit + tag + push
- 或开 v0.3.9:`parent_project` link 字段反向 sync(P0 候选)
- 写 `docs/releases/v0.3.0.md` ~ `v0.3.7.md`(用户向 release notes,共 8 个)
- 5/27 + 5/26 daily 日志回写

---

## 🔗 相关

- [`../../VERSION.md`](../../VERSION.md)
- [`../../ROADMAP.md`](../../ROADMAP.md)
- [`../../../CHANGELOG.md`](../../../CHANGELOG.md)
- [`../../handoff/OB对接/2026-05-27-v0.3.6-today_source-handoff.md`](../../handoff/OB对接/2026-05-27-v0.3.6-today_source-handoff.md)
- [`../../engineering/README.md`](../../engineering/README.md)
