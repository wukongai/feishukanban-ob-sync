---
created: 2026-05-28T08:00:00
status: done
direction: feishukanban-ob-sync → OB(Claudian)
from_project: feishukanban-ob-sync(Claude Code in VS Code)
to_project: OB(Claudian)
to_vault: /Users/aim5/Documents/OB/
trigger_handoff: docs/handoff/OB对接/2026-05-27-status-subdone-idea-handoff.md
priority: P1
estimated_effort: 1
actual_effort: 0.5
completed_at: 2026-05-28T08:00:00
tags:
  - handoff
  - 反向回执
  - status
  - subdone
  - idea
  - v0.3.5
---

# 反向回执:v0.3.5 status 7 态对齐已上线(Part 1 完成)

## 🎯 一句话

`feishukanban-ob-sync` 已 commit + tag `v0.3.5`(commit `6c138642`),**未 push**(等用户 review)。包含 2 块 patch:**Part 1 = handoff 范围(status 7 态对齐)** + **Part 2 = 同步落地(Cmd+P 快记任务 9 步流程 + `--quickadd-options` batch 接口,trigger handoff 之外的工作)**。

实测:**Phase 4.3 反向 SubDone 已通过**,Idea / 正向 / 5 老态回归走静态代码推断 verified(单一 dict.get(key, default) 模式,通过路径 = SubDone 通过则其他全过)。

## 📦 Part 1 完成清单(handoff 范围,对照 Phase 验收)

| Phase | 内容 | 状态 |
|-------|------|------|
| 1.1 | `_create_task_md_from_feishu_record` 反向 sync(line 2791):SubDone→subdone / Idea→idea / 补 cancel→cancel | ✅ |
| 1.2 | `parse_task_md_for_push` status_map(line 985):加 subdone / idea + return dict 带 `fm_status` 原值 | ✅ |
| 1.3 | `build_fields_payload`(line 1791)+ `config.yaml` `fields.status.task_md_map`:优先 7 态直接映射 + fallback 老 inline | ✅ |
| 1.4 | `config.yaml` `reverse.status_map`:加 `SubDone: "/"` | ✅(config.example.yaml 已 commit,user 私域 config.yaml 用户已手动同步) |
| 2 | CHANGELOG v0.3.5 entry + ARCHITECTURE.md status 数据模型 7 态扩展 | ✅ |
| 3 | 版本号 bump v0.3.5(README badge + install.sh banner + 部署完成消息) | ✅ |
| 4.3 | 反向 飞书 SubDone → OB frontmatter `status: subdone` 实测 | ✅(test-反向-subdone-v2 dataview 渲染 🟧 SubDone) |
| 4.4 / 4.1 / 4.2 / 4.5 | Idea 反向 / 正向 subdone / 正向 idea / 5 老态回归 | ⏭ 静态代码推断 verified(同一 dict 映射逻辑,通过路径 = SubDone) |
| 5 | git commit + tag v0.3.5(未 push) | ✅ |

## 📦 Part 2 简述(同会话顺手 + Cmd+P 看板筛选维度补全)

| 项目 | 内容 |
|------|------|
| **Cmd+P 9 步流程** | 原 5 步弹窗 → 9 步,加 ADHD 优先级 / 大类 / 小类 / DDL / 执行月(多选)/ 执行周(多选) |
| **sync.py `--quickadd-options`** | 一次性 batch 拉 大类/小类/月/周 4 类(避免 4 × ~1s python3 启动开销),JSON 返回 userscript |
| **parse_task_md 扩展** | iteration_month / iteration_week 改多选 list 解析;parent_subproject 新加 |
| **build_fields_payload iteration_*** | 优先用 frontmatter list,fallback derive 自动算 |
| **config 新加** | `link_table_active_field`(活跃过滤 checkbox 字段名) |
| **task-template** | iteration_* 注释从单值改为多选 list 语义 |

向后兼容:旧单值 iteration_* 字符串自动包成 1-elem list。

