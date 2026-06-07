---
created: 2026-06-07T10:30:00
status: handoff-pending
from_project: OB(Claudian)
to_project: feishukanban-ob-sync(Claude Code in VS Code)
to_repo: ~/Documents/CodingProject/feishukanban-ob-sync
priority: P1
estimated_effort: 3
tags:
  - handoff
  - task-md-schema
  - macro-v2-parity
  - ob-cc-pain-point
---

# OB CC 手工创建 task md 缺 Macro v2 等效路径 + frontmatter schema 不一致

## 一句话需求

OB Claudian 通过 `python3 sync.py --task-md <path> --apply` 路径创建/同步 task md 时,**没有等效的 Macro v2(QuickAdd UserScript)校验链路**,导致 task md 文件命名、frontmatter schema、与飞书联动的字段映射全部漂移,需求池/今日计划段渲染异常 + 飞书任务标题缺前缀。建议 sync.py 增加 `--validate-task-md` / `--create-task-md` CLI,并把 schema 真相源固化到 sync.py 内部(供 OB CC 调用 / rules 文档反向引用)。

## 背景

### 本次事故复盘(2026-06-07)

OB Claudian 帮用户创建一条 P0 task「优化 OB CLAUDE.md 系统提示词,实现渐进式读取」进需求池。**全流程 4 轮迭代才修对**:

| 轮次 | 错误 | 真因 |
|------|------|------|
| 1 | 文件名 `2026-06-06-...md`(应 `2026-06-07-...md`)+ `created` 用 PDT 时间 | OB CC 用 `currentDate`(Mac PDT),没换算北京时间 |
| 2 | 用户截图反馈 6-07 journal 看不到 | OB CC 把 `today: false` + 无 `today_history`,journal 完全不渲染 |
| 3 | OB CC 改 `today: true` 想让今日计划段显示 | **从需求池消失 → 进了今日计划段**(用户原意是需求池) |
| 4 | 用户截图显示其他 task 都有「【小类】」前缀,本条没有 | 真因:Macro v2 自动从 `parent_project` 字段拼前缀到文件名 + H1,OB CC 手工 Write 时**完全不知道这套规则**(rules 文档里没写,sync.py 也没校验) |

### schema 漂移实证

OB CC 参照 `OB/.claude/rules/base-and-frontmatter.md` 「task md frontmatter schema」section 写出的 frontmatter,**与 Macro v2 实际产出的差异**:

| 字段 | Macro v2 真实输出 | rules 文档写法 | OB CC 写错 |
|------|-----------------|--------------|-----------|
| `parent_project` | `"[[AiCoding实践]]"`(wikilink → 项目池) | **未列出此字段** | 没写 |
| `subcategory` | **空**(不填) | 列出该字段 + 说明用于飞书「小类」 | 误填 `[AIcoding实践]`(I 大写错,真实为 AiCoding) |
| `project_minor` | **空**(不填) | 列出该字段 + 说明用于飞书「项目小类」 | 误填 `[系统提示词优化]`(不在白名单) |
| `today_history` | `[]`(空数组) | 提到该字段但没说默认值 | 写成 `["2026-06-07"]` |
| `today_source_history` | `[]`(空数组) | **未列出此字段** | 没写 |
| `due / done_date / actual_hours / efficiency / quality / parent_subproject / parent_task / parent_inspiration` | 全部存在(空占位) | 部分列出 | 没写(漏掉) |
| 文件名 + H1 「【父项目】」前缀 | Macro v2 从 `parent_project` 自动拼 | **完全未提及** | 没加 |

### 影响范围

