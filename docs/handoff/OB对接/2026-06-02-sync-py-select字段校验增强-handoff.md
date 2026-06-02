---
created: 2026-06-02T20:00:00
status: handoff-pending
from_project: OB(Claudian)
to_project: feishukanban-ob-sync(Claude Code in VS Code)
to_repo: /Users/aim5/Documents/CodingProject/feishukanban-ob-sync
spec:
plan:
priority: P1
estimated_effort: 2-3 小时
tags:
  - handoff
  - sync.py
  - select-validation
  - dx
---

# sync.py select 字段全面校验 + 友好报错(改善 dry-run 体验)

## 一句话需求

apply 跑通 OB CC 同步 task md 到飞书时,**因「项目小类」字段传了不存在的选项 + 误把单选当多选**,触发飞书 API 返回 `code=800010401 invalid_request` 宽泛报错,排查耗时 ~15 分钟才二分定位。**改进 sync.py:dry-run 阶段就主动校验所有 select 字段的合法选项 + 单/多选语义,提前用清晰错误信息提示用户,而不是把模糊的 API 报错丢给用户排查**。

## 背景

**触发事故**:2026-06-02 OB CC 帮用户把 task md sync 到飞书项目管理表(扫尾归档 `recvllkUpGIb3v`),走 skill `/同步任务到飞书` 的 🅱 路径 B(UPDATE 已有 task)。task md frontmatter 写了 `project_minor: [CC 工程化, 数据分析]`(OB CC 根据本任务实际特征生成的两个新分类标签),sync.py 直接把它当作 multi-select 传到飞书,触发 `invalid_request`。

**二分定位过程**(浪费的时间):
1. dry-run 全绿,apply 报 `code=800010401 invalid_request`,无具体字段信息
2. 用 feishu-cli 单字段 minimal upsert 测试:状态 ✅ → 加价值优先级/大类 ✅ → 加小类/项目小类/ADHD ❌
3. 再二分:仅小类 ✅ / 仅项目小类 ❌ / 仅 ADHD ✅
4. 用 `feishu-cli bitable field list` 拉飞书表 schema:`项目小类` 字段 `multiple: false` 单选 + 选项白名单只有 7 个(训练营 / 干货 / 智能体 / claudecode / skill / Codex / 软硬件)→ 二个 OB 端原值都不在白名单
5. 修复:改 task md `project_minor: [claudecode]`(单值 + 已有选项)→ apply 成功

**根因 — 三个相关 bug 叠加**:
1. **select 字段没做选项校验**:`project_minor / category / subcategory / adhd_priority / priority` 等都直接把 frontmatter 原值传飞书,飞书白名单外的值触发 `invalid_request`
2. **sync.py 代码注释写错单/多选语义**(sync.py:1330 注释「v0.3.8: project_minor 项目小类,task 表 multi-select」),但实测飞书侧 `multiple: false` 单选
3. **错误信息层级过浅**:飞书 API 返回 `code=800010401: invalid_request: invalid_request`,不指明具体哪个字段错,sync.py 没解析也没本地预校验

**对比 — `iteration_week / iteration_month` 已有的好做法**:2026-05-18 你给这两个字段加了 `best_match_enum`(基于 `feishu-cli bitable field search-options`),未命中静默跳过 + 缓存。本次要求**把这套机制扩展到所有 select 字段**,且失败时给具体报错而不是静默跳过。

## 目标 / 非目标

### 目标(必做)

1. **所有 select 字段统一走选项校验**:`category / subcategory / project_minor / adhd_priority / priority` 等所有映射到飞书 select 字段的 frontmatter 字段,在 dry-run 阶段拉飞书 schema 校验
2. **dry-run 输出区分校验结果**:每个 select 字段标注「✅ 已校验」/「⚠️ X 个值不在白名单:[xxx, yyy]」/「❌ 字段是单选,但传了多个值」
3. **修正 `project_minor` 字段单/多选语义**:从配置或 schema 动态判断(`multiple` 字段),不是硬编码;sync.py:1330 注释同步修正
4. **失败时给清晰报错 + 可执行建议**:apply 前如果有不合法值,默认阻断 + 列出"飞书后台可用选项 / 建议去后台添加 X 选项 / 改 frontmatter 用现有选项 Y"三个候选方案
5. **保持向后兼容**:`iteration_week / iteration_month` 现有 `best_match_enum` 行为不变(仍走 search-options 模糊匹配 + 静默跳过)

### 非目标(不做)

