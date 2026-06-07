---
created: 2026-06-07
status: in-progress
target_version: v0.9.0
handoff: docs/handoff/OB对接/2026-06-07-OB-CC手工创建task-md缺Macro-v2等效路径-handoff.md
tags:
  - design
  - schema
  - validate-task-md
  - macro-v2-parity
---

# task md schema 真相源固化 + --validate-task-md + --create-task titlePrefix 对齐 Macro v2

## 背景

OB CC 用 sync.py 路径手工建 task md 时,**与 Macro v2(QuickAdd UserScript)输出不等效**,具体漂移:

- 文件名缺「【父项目】」前缀 → 与 vault 其他 task 视觉不齐
- H1 缺前缀 → 飞书侧任务标题缺前缀
- subcategory/project_minor 误填 → 触发 select 字段 warning
- today_history/today_source_history 半残

根因:schema 真相源散布 4 处(parse_task_md / _build_task_md_content_from_params / Macro v2 / task-template.md),没单一真相源 + 没校验工具兜底。

## 设计目标

1. **schema 真相源固化**:sync.py 顶部加 `TaskMdSchema` dataclass(决策:不抽独立模块,sync.py 单文件设计)
2. **`--validate-task-md`**:校验 task md frontmatter / 文件名 / H1 / today_history lockstep / select 白名单,带 `--apply` 机械修复
3. **`--create-task` 补 titlePrefix**:`parent_project` 非空 → 文件名/H1 自动加「【最终归属】」前缀,与 Macro v2 等效(决策:复用现有 CLI,不新增 `--create-task-md`)

## 非目标