1. **journal 渲染不一致**:OB CC 创建的 task 在「🗂️ 今日需求池」段缺命名前缀,与 Macro v2 创建的 task 视觉上不齐(用户截图反馈)
2. **飞书任务标题不一致**:同上,飞书项目看板上看不出"这条是 AiCoding 实践分类"
3. **OB CC 触发 select 字段 warning**:`小类` / `项目小类` 字段误填非白名单值,sync.py 跳过这两字段
4. **rules 文档误导**:rules 文档把 `subcategory` / `project_minor` 描述为"应该填的字段",实际 Macro v2 是空——文档真相源跟不上代码迭代
5. **多轮 token 浪费**:OB CC 4 轮迭代才修对,本次会话 system prompt 已爆 200K context(详情见 OB 内 task 正文「## 💡 执行思路」),Agent 工具不可用,排障成本翻倍

## 目标 / 非目标

### 目标(必须做)

1. **schema 真相源固化到 sync.py**:把 Macro v2 输出的 task md frontmatter schema 写成 sync.py 内部常量 / dataclass,供 `--validate-task-md` / `--create-task-md` 复用
2. **CLI 校验工具 `--validate-task-md <path>`**:OB CC 写完 task md 后跑一次,sync.py 报"缺哪些字段 / 哪些字段值不对 / 文件名前缀是否对应 parent_project / H1 是否对应 parent_project"
3. **CLI 创建工具 `--create-task-md`**:接受 `--parent-project <P> --title <T> --priority <P0|P1|P2|P3> --today-source <planned|unplanned>`(可加更多 flag),产出等效于 Macro v2 的 task md 文件(文件名拼前缀 + H1 拼前缀 + frontmatter 全占位 + 自动 sync 飞书)
4. **更新 rules 文档**:OB 端 `rules/base-and-frontmatter.md` 的 task md schema section 重写,**链接到 sync.py 的 schema 真相源**(不再单独维护一份)

### 非目标(明确不做)

- ❌ 不替换 Macro v2:Macro v2 在 Obsidian 内仍是用户主入口,不动
- ❌ 不改 OB vault 内 base 文件:`_task.base` 不改字段
- ❌ 不强制 OB CC 走新 CLI:旧的 `--task-md <path>` 仍可用(向后兼容,只是 OB CC 自己要保证 frontmatter 正确)

## 接口契约

### 输入(OB 给的)

- task md 文件路径(已存在 / 即将创建)
- 或 CLI flags(`--parent-project` / `--title` / `--priority` / `--today-source` / `--category` / `--adhd-priority` / `--estimate-hours` / `--due`)

### 输出(feishukanban-ob-sync 要交付的)

**A. `sync.py --validate-task-md <path>`**

输出 markdown 友好的报告,例:

```
🔍 校验 task md schema:/path/to/2026-06-07-xxx.md
  ✅ frontmatter 必填字段:全部存在
  ⚠️  文件名缺「【父项目】」前缀
     parent_project = "[[AiCoding实践]]"
     当前文件名:2026-06-07-优化系统提示词渐进式读取.md
     期望文件名:2026-06-07-【AiCoding实践】优化系统提示词渐进式读取.md
     修复:--fix-prefix(自动 mv 文件 + 改 H1)
  ⚠️  subcategory 误填非空值 `["AIcoding实践"]`
     Macro v2 schema:subcategory 应为空(分类靠 parent_project)
     修复:--fix-subcategory(自动清空)
  ✅ today_history 字段正常
```

`--apply` flag 自动修复所有可机械修复的项。

**B. `sync.py --create-task-md ...`**

接受 CLI flags,产出文件 + sync 飞书 + 回写 record。等效于:

```bash
python3 sync.py --create-task-md \
    --parent-project "AiCoding实践" \
    --title "优化 OB CLAUDE.md 系统提示词,实现渐进式读取" \
    --priority P0 \
    --today-source planned \
    --category "技能工具" \
    --adhd-priority "自由待办" \
    --estimate-hours 4
```

→ 自动产生:
- 文件:`04 Inbox/task/2026-06-07-【AiCoding实践】优化 OB CLAUDE.md 系统提示词,实现渐进式读取.md`
- frontmatter:完整占位 + Macro v2 schema 对齐
- H1:`# 【AiCoding实践】优化 OB CLAUDE.md 系统提示词,实现渐进式读取`
- 正文:H2 段占位(## 📝 执行概述 / ## ✅ 验收条件 / ## 💡 执行思路 / ## 📦 交付 / ## 🪞 复盘 / ## ✅ 完成标记)
- 自动 sync 飞书 + 回写 record_id

**C. schema 真相源(供 OB 端文档反向引用)**

在 sync.py 或独立模块定义 dataclass / TypedDict,文档生成器可以从代码生成 schema 表给 rules 文档引用。例:

```python
@dataclass
class TaskMdSchema:
    """task md frontmatter schema(与 Macro v2 等效)"""
    priority: Literal["P0","P1","P2","P3"]
    status: Literal["todo","doing","subdone","done","block","cancel","idea"]
    today: bool
    today_history: list[str]  # 默认 []
    today_source: Optional[Literal["planned","unplanned"]]
    today_source_history: list[str]  # 默认 []
    parent_project: Optional[str]  # wikilink: "[[XXX]]";空则文件名 / H1 无前缀
    subcategory: Optional[list[str]]  # 通常为空,飞书「小类」select
    # ... 其他字段
```

### 错误处理契约

- `--validate-task-md` 校验失败 → exit 1 + 报告 stderr
- `--create-task-md` 同名文件已存在 → exit 1 + 提示用 `--task-md` UPDATE 路径
- 校验通过但用户没用 `--apply` → 只打印报告 exit 0(参考 dry-run 模式)

## 实施任务

### Phase 1:schema 真相源固化

- [ ] 在 `sync.py` 或新建 `lib/task_md_schema.py` 定义 dataclass / TypedDict
- [ ] 把现有 `parse_task_md` 改成用 schema 校验输入(失败时报具体字段)
- [ ] 写单元测试:Macro v2 真实产出的 task md 全部能 parse 通过

### Phase 2:`--validate-task-md` CLI

- [ ] argparse 加 `--validate-task-md <path>` + `--apply`(配合 --fix-* 子 flag)
- [ ] 实现 `validate_task_md(path) -> ValidationReport` 函数
- [ ] 实现 `--fix-prefix` / `--fix-subcategory` / `--fix-today-history` 等机械修复
- [ ] 加文档到 README

### Phase 3:`--create-task-md` CLI

- [ ] argparse 加 `--create-task-md` + CLI flags
- [ ] 实现 `create_task_md(args) -> Path` 函数:文件名拼接 / H1 拼接 / frontmatter 占位 / 写盘
- [ ] 自动接力跑现有 `push_task_md` push 飞书
- [ ] 单元测试 + 集成测试(对比与 Macro v2 输出 diff 应为空)

### Phase 4:rules 文档更新(handoff 给 OB 项目)

- [ ] 写一份反向回执,提示 OB 端把 `rules/base-and-frontmatter.md` 的 task md schema section 重写,**链接到 sync.py 的 schema 真相源**(可以是 GitHub permalink 到 dataclass 定义)
- [ ] 反向回执提到要在 OB 内 `rules/cc-config.md` 或 `rules/feishu-project-sync.md` 加铁律:**OB CC 创建/同步 task md 必须先跑 `--validate-task-md`,通过后再继续**

## 验收标准

- [ ] OB CC 跑 `python3 sync.py --validate-task-md <Macro v2 产出的任意 task md>` → "全部校验通过"
- [ ] OB CC 跑 `python3 sync.py --validate-task-md <本次事故的 OB CC 手写 task md 第 1 版>` → 报出"缺前缀 / subcategory 误填 / 缺 parent_project"等问题
- [ ] OB CC 跑 `python3 sync.py --create-task-md --parent-project "AiCoding实践" --title "测试" --priority P2` → 产出与 Macro v2 等效的 task md(diff 工具对比无差异)
- [ ] 飞书侧 CREATE 后任务标题正确含「【AiCoding实践】」前缀
- [ ] sync.py 内或独立模块有 schema dataclass,作为文档真相源

## 不包括(OB CC 单独承担)

- OB 端 `rules/base-and-frontmatter.md` schema section 重写(等到反向回执到 OB)
- 本次事故的 task md 已经手工修复(`2026-06-07-【AiCoding实践】优化 OB CLAUDE.md 系统提示词,实现渐进式读取.md` 已 sync OK,无需 feishukanban-ob-sync 处理)
- 用户当前还在用 Macro v2 主流程,不需要他改任何习惯

## 沟通约定

- 实施前如有设计偏离 / 替代方案 → 写反向回执到本目录 + 用户带回 OB CC 决策
- 完成后写「2026-06-07-OB-CC手工创建task-md缺Macro-v2等效路径-反向回执.md」,列出 commit hash + 测试结果 + OB 端 follow-up 清单
- **不要主动改 OB vault**(铁律 #2 跨工程边界)

## 启动指令(给 feishukanban-ob-sync CC)

第一步:
1. 读这份 handoff
2. 读现有 `sync.py` 的 `parse_task_md` / `push_task_md` / `_create_task_md`(如果存在 reverse sync 路径)弄清现状
3. 读 `obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js` 弄清 Macro v2 真实命名 + frontmatter 规则
4. 写 spec / plan(可直接在 `docs/specs/` 落档)
5. 实施 Phase 1 → 2 → 3
6. 跑测试 + 写反向回执

## 完成记录(feishukanban-ob-sync CC 完成后填写)

> 实际耗时:_
> 偏离 spec 的地方:_
> 测试结果:_
> commit hash:_
> 反向回执文件:_

## 状态变更记录

- 2026-06-07 10:30 OB CC 创建,status=handoff-pending