- ❌ 自动建飞书选项(不要冒险写飞书 schema,只读校验)
- ❌ 模糊匹配代替严格白名单(`project_minor` 不像 `iteration_week` 那样有"自然语义",硬要 fuzzy 容易选错)
- ❌ 兼容 `record list` 反推选项(直接调 `field list` 一次拿全 schema 即可,效率更高)
- ❌ 改 OB 侧 task md schema(本次只改 sync.py 的校验层)

## 接口契约

### 输入(OB 端 frontmatter)

frontmatter 字段照旧,**不强制改 schema**。OB CC 写值时仍可能传白名单外的值(因为 OB CC 不知道飞书后台真实选项)。

```yaml
project_minor:
  - claudecode    # ✅ 白名单内
  - CC 工程化      # ❌ 白名单外(本次事故的真实值)
category: 技能工具  # ✅ 校验
subcategory:
  - 工具开发        # ✅ 校验
```

### 输出(sync.py dry-run / apply 行为)

**dry-run 时**:

```
============================================================
📝 task md 模式: ...
📌 dry-run(--apply 才真写)
============================================================

🔍 校验 select 字段(拉飞书 schema)...
  ✅ category:        值「技能工具」 在白名单
  ✅ subcategory:     值「工具开发」 在白名单
  ⚠️  project_minor: 单选字段,传了 2 个值 → 只保留第一个「CC 工程化」
                     选项「CC 工程化」不在白名单(白名单:训练营/干货/智能体/claudecode/skill/Codex/软硬件)
                     建议 1:改 frontmatter 用现有选项(claudecode 与本任务最匹配)
                     建议 2:去飞书后台「项目小类」字段加「CC 工程化」选项后重跑
                     ⚠️  apply 时将跳过该字段(其他字段照常 sync)
  ✅ adhd_priority:   值「自由待办」 在白名单
  ✅ priority_str:    值「P2」 在白名单
```

**apply 时**:
- 校验失败的字段从 payload 中**跳过**(不阻断其他字段),并打印 `⚠️` 提示
- 如果有任意 select 字段校验失败,**末尾再列一遍跳过摘要**(便于用户决策"是否要去后台加选项 + 重跑")
- 提供 `--strict-select`(可选 flag,与现有 `--strict-soft-sections` 平行)开关:校验失败时整个 task 拒推,避免静默丢字段

### 错误处理契约

| 场景 | 行为 |
|---|---|
| 飞书 `field list` cli 失败(网络 / token 过期) | 退化为不校验 + warn(不阻断 sync) |
| 字段不存在(`field_name` 配置错) | warn,跳过该字段 |
| select 字段配置错(`type` 不匹配) | warn,跳过该字段 |
| `--strict-select` 开启 + 任意校验失败 | 整个 task 拒推,exit code 1 |

### 缓存

`_ENUM_MATCH_CACHE` 已有,但是 (field_id, query) → option_name 形式,不适合本次全选项缓存。建议**新增** `_FIELD_OPTIONS_CACHE: dict[str, dict]`(key = field_id,value = `{multiple: bool, options: list[str], type: str}`),整张 schema 拉一次,所有字段共用,**进程内缓存,sync.py 跑一次 task 命中一次**。

## 实施任务(分 Phase 勾选清单)

### Phase 1:抽取 + 缓存 schema

- [ ] 写 `fetch_table_schema(base_token, table_id, config) -> dict`,调 `feishu-cli bitable field list`,返回 `{field_name: {id, type, multiple, options: [name1, name2, ...]}}`
- [ ] 模块级缓存 `_FIELD_OPTIONS_CACHE`,key = `(base_token, table_id)`(支持多表;当前只有一表,但留扩展)
- [ ] cli 失败兜底:catch + warn + 返回 `None`,调用方降级为不校验

### Phase 2:select 字段统一校验函数

- [ ] 写 `validate_select_value(field_name: str, value: Any, schema: dict) -> tuple[Optional[Any], list[str]]`,返回 `(validated_value, warnings)`
  - 单选传 list → 取第一个 + warn
  - 多选传 string → 包成 list
  - 值不在白名单 → 返回 None + warn(列出建议:已有相似选项 / 添加新选项)
- [ ] 在 `build_fields_payload`(或对应组装 payload 的函数)里,对所有 select 字段批量调 `validate_select_value`
- [ ] 跳过的字段从 payload 删除,但记录到 `dropped_fields` 列表供 dry-run 显示

### Phase 3:dry-run 输出

- [ ] dry-run 显示「🔍 校验 select 字段」section,逐字段列结果
- [ ] 失败字段末尾汇总:「X 个 select 字段值不合法,apply 时将跳过」
- [ ] 提示飞书后台修复路径(本节「输出」section 的 dry-run 范例)