- 不改 Macro v2 行为(主入口仍为用户日常用)
- 不抽 `lib/task_md_schema.py`(sync.py 单文件原则)
- 不重构 `parse_task_md` 解析逻辑(只加 schema 引用)
- 不动 OB vault `rules/`(铁律 #2 — 反向回执让 OB CC 自己改)

## Phase 1:schema 真相源固化

### TaskMdSchema dataclass(放 sync.py 约 line 70 `load_config` 上方)

```python
@dataclass(frozen=True)
class TaskMdField:
    """task md frontmatter 单字段定义"""
    name: str                          # 字段名(yaml key)
    required: bool = False             # 是否必填(缺 → validate 报 error)
    type: str = "str"                  # str / bool / int / float / list / wikilink / date / iso_datetime
    enum: Optional[tuple] = None       # 枚举值白名单(None 表示非枚举)
    default_empty: str = ""            # 模板空值渲染(如 "[]" / "" / "false")
    sync_to_feishu: bool = True        # 是否推飞书(OB-only 字段如 today_source_history 设 False)
    feishu_select: bool = False        # 是否走飞书 select 字段(配合 validate_select_value)
    note: str = ""                     # 字段说明(给 validate 报告用)


TASK_MD_SCHEMA: tuple[TaskMdField, ...] = (
    TaskMdField("priority", required=False, type="str",
                enum=("P0", "P1", "P2", "P3"), feishu_select=True,
                note="价值优先级(纯价值维度,不含时间)"),
    TaskMdField("status", required=True, type="str",
                enum=("todo", "doing", "subdone", "done", "block", "cancel", "idea"),
                default_empty="todo", feishu_select=True),
    TaskMdField("today", required=True, type="bool", default_empty="false"),
    TaskMdField("today_history", required=True, type="list", default_empty="[]",
                note="今日历史(每次进 today 追加一日);与 today_source_history 长度一致 lockstep"),
    TaskMdField("today_source", required=False, type="str",
                enum=("planned", "unplanned"), sync_to_feishu=False),
    TaskMdField("today_source_history", required=True, type="list", default_empty="[]",
                sync_to_feishu=False,
                note="与 today_history 一一对应,OB-only(不同步飞书)"),
    TaskMdField("created", required=True, type="iso_datetime",
                note="ISO 8601 北京时间;无引号"),
    TaskMdField("due", required=False, type="date"),
    TaskMdField("done_date", required=False, type="date"),
    TaskMdField("category", required=False, type="str", feishu_select=True,
                enum=("产品项目", "杂务", "技能工具", "领域学习")),
    TaskMdField("subcategory", required=False, type="list", feishu_select=True,
                note="非产品项目分支用(杂务/技能工具/领域学习);产品项目分支应空"),
    TaskMdField("project_minor", required=False, type="list", feishu_select=True,
                note="产品项目分支三级分类(白名单见飞书);非产品项目分支应空"),
    TaskMdField("adhd_priority", required=False, type="str",
                enum=("待抢救", "有 DDL", "自由待办"), feishu_select=True),
    TaskMdField("estimate_hours", required=False, type="float"),
    TaskMdField("actual_hours", required=False, type="float"),
    TaskMdField("efficiency", required=False, type="str",
                enum=("高", "中", "低"), feishu_select=True),
    TaskMdField("quality", required=False, type="str",
                enum=("高", "中", "低"), feishu_select=True),
    TaskMdField("parent_project", required=False, type="wikilink",
                note="最终归属项目(选小类用小类名,否则大类名);非空 → 文件名/H1 加「【<名>】」前缀"),
    TaskMdField("parent_subproject", required=False, type="wikilink",
                sync_to_feishu=False, note="OB-only,不推飞书"),
    TaskMdField("parent_task", required=False, type="wikilink"),
    TaskMdField("parent_inspiration", required=False, type="wikilink"),
    TaskMdField("日志", required=True, type="wikilink",
                note="形如 [[journals/YYYY-MM-DD]]"),
    TaskMdField("feishu_record", required=False, type="str",
                note="CREATE 后由 sync.py 回填,人不手改"),
    TaskMdField("feishu_url", required=False, type="str",
                note="CREATE 后由 sync.py 回填,人不手改"),
    TaskMdField("iteration_week", required=False, type="list"),
    TaskMdField("iteration_month", required=False, type="list"),
    TaskMdField("completion_month", required=False, type="str",
                note="完成时自动算"),
    TaskMdField("tags", required=True, type="list", default_empty="[task]"),
)


def task_md_schema_field(name: str) -> Optional[TaskMdField]:
    """按 name 取 schema 单字段(O(n) 查找,字段少不在乎)"""
    for f in TASK_MD_SCHEMA:
        if f.name == name:
            return f
    return None
```

### parse_task_md 改造(最小侵入)

- 不动现有 `parse_task_md` 返回的 dict 结构(保 caller 兼容)
- 但**校验逻辑放 `validate_task_md`**,parse 保持容错

### 单元测试

- 用 Macro v2 真实产出的 vault 内 task md(取 3-5 个有代表性的)跑 `validate_task_md` → 应全部通过

## Phase 2:`--validate-task-md` CLI

### 入口

```bash
python3 sync.py --vault /OB --validate-task-md "04 Inbox/task/xxx.md"            # dry-run 报告
python3 sync.py --vault /OB --validate-task-md "04 Inbox/task/xxx.md" --apply    # 机械修复
```

### `validate_task_md(path: Path, apply: bool) -> ValidationReport` 函数

校验维度:
1. **frontmatter 必填字段存在**(priority/status/today/today_history/created/日志/tags)
2. **enum 字段值在白名单**(走 schema TaskMdField.enum)
3. **wikilink 字段格式正确**(parent_project/parent_task 等)
4. **文件名前缀对齐 parent_project**:
   - parent_project 非空 → 文件名应是 `YYYY-MM-DD-【<最终归属>】<title>.md`
   - parent_project 空 → 文件名应是 `YYYY-MM-DD-<title>.md`(无前缀)
5. **H1 对齐文件名**:`# {filename 去日期前缀}.md` 必须匹配
6. **today_history lockstep**:`len(today_history) == len(today_source_history)`(与 today=true 状态对齐)
7. **select 字段值在飞书白名单**(复用 `validate_select_value`)

### 报告格式

```
🔍 校验 task md:04 Inbox/task/2026-06-07-xxx.md
  ✅ frontmatter 必填字段:全部存在
  ❌ 文件名缺「【AiCoding实践】」前缀
     parent_project = "[[AiCoding实践]]"
     当前:2026-06-07-优化系统提示词.md
     期望:2026-06-07-【AiCoding实践】优化系统提示词.md
     修复:--apply(自动 mv 文件 + 改 H1)
  ⚠️  subcategory 误填 ["AIcoding实践"](应为空)
     原因:产品项目分支不使用 subcategory(走 parent_project)
     修复:--apply(自动清空)
  ✅ today_history/source_history lockstep 对齐

总计:2 error / 0 warn / 4 pass
```

### `--apply` 机械修复行为

- 文件名前缀缺失 → `mv` 文件(用 `Path.rename`)+ 同步改 H1 + 改完成标记行
- subcategory/project_minor 非法值 → 清空对应 frontmatter 行
- today_history/source_history lockstep 不对齐 → 复用 `_normalize_today_history_lockstep` 或新写

### 退出码

- 全 pass + 无 warn → exit 0
- 有 warn 无 error → exit 0(警告)
- 有 error 且未 `--apply` → exit 1
- 有 error 已 `--apply` → 修复后再校验,全 pass exit 0,否则 exit 1

## Phase 3:`--create-task` 补 titlePrefix

### 改 `_build_task_md_content_from_params`

加 helper:

```python
def _compute_title_prefix(parent_project: str, category: str, subcategory_list: list) -> str:
    """对齐 Macro v2 titlePrefix 逻辑:
    - parent_project 非空(产品项目分支,最终归属)→ 【<parent_project>】
    - 否则若 category 非空且有 subcategory_list → 【<category>-<sub1>-<sub2>】
    - 否则若仅 category 非空 → 【<category>】
    - 否则 → ""(无前缀)
    """
    pp = parent_project.strip().lstrip("[").rstrip("]").strip()  # 容 [[X]] / X
    if pp:
        return f"【{pp}】"
    if category and subcategory_list:
        return f"【{category}-{'-'.join(subcategory_list)}】"
    if category:
        return f"【{category}】"
    return ""
```

### 改 `create_task_from_params`

- 当前:`target_path = vault_root / "04 Inbox" / "task" / f"{today_date}-{safe_title}.md"`
- 改为:`target_path = vault_root / "04 Inbox" / "task" / f"{today_date}-{title_prefix}{safe_title}.md"`
- `title_prefix` 走 `_compute_title_prefix(args.parent_project, args.category, args.subcategory or [])`

### 改 _build_task_md_content_from_params 内 H1 生成

- 当前:`f"# {title}"`
- 改为:`f"# {title_prefix}{title}"`

### 兼容性

- 旧调用未传 `--parent-project` → title_prefix = ""(无前缀,与现状一致 ✅)
- 旧调用传 `--parent-project` 但 zhixing-game 等老 SOP 没期望前缀:需要加 flag 兜底?**评估:旧调用如果传 parent_project,意图就是"归类到该项目",有前缀更合理。无需兼容 flag**。如出问题再加 `--no-title-prefix` 退出口。

### 新增 CLI flag 支持

- `--subcategory <s>` flag(可重复)— 接住非产品项目分支的 subcategory_list,供 titlePrefix 拼接 + frontmatter 写入

## Phase 4:反向回执 + bump 版本

### 反向回执文件

`docs/handoff/OB对接/2026-06-07-OB-CC手工创建task-md缺Macro-v2等效路径-反向回执.md`

包含内容:
- 实施实际状况(等价方案:`--create-task` 补 titlePrefix,不新增 `--create-task-md`)
- commit hash + 测试结果
- OB 端 follow-up 清单:
  - `rules/base-and-frontmatter.md` task md schema section 重写,**链接到 sync.py 顶部 `TASK_MD_SCHEMA` 定义**
  - `rules/feishu-project-sync.md` 加铁律:OB CC 手工创建/同步 task md 前先跑 `python3 sync.py --vault /OB --validate-task-md "<path>"`,通过后再继续
  - 提示用户在 OB CC 内执行,**不主动改 vault**

### 版本号

- v0.8.5 → **v0.9.0**(minor bump,新增 CLI + schema 真相源)
- CHANGELOG 加 section
- README badge 更新

## 验收标准

- [ ] Macro v2 产出的真实 task md(取 3-5 个 vault 内文件)跑 `--validate-task-md` → 全 pass
- [ ] 本次事故的"OB CC 手写第 1 版"模拟样本(可在测试时 mock) → 报出缺前缀 / subcategory 误填等
- [ ] `--create-task --parent-project "AiCoding实践" --title "测试" --priority P2 --apply` → 产出 `2026-06-07-【AiCoding实践】测试.md`(diff 与 Macro v2 等效输出无差异)
- [ ] 飞书侧 CREATE 后任务标题正确含「【AiCoding实践】」前缀
- [ ] sync.py 顶部存在 `TASK_MD_SCHEMA` dataclass tuple

## 偏离 handoff 的地方(记录)

| handoff 期望 | 实际方案 | 理由 |
|------|------|------|
| 新增 `--create-task-md` | 复用 `--create-task` 补 titlePrefix | 已有 `--create-task` v0.7.0+,等价能力,避免双 CLI 维护负担(用户拍板) |
| 抽 `lib/task_md_schema.py` 模块 | sync.py 顶部 dataclass | sync.py 单文件设计原则(用户拍板) |
| 各种 `--fix-prefix` / `--fix-subcategory` 子 flag | 统一 `--apply` 自动跑所有机械修复 | 减小 CLI surface;每条 error 在报告里写"修复方式" |

## 实施顺序

1. Phase 1 dataclass(~30 分钟)
2. Phase 3 titlePrefix(~30 分钟)— 先做,因为 Phase 2 validate 依赖 titlePrefix 规则
3. Phase 2 validate(~60-90 分钟)
4. 真机验收(~30 分钟)— 在用户 vault 上跑
5. Phase 4 反向回执 + bump(~30 分钟)
