---
created: 2026-06-02T22:00:00
status: handoff-completed
from_project: feishukanban-ob-sync(Claude Code in VS Code)
to_project: OB(Claudian)
ref_handoff: docs/handoff/OB对接/2026-06-02-sync-py-select字段校验增强-handoff.md
priority: P1
tags:
  - reverse-receipt
  - sync.py
  - select-validation
  - dx
---

# 反向回执:sync.py select 字段全面校验 + 友好报错 — 已落地

## 总结

handoff 6 个 Phase + 4 个反测用例全过 ✅。新增 `fetch_table_schema` + `validate_select_value`,在 `build_fields_payload` 内统一拦截所有 task md select 字段(`category / subcategory / project_minor / adhd_priority / priority_str / efficiency / quality`)的白名单外值,事故复现案例(`project_minor: [CC 工程化, 数据分析]`)从「飞书 `code=800010401 invalid_request` 宽泛报错」变成「dry-run 阶段清晰提示 + 列白名单 + 给修复路径」。

## 版本号 + commit hash

- 版本:**v0.7.9**(patch — 修飞书宽泛报错 + 加 `--strict-select` 新 flag,默认行为兼容)
- commit hash:**待 commit**(本回执先落,合并 commit 后追加 hash;用户 review 通过后才 commit + 待用户决定是否 push,**遵守铁律 #1**)
- 实际耗时:约 90 分钟(读 handoff 20 + 设计 + 代码 50 + 反测 + 文档 20)
- 实际改动文件:
  - `sync.py`(+~250 行,改 9 处) — 核心实施
  - `config.yaml`(注释更正项目小类「multi-select」→ 单选 + 白名单)
  - `CHANGELOG.md`(v0.7.9 section)
  - `README.md`(顶部 badge → v0.7.9)
  - `docs/handoff/OB对接/2026-06-02-sync-py-select字段校验增强-完成回执.md`(本文件)

## 反测 4 用例结果

| Case | 配置 | dry-run 关键输出 | apply 行为 | exit code | 期望 | 实际 |
|---|---|---|---|---|---|---|
| 1 全合法 | `project_minor: [claudecode]` + 全字段合法 | 🔍 全部通过 ✅ + payload 含 7 个字段 | 通过 | 0 | ✅ | ✅ |
| 2 白名单外+默认 | `project_minor: [CC 工程化, 数据分析]` | ⚠️ 单选多值截一 + ⚠️ 不在白名单 + 列白名单 + 后台加选项建议 + 「项目小类」字段被跳过 | 其他字段照常 sync | 0 | ✅ | ✅ |
| 3 白名单外+strict | 同 case2 + `--strict-select` | ⛔ 拒推 + 3 个修复路径 | 整条 task 拒推 | 1 | ✅ | ✅ |
| 4 单选传多值合法 | `project_minor: [claudecode, skill]` | ⚠️ 截第一个 claudecode + payload 写 `[claudecode]` | 不拒推 | 0 | ✅ | ✅ |

完整反测输出存档:`/tmp/select-validation-test/case[1-4]-out*.txt`(本回执后清理)。

## 关键设计决策(handoff 之外)

### 1. cli 分页 bug 应对:多轮累积合并

**反测发现的隐藏坑**:`feishu-cli bitable field list` 每次只返 **20 条**(`total=31`),且每次返回的字段子集**随机**(无 `page_token` 参数,cli 不暴露分页机制)。意味着单次 `field list` 拿到的 schema **永远不全**,会把合法字段误报「不在 schema」。

**应对**:`fetch_table_schema` 内部多轮循环调用,by `field_id` 去重累积。达到 `total` 即停;连续 3 轮无新字段(服务端真没更多了)也停;最多 15 轮上限保护。摊销首次 cache miss,后续命中 cache O(1)。残缺仍能跑(降级:可能误报但不阻断)。

代码位置:`sync.py:1555-1635` 区段,`_SCHEMA_FETCH_MAX_ROUNDS = 15`。

### 2. project_minor 实测是单选

**修正 sync.py:1330 + config.yaml 注释**:实测「项目小类」`multiple=false` 单选(早期注释「multi-select」错误,这是事故根因之一)。白名单(2026-06-02):**训练营 / 干货 / 智能体 / claudecode / skill / Codex / 软硬件**。

frontmatter 仍写 YAML list(给 OB Cmd+P 弹最近 5 条选项保持工作流不变),sync.py 内由 `validate_select_value` 据 schema 动态判断:单选传多值 → 截第一个 + warn。

### 3. 警告输出格式

dry-run 输出三段式 warn(对照 handoff 范例):
- 第 1 行:列出非法值 `字段「项目小类」N 个值不在白名单:[...]`
- 第 2 行:列白名单(超过 10 项截断 + 「共 N 项」尾标)
- 第 3 行(可选):相似项建议(fuzzy 子串匹配,无相似项则不打)
- 第 4 行:固定建议「去飞书后台 X 字段加 [...] 选项后重跑」

末尾汇总 + strict 提示:`⚠️  1 个 select 字段因值不在白名单被跳过(其他字段照常 sync): 项目小类 / 提示:加 --strict-select 后这些字段将触发拒推(skill 路径默认启用)`

### 4. strict 拒推消息

`--strict-select` 触发时 `_fail()` 打:
```
⛔ 拒推(--strict-select):N 个 select 字段值不在飞书白名单
   字段:项目小类
   修复路径(任选其一):
   ① 改 frontmatter 用现有白名单选项(看上方「相似项」建议)
   ② 去飞书后台对应字段添加缺失选项后重跑
   ③ 去掉 --strict-select 走宽松模式 — 字段跳过但其他字段照常 sync(菜单路径的默认行为)
```

exit 1,与 `--strict-soft-sections` 拒推走同款 `_fail()` 出口。

### 5. 默认行为完全兼容

- 默认宽松模式 + 全合法 → payload 与 v0.7.8 完全一致(`out[field_name]` list 包裹)
- 默认宽松 + 白名单外 → 该字段从 payload 删除(不撞 `invalid_request`),其他字段照样 sync
- cli 拉 schema 失败 → schema=None,`validate_select_value` 走降级分支(透传 list 包裹,不校验),对齐 `behavior.fail_fast=false`
- inline journal 模式(`push_journal`)不走 task_md select 分支,行为完全不变

## 给 OB CC 的 follow-up 待办

### 必做:SKILL.md 加 `--strict-select` 启用

**`~/.claude/skills/同步任务到飞书/SKILL.md`「apply 前自检清单」加一条**:走 skill 路径的 `--apply` 命令必须**同时**加 `--strict-select` 和 `--strict-soft-sections`(两个 flag 平行,都默认 False、都对应 skill 路径必启用)。

建议改法:
- 现状 SKILL.md 凡是 `python3 sync.py ... --apply --strict-soft-sections` 的位置,统一加 `--strict-select`
- 在「apply 前自检清单」加一条 bullet:**select 字段值必须在飞书白名单**(由 `--strict-select` 强制 — 不需要 Claude 自检,工具拦截)
- 说明:strict-select 会让"frontmatter 笔误 / OB CC 自创标签"在 apply 阶段直接拒推 + exit 1,Claude 必须改 frontmatter 用白名单内的值或去飞书后台加选项再重跑
- 跟 `--strict-soft-sections` 一致的语义:**菜单路径默认宽松、skill 路径默认严格** — 用户既能保留 OB Cmd+P 快速建骨架的工作流,又能让 Claude/skill 路径严守白名单

### 可选:OB Cmd+P「快记任务」project_minor 菜单源

现 userscript 走 `recent_project_minor`(最近 5 条 distinct),按 set 顺序取 — 用户可能选到的仍是已有的(白名单内的)。本次校验生效后,即使用户在 OB 端手敲新 project_minor 值,sync.py 也会拦截。**不需要改 userscript**,工作流不变。

### 不动:飞书后台选项

铁律 #2 — 不动用户私域。飞书后台「项目小类」是否加「CC 工程化」等新选项,是用户决策(目前白名单 7 项已能覆盖大部分场景)。

## Spec 偏离 / 实施方自主决策点

- **没加 record list 反推 select 选项**(handoff「非目标」明确要求不做) — 选了 `field list` 多轮累积方案
- **没改飞书后台**(handoff「非目标」要求只读校验)
- **加了 cli 分页 bug 多轮累积(handoff 没要求,但反测发现是 hard blocker,必须做)**
- **没加单元测试**(handoff「非目标」隐含;反测以 manual 4 用例 + 输出贴回执形式) — 仓库目前也没 `tests/` 目录;若后续加测试基础设施,这些函数可单独 mock cli 测

## 状态变更记录

- 2026-06-02 20:00 OB CC 写完 handoff,状态 handoff-pending
- 2026-06-02 22:00 feishukanban-ob-sync CC 完成实施 + 4 用例反测全过,本回执发出,状态 handoff-completed
- 2026-06-02 22:00+ 等用户 review 后 commit;commit hash 后补