### Phase 4:`--strict-select` flag

- [ ] argparse 加 `--strict-select` flag(默认 false,与 `--strict-soft-sections` 平行)
- [ ] strict 模式下,任意 select 字段校验失败 → 整个 task 拒推 + exit 1
- [ ] 更新 SKILL.md(OB 侧 `~/.claude/skills/同步任务到飞书/SKILL.md`)的「apply 前自检清单」加一条:strict-select 建议同时启用(meta-skill 的 SOP 升级,这条由 OB CC 在反向回执后做)

### Phase 5:修正 project_minor 单/多选语义

- [ ] sync.py:1330 注释「task 表 multi-select」→ 改为「单/多选由 schema 动态判断」
- [ ] `_ensure_list(fm.get("project_minor"))` 改为根据 schema 的 `multiple` 字段决定:单选取第一个 string,多选保留 list
- [ ] 注意向后兼容:OB 端 frontmatter `project_minor:` 仍写 YAML list,sync.py 内部按 schema 决定如何打 payload

### Phase 6:测试 + 文档

- [ ] 复现本次事故:`project_minor: [CC 工程化, 数据分析]` + dry-run → 期望看到清晰报错
- [ ] 测试正向用例:`project_minor: [claudecode]` → 期望 apply 成功(与现状一致)
- [ ] CHANGELOG.md 加版本号(v0.7.x → v0.8.0?根据现行版本号)
- [ ] feishu-schema.md 更新「项目小类」字段说明(标 single-select + 列 7 个白名单选项)

## 验收标准

完成后跑下面 4 个用例,期望全部符合:

1. **正向**:`project_minor: [claudecode]` + `category: 技能工具` + `subcategory: [工具开发]` → dry-run 全绿 + apply 成功
2. **白名单外值**(默认):`project_minor: [CC 工程化]` → dry-run 标 ⚠️ + 列建议 + apply 仍成功(其他字段照样 sync,project_minor 跳过)
3. **白名单外值 + strict**:`project_minor: [CC 工程化]` + `--strict-select` → dry-run 标 ❌ + apply 拒推 + exit 1
4. **单选传多值**:`project_minor: [claudecode, skill]` → dry-run 标 ⚠️ 只保留第一个 + apply 写入 claudecode

## 不包括(OB CC 单独承担)

- ✅ OB CC 已在本会话修了 task md(改 `project_minor: [claudecode]`),已 apply 成功
- ✅ OB CC 会在 SKILL.md 的「apply 前自检清单」加一条「select 字段值必须在飞书白名单」(看你完成后是否加 `--strict-select` 默认启用,再决定 SKILL.md 怎么改 — 等反向回执来再做)
- ✅ OB CC 不动飞书后台选项(那是用户的决策)

## 沟通约定

- 实施中发现 spec 不明的地方:在 handoff 文末「Spec 偏离」section 加记录,继续做最合理的实现
- 发现需要 OB CC 配合的 follow-up:加到 follow-up section,**实施完成后写反向回执**带回 OB
- 完成后请写反向回执 `2026-06-02-sync-py-select字段校验增强-完成回执.md`,告诉 OB CC:版本号 / commit hash / OB 端待办(如改 SKILL.md) / 反测用例结果
- 出问题不要主动改 OB vault(本次纯 sync.py 改造,不该有 OB 端代码改动需求)

## 启动指令(给 feishukanban-ob-sync CC)

1. Read 本 handoff
2. Read sync.py 现有 `best_match_enum` 实现(line 1502-1552)作参考
3. Read sync.py 现有 `build_fields_payload`(grep 一下)确认 select 字段的写入位置
4. Read `~/Documents/CodingProject/feishukanban-ob-sync/config.yaml` 看 select 字段的 field_name 配置
5. 走 brainstorming → 8 条原则自检 → writing-plans → 实施(参考铁律 #3 + 5 阶段插件 SOP 思路,但本次是工具脚本不是插件)
6. 实施过程中保持 cli 失败兜底 + 缓存命中率
7. 测试用例放 `tests/`(如果有的话),没有则在 reverse-receipt 里贴 manual 测试输出

## 完成记录(feishukanban-ob-sync CC 完成后填写)

- 实施完成日:
- 版本号:
- Commit hash:
- 实际耗时:
- 实际改动文件:
- 反测结果:

## Spec 偏离(实施方自主决策点)

- (留空,实施方按需填)

## 状态变更记录

- 2026-06-02 20:00 OB CC 写完 handoff,状态 handoff-pending