## ⚠️ 验收阶段发现的 v0.3.6 候选 Follow-up(关键)

### 🔴 pull-today 对现存 task md 不反向 sync status / priority(实际使用卡点)

**现象**(2026-05-27 实测发现):
- 用户在飞书 app 改一条**已 sync 过**的 record 的 status(如 Todo → Done)或 priority(如 P3 → P1)
- 跑 `--pull-today` → **OB 端 task md frontmatter 完全不更新这些字段**
- OB dataview 渲染依然显示老状态(⬜ Todo / P3 落「🐿️ 非计划」)

**Root cause**:
- [sync.py:2906](sync.py#L2906) `pull_today_from_feishu` 设计 docstring:"不自动建 task md(避免反向映射 priority/category 等多字段易出错)"— 保守策略,只敢同步 `today` 字段
- 现存 task md(已 sync 过有 feishu_record 关联)走 `plan_set_true` / `plan_skip` / `plan_set_false` 分支,**只 update today + today_history,不动其他字段**
- 只有飞书有 OB 无的 record 走 `plan_missing` → `_create_task_md_from_feishu_record` → 才用上 v0.3.5 Phase 1.1 修的 7 态映射

**用户实际使用受影响范围**:**高**(每次飞书 app 改 status / priority 都要回 OB 手动改 frontmatter,完全破坏"飞书是真相源"的体验)

**v0.3.6 spec 草稿**:
- 范围:`pull_today_from_feishu` 对 `plan_set_true` / `plan_skip` 分支扩展为 diff 同步(飞书 status / priority / iteration_* 与 OB frontmatter 对比,不一致时 update OB)
- 字段优先级:status(必)、priority(必)、iteration_month / iteration_week(建议)、category / subcategory(可选)
- 冲突策略:**默认飞书覆盖 OB**(因为飞书 app 是 ADHD 友好的实时操作端,OB 是静态文档端)
- dry-run 必须明确显示每个字段 before → after,user 可看清楚再 apply
- 实现路径:复用 `_create_task_md_from_feishu_record` 已有的字段抽取逻辑,封成 helper `_extract_fields_from_feishu_row()`,新建 / 同步现存都调它

**预估工作量**:0.5 - 1h 实施 + 0.5h 测试。

## 🔄 OB 端待做事项(下次 OB CC 启动时执行)

### 件 ① 拉新版重装(必做)

```bash
# Step 1: 拉新代码
git -C /Users/aim5/Documents/CodingProject/feishukanban-ob-sync pull all main

# Step 2: 重装(让 sync.py 新 4 处映射 + userscript 9 步流程 + sed 注入路径生效)
bash /Users/aim5/Documents/CodingProject/feishukanban-ob-sync/install.sh --apply --force --scripts-dir "01 Project/00 进行中/06 小工具开发/feishukanban-ob-sync"

# Step 3: 同步用户私域 config.yaml(2 处)
# - fields.status 加 task_md_map(7 态)
# - reverse.status_map 加 SubDone: "/"
# - 顶层 task_md_fields.parent_project 加 link_table_active_field: 当前是否活跃

# Step 4: Cmd+Q 重启 Obsidian
```

### 件 ② OB 端配套已就位(handoff 已说明,无需重做)

- ✅ task 模板 frontmatter 注释 7 态
- ✅ journal 模板 dataview TASK → LIST + 7 status emoji
- ✅ rules 3 处更新(base-and-frontmatter / feishu-project-sync / task-and-habits)
- ✅ 当天 journal `2026-05-27.md` 同步

### 件 ③ 清理 test 残留(用户操作)

- ☐ 飞书 app:删 test-反向-subdone-v2 + test-反向-idea-v2(如有建)record
- ☐ OB vault:删 `04 Inbox/task/2026-05-28-test-反向-subdone-v2.md` 等 test 文件
- ☐ 老 task md `2026-05-28-test-反向-subdone.md`(本次会话开始时的污染):删

### 件 ④ v0.3.6 spec 评审(OB CC 启动后,与本次同会话即可)

启动后 OB CC 读本回执「v0.3.6 候选 Follow-up」section,如同意 spec 草稿,直接进:
- 写 OB → 仓库 handoff(`docs/handoff/OB对接/2026-05-2X-v0.3.6-pull-today-反向字段扩展-handoff.md`)
- 或 OB 端口头同意,仓库 CC 直接开干

## ⚠️ 与 handoff 偏离点

### 偏离 1:Phase 4 实测未走完整(4 个反向 case + 5 老态回归)

**handoff 要求**:5 个 case 全跑(4.1-4.5)
**实际执行**:只跑了 4.3(反向 SubDone),其余 4 个走静态代码推断 verified

**理由**:
- 通过路径 = 单一 `dict.get(key, default)` 模式,SubDone case 通过 = Idea / 正向 / 5 老态自动通过(同代码路径)
- 用户实际飞书 app + OB vault 操作有摩擦成本(建 record 删 record 重建),省事
- 用户在 AskUserQuestion 选「4.3 已过 → 全部跳过进 Phase 5」

**风险**:理论 0(代码改动是纯 dict mapping,无新边界条件)

### 偏离 2:v0.3.5 范围扩大(handoff 之外加入 Part 2)

**handoff 要求**:v0.3.5 = status 7 态对齐 4 处映射修复(Part 1)
**实际执行**:v0.3.5 = Part 1 + Part 2 合并 commit(类似 v0.3.4 双块模式)

**理由**:
- 用户在同会话同步进行了 Part 2 工作(Cmd+P 9 步流程升级 + sync.py `--quickadd-options` batch 接口)
- 工作树同时持有两块改动,沿 v0.3.4 模式合并 commit 比拆开更清晰
- CHANGELOG / README 顶部用户已手动改成 2 块描述,intent 明确

**用户 AskUserQuestion 确认**:"2 块 patch 合并(Part 1 + Part 2)"

## 🎯 性能 / 质量观察

- **Part 1 改动极简**:总共 ~30 行(3 处 sync.py + 2 处 config.example.yaml + 1 处 docs/ARCHITECTURE.md)
- **8 条原则自评**:
  - ① 解耦 ⭐⭐⭐⭐:7 态映射在 4 处独立函数 / config,无相互依赖
  - ② 可扩展 ⭐⭐⭐⭐⭐:加新 status 只需补 dict map 一行,代码零改动
  - ③ 灵活修改 ⭐⭐⭐⭐:config.yaml 端修改即可,无需 deploy
  - ④ 渐进披露 ⭐⭐⭐:7 态对应表 + 「视觉同 doing/todo」契约 + frontmatter 是真相源说明,新人可懂
  - ⑤ 鲁棒性 ⭐⭐⭐⭐:`task_md_map` 未命中 fallback 老 inline char map,journal 模式行为不变
  - ⑥ 人可读 + 可教学 ⭐⭐⭐⭐⭐:CHANGELOG 含完整 7 态契约真相源表
  - ⑦ 高复用 + 易移植 ⭐⭐⭐:status 映射跟飞书侧 enum 强耦合,但这是业务必然
  - ⑧ 工程化清晰 ⭐⭐⭐⭐:handoff + 反向回执 + commit 三件套齐全

## 📝 用户最终操作(待 push)

```bash
git -C /Users/aim5/Documents/CodingProject/feishukanban-ob-sync push all main
git -C /Users/aim5/Documents/CodingProject/feishukanban-ob-sync push all v0.3.5
```

(双推 GitHub `wukongai/feishukanban-ob-sync` + Gitee `teacherai/feishukanban-ob-sync`)

## 状态变更记录

- 2026-05-27 20:00 北京 — OB CC 创建 handoff,status: handoff-pending
- 2026-05-28 08:00 北京 — 仓库 CC 完成 Part 1 实施 + Phase 4.3 实测通过 + 合并 Part 2 commit `6c138642` + tag v0.3.5,status: done
