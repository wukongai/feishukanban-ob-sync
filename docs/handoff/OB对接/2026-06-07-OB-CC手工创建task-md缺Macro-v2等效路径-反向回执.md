---
created: 2026-06-07
status: reverse-handoff-pending
from_project: feishukanban-ob-sync(Claude Code in VS Code)
to_project: OB(Claudian)
priority: P1
target_version: v0.9.0
related_handoff: 2026-06-07-OB-CC手工创建task-md缺Macro-v2等效路径-handoff.md
tags:
  - reverse-handoff
  - task-md-schema
  - validate-task-md
  - macro-v2-parity
---

# 反向回执:task md schema 真相源 + `--validate-task-md` + `--create-task` titlePrefix 落地

## TL;DR

`feishukanban-ob-sync` v0.9.0 已落地 3 件事,完成 handoff 全部目标:

1. ✅ **schema 真相源**:`sync.py` 顶部 `TASK_MD_SCHEMA` dataclass tuple(28 字段),`parse_task_md` / `_build_task_md_content_from_params` / `validate_task_md` 三路引用
2. ✅ **`--validate-task-md <path>` CLI**:6 维度校验 + `--apply` 机械修复(改文件名 / H1 / 完成标记 / 清非法 enum / 修 lockstep)
3. ✅ **`--create-task` 补 titlePrefix**:复用现有 CLI(handoff 期望的 `--create-task-md` 等价,用户拍板),`parent_project` 非空 → 文件名/H1/完成标记/飞书任务标题自动加「【最终归属】」前缀,与 Macro v2 等效

## 偏离 handoff 的设计点

| handoff 期望 | 实际方案 | 理由 |
|---|---|---|
| 新增 `--create-task-md` | 复用 `--create-task`(v0.7.0+ 已存在,handoff 未察)补 titlePrefix | 等价能力,避免双 CLI 维护;用户拍板 |
| 抽 `lib/task_md_schema.py` | `sync.py` 顶部 dataclass | sync.py 单文件原则;用户拍板 |
| 各种 `--fix-prefix`/`--fix-subcategory` 子 flag | 统一 `--apply` 自动跑所有机械修复 | 减小 CLI surface |
| 校验维度 9 项(含 `subcategory/project_minor` 飞书白名单) | 6 维度本地校验,飞书 select 白名单校验留给 push 路径(`validate_select_value`) | 不依赖 cli,validate 跑得快;事故场景的 `subcategory: [AIcoding实践]` 本地虽抓不到,但 push 时仍由飞书 select 守门 |

## 落地行为细节

### `_compute_title_prefix` 规则(对齐 Macro v2)

```python
# 1) parent_project 非空 → 【<裸名>】(产品项目分支最终归属)
# 2) category=产品项目 但 parent_project 空 → ""(无前缀,对齐 Macro v2 行为;
#    永远不生成「【产品项目】」这种把大类名当前缀的怪标题)
# 3) category 非产品项目 + subcategory list → 【<cat>-<sub1>-<sub2>】
# 4) 仅 category → 【<cat>】
# 5) 全空 → ""
```

### `validate_task_md` 校验维度

1. **必填字段存在**(走 `TaskMdField.required`;list 字段裸空合法,半残由 lockstep 单独抓)
2. **enum 字段值在白名单**(走 `TaskMdField.enum`,本地校验;list 类逐项)
3. **wikilink 字段格式**(`parent_project`/`parent_task` 等;非 `[[X]]` 形式 → warn)
4. **文件名前缀对齐 frontmatter**:
   - 期望前缀 ≠ 文件名前缀,期望非空但文件名无 → **error** + `--apply` 修
   - 两者都有但不一致 → **warn**(让用户决策哪边是真相)
   - 文件名有但 frontmatter 推不出 → **warn**(建议补 `parent_project`)
   - 都空 → pass
5. **H1 与文件名前缀一致**(去日期前缀)— 不一致 → warn
6. **`today_history` / `today_source_history` lockstep**(长度相等)— 不一致 → error + `--apply` 修

### `--apply` 机械修复

复用现成的 `update_md_frontmatter`(已处理多行 yaml list 续行,v0.5.4 修过),不重复造轮子:
- 文件名前缀缺失 → `Path.rename` + 改 H1(re.sub)+ 改完成标记行(只在 `## ✅ 完成标记` 段下)
- enum 非法值 → frontmatter 改为裸 `key:`(对齐模板空风格)
- lockstep 不齐 → 短的补 `""` 到长的长度(保守策略;不丢历史)

## 真机验收(在用户 vault 上跑过)

| 样本 | 结果 |
|---|---|
| `2026-06-07-【AiCoding实践】走loop...md`(完美 Macro v2 输出) | ✅ 0 error / 0 warn |
| `2026-06-07-【AI Coding】CCSwitch 实测...md`(老数据 parent_project 空但 filename 有前缀) | ✅ 0 error / 1 warn(建议补 parent_project) |
| `2026-06-07-【AI博主 IP】写 token 精算...md`(filename `【AI博主 IP】` ≠ frontmatter `[[AI+自媒体]]`) | ✅ 0 error / 1 warn(让用户决策真相) |
| `2026-06-07-【feishukanban-ob-sync】v0.8.3...md`(lockstep 半残) | ✅ 抓 1 error;`--apply` 自动修对齐 |
| 模拟事故 task md(文件名无前缀)→ `--apply` | ✅ 文件名/H1/完成标记三处同步加前缀,复测 0 error |

`--create-task --parent-project "AiCoding实践" --title "测试" --priority P2 --json`:
- 产出文件名:`2026-06-07-【AiCoding实践】测试.md` ✅
- H1:`# 【AiCoding实践】测试` ✅
- 完成标记:`- [ ] 【AiCoding实践】测试` ✅
- 飞书 payload 任务标题:`【AiCoding实践】测试` ✅
- 产品项目 link 正确解析到 record_id ✅

## OB 端 follow-up 清单(用户带回 OB CC 决策 / 执行)

> **铁律 #2**:本项目 CC **不主动改 OB vault** — 以下事项请用户在 OB CC 内执行。

### 1. 改 `OB/.claude/rules/base-and-frontmatter.md` 的 task md schema section

- **删掉手工维护的 schema 表**(已散布漂移)
- 改为**反向链接到 sync.py 的真相源**:
  - 链接形式 1:GitHub permalink(commit hash 锁定) → `https://github.com/<user>/feishukanban-ob-sync/blob/<sha>/sync.py#L<line>-L<line>` 指向 `TASK_MD_SCHEMA` tuple
  - 链接形式 2:本地 obsidian 跳转(若 vault 内有 symlink 到 sync.py)
- schema 字段、required、enum、note 都从 sync.py 真相源读,不再手工列表

### 2. 改 `OB/.claude/rules/feishu-project-sync.md` 加铁律

新增 1 条铁律(建议放在「任务创建/同步」section):

> **OB CC 手工建 / 同步 task md 后,提交飞书前必须先跑 `--validate-task-md` 校验**
>
> ```bash
> python3 /Users/aim5/Documents/CodingProject/feishukanban-ob-sync/sync.py \
>   --vault /Users/aim5/Documents/OB \
>   --validate-task-md "<task md 路径>"
> # 0 error → 安全提交;有 error → 加 --apply 自动修 / 手动修后复跑
> ```
>
> **触发场景**:① OB CC 手工 `Write` 新 task md;② OB CC 修复半残/迁移老 task md;
> ③ pull-task 后想再 push 之前一次 sanity check。
>
> **原因**:2026-06-07 事故复盘 — OB CC 手写 task md 文件名/H1 缺「【父项目】」前缀
> + `subcategory` 误填 + `today_source_history` 漏写,4 轮迭代才修对(详见
> `docs/handoff/OB对接/2026-06-07-...handoff.md`)。validate 工具是机械守门员。

### 3. (可选)给 OB CC 加一个轻 skill `/检查task md`

参考 `~/.claude/skills/同步任务到飞书/SKILL.md` 包装一下 `--validate-task-md`,触发关键词:「检查 task md」「校验 task md」「task md 漏字段」等。skill 内部仅:
1. 取 ide_selection / 用户传入 task md 路径
2. 跑 `python3 sync.py --vault /OB --validate-task-md "<path>"`(dry-run)
3. 报告给用户;若 user 拍板 → 加 `--apply` 修

不强制,看用户时间。

## 后续 follow-up(留给本项目,不阻塞 OB 端)

| follow-up | 优先级 | 理由 |
|---|---|---|
| `subcategory` / `project_minor` 飞书白名单校验(可选 flag `--check-feishu-schema`) | P3 | push 路径已守门;只想"提前预校"加 1 次 cli 拉 schema 开销 |
| `validate_task_md` 加 `--check-h2-sections` 校验软段非空(配合 `--strict-soft-sections` 一致) | P3 | 当下宽松走 push 路径 strict_soft |
| `validate_task_md` 末尾再跑一次 validate 确认 `--apply` 修复完成(目前直接 return 0) | P3 | 用户重复跑一次即可确认,不阻塞使用 |
| `--apply` 自动从 today_source 推断 today_source_history(目前补 `""` 占位) | P3 | 已有 `--repair-history` 做这件事,validate 只做"对齐长度";想精准用 `--repair-history` |

## 完成记录(handoff 文档完成区填写)

> 实际耗时:~2.5 小时(spec 30min + Phase 1 dataclass 20min + Phase 3 titlePrefix 30min + Phase 2 validate 60min + 真机验收 + 反向回执 30min)
> 偏离 spec 的地方:`_compute_title_prefix` 在 category=产品项目 但 parent_project 空时返回 ""(不 fallback 到「【产品项目】」),对齐 Macro v2 真实行为;validate 文件名前缀校验改为「尊重文件名现状」(老数据有前缀但 parent_project 空 → warn 而非 error)
> 测试结果:5 个真机验收样本全通过(完美 Macro v2 → 0 error;老数据 → warn 提示;事故场景 → error 抓出 + --apply 修对)
> commit hash:(本会话尚未 commit,待用户 review 后)
> 反向回执文件:本文件

## 状态变更记录

- 2026-06-07 10:30 OB CC 创建 handoff(`status=handoff-pending`)
- 2026-06-07 11:40 feishukanban-ob-sync CC 完成 3 phase(`status=reverse-handoff-pending`),等用户带回 OB CC 执行 follow-up
