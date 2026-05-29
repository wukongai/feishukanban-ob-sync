---
created: 2026-05-28T14:30:00
status: handoff-pending
from_project: OB(Claudian)
to_project: feishukanban-ob-sync(Claude Code in VS Code)
to_repo: ~/Documents/CodingProject/feishukanban-ob-sync/
spec: 无独立 spec(本 handoff 自包含)
priority: P1
estimated_effort: 1.5-2 小时
tags:
  - handoff
  - task-md
  - sync.py
  - 字段补全
---

# task md 补 5 字段:forward + reverse + 反向建 三处实现

## 一句话需求

OB 端 task md 模板新加了 **5 个飞书字段**(交付 / 用户故事 / 完成质量 / 用时 / 父任务),sync.py 需要同步实现 **forward(OB→飞书)+ reverse(pull-today 飞书→OB)+ _create_task_md_from_feishu_record 反向建** 三处映射,完成 OB ↔ 飞书双向闭环。

## 背景

**用户原话**:"任务 md 中最重要的是最重要的是交付内容"。当前 sync.py 对 task md 的同步存在协同缺口:

| 飞书 task 表字段 | 类型 | OB 模板 | Forward(OB→飞书)| Reverse(pull-today)|
|---|---|---|---|---|
| **交付** | text | ❌ 之前缺(本次加 `## 📦 交付` H2)| ❌ | ❌ |
| **用户故事** | text | ❌ 之前缺(本次加 `## 👥 用户故事` H2)| ❌ | ❌ |
| **完成质量** | select | ❌ 之前缺(本次加 frontmatter `quality`)| ❌ | ❌ |
| **用时** | number | ❌ 之前缺(本次加 frontmatter `actual_hours`)| ❌ | ❌ |
| **父任务** | link | ❌ 之前缺(本次加 frontmatter `parent_task`)| ❌ | ❌ |

OB 端 5 月 28 日已完成的工作:
- ✅ `03 Resources/素材库/模版/task 模版.md` 加 5 字段(2 个 H2 + 3 个 frontmatter)
- ✅ `.claude/rules/base-and-frontmatter.md` task md schema 同步
- ✅ `.claude/rules/feishu-project-sync.md` 1:1 映射表 + 反向同步白名单 audit

**目标**:本 handoff 完成后,OB ↔ 飞书 task 字段双向 1:1 闭环,**飞书侧手编「交付」也能拉回 OB**。

## 目标 / 非目标

### 目标(必须做)

1. **Forward(OB→飞书)**:`push_task_md` 函数(估计在 sync.py 2000+ 行附近,scope 见 `_extract_task_md_for_push` 或类似函数)新增 5 个 OB→飞书 写入:
   - frontmatter `quality` → 飞书「完成质量」(select)
   - frontmatter `actual_hours` → 飞书「用时」(number)
   - frontmatter `parent_task` → 飞书「父任务」(link)— **注意**:OB `parent_task` 值是 `"[[<父 task 文件名>]]"`,需要先解析 → vault 内 find → 拿到该父 task 的 `feishu_record` → 飞书 link 字段需要 record_id 数组。如果父 task 未 sync(无 feishu_record),报警 + 跳过该字段(不阻断主 sync)
   - `## 📦 交付` H2 段正文 → 飞书「交付」(text)
   - `## 👥 用户故事` H2 段正文 → 飞书「用户故事」(text)

2. **Reverse(pull-today 飞书→OB)**:`_REVERSE_SYNC_FIELD_WHITELIST`(sync.py 2497 行附近 `rev_cfg = config["reverse"]["field_to_ob"]`)+ `_extract_fields_from_feishu_row` 函数 + `pull_today_from_feishu` 主逻辑 加:
   - 飞书「完成质量」→ frontmatter `quality`
   - 飞书「用时」→ frontmatter `actual_hours`
   - 飞书「父任务」→ frontmatter `parent_task`(从飞书 link 字段拿到父 record_id → 反查 OB 内 task md 文件 → 拼 wikilink)
   - 飞书「交付」→ task md「## 📦 交付」H2 段(**注意**:这是首次反向同步正文 H2 段,需要新逻辑 — 见下方"接口契约 § 反向 H2 同步策略")
   - 飞书「用户故事」→ task md「## 👥 用户故事」H2 段

3. **反向建 task md**:`_create_task_md_from_feishu_record`(sync.py 3025 行)新建模板加 5 字段:
   - frontmatter 加 `quality: / actual_hours: / parent_task:`(用从飞书拉的实际值,空就空)
   - 正文加 `## 📦 交付` + `## 👥 用户故事` H2 段(用从飞书拉的实际内容,空就空)

4. **config.yaml 同步**:`fields:` 段 + `reverse.field_to_ob:` 段 + (如适用)`reverse.field_to_ob` 的反向白名单 都加 5 字段配置项。**保持开关式设计**:如某字段值为 null 则禁用,方便未来其他用户做 fork 时按需开关。

5. **handoff back**:实施完成后写「完成回执」`2026-05-28-task-md-补5字段-完成回执.md` 到同目录,列实施成果 / 测试结果 / OB 端待办清单(如有)。

### 非目标(明确不做)

- ❌ **不做附件字段**(飞书「附件」attachment type) — 架构复杂,留 P2 backlog。OB 端 `attachments` frontmatter 设计 + 上传/下载 OSS / 飞书文件 token 转换都需要单独 spec。
- ❌ **不做「执行思路」/「相关资料」字段** — OB 端有,但飞书表无对应字段,继续 sync 静默跳过(目前行为已正确,无需改)。
- ❌ **不动其他字段** — 保留现有 9 字段 reverse 白名单 + 7 状态 emoji 对齐表,本次只增量加 5。

## 接口契约

### Forward 字段映射(OB → 飞书)

```yaml
# config.yaml fields: 段新增
delivery:
  field_name: 交付
  source: section_h2  # 新 source 类型:从 H2 段抽
  h2_pattern: "## 📦 交付"

user_story:
  field_name: 用户故事
  source: section_h2
  h2_pattern: "## 👥 用户故事"

quality:
  field_name: 完成质量
  source: frontmatter
  frontmatter_key: quality

actual_hours:
  field_name: 用时
  source: frontmatter
  frontmatter_key: actual_hours
  type: number  # 自动 stringify → number

parent_task:
  field_name: 父任务
  source: frontmatter_wikilink_to_record
  frontmatter_key: parent_task
  # 特殊:wikilink 解析 → vault find → 取 target 文件 feishu_record → 飞书 link 字段
  fallback_on_missing: warn_and_skip
```

### Reverse 字段映射(飞书 → OB)

```yaml
# config.yaml reverse.field_to_ob: 段新增
delivery_field: 交付
user_story_field: 用户故事
quality_field: 完成质量
actual_hours_field: 用时
parent_task_field: 父任务
```

**`_REVERSE_SYNC_FIELD_WHITELIST` 扩展**(sync.py 内常量,或在 `_compute_field_diff` 函数里枚举):

```python
_REVERSE_SYNC_FIELD_WHITELIST = [
    "priority", "status", "category", "subcategory",
    "adhd_priority", "estimate_hours", "due", "done_date",
    "parent_project",
    # === 2026-05-28 新增 ===
    "quality",          # frontmatter
    "actual_hours",     # frontmatter
    "parent_task",      # frontmatter(wikilink form)
    # 正文 H2 段(下方反向 H2 同步策略)
]

# 正文 H2 段需要单独 list(因为不是 frontmatter)
_REVERSE_SYNC_H2_WHITELIST = [
    ("delivery", "## 📦 交付", "交付"),
    ("user_story", "## 👥 用户故事", "用户故事"),
]
```

### 反向 H2 同步策略(新逻辑,本 handoff 重点)

正文 H2 段(交付 / 用户故事)反向同步比 frontmatter 复杂,需要在 task md 文件内做**局部 H2 段替换**。

**算法**(供参考,实施可优化):

```python
def update_h2_section_in_task_md(file_path: Path, h2_title: str, new_content: str) -> bool:
    """
    在 task md 文件内查找 ## <h2_title> 段,把内容替换为 new_content。
    - 如 H2 段存在 → 替换段内容(不动 H2 标题)
    - 如 H2 段不存在 → 在「## ✅ 完成标记」之前插入新 H2 段
    - new_content 是空字符串 → 段内容置空(保留 H2 标题 + HTML 注释)

    Returns: True if 改了文件,False 不变
    """
    text = file_path.read_text(encoding="utf-8")
    # 正则:## <h2_title> 行,捕获到下一个 H2 或文件末尾的内容
    pattern = re.compile(
        rf"^({re.escape(h2_title)})\s*$\r?\n(.*?)(?=\n## |\Z)",
        re.MULTILINE | re.DOTALL
    )
    match = pattern.search(text)
    if match:
        # 段存在 → 替换内容
        new_section = f"{match.group(1)}\n{new_content}\n"
        text_new = pattern.sub(new_section, text)
    else:
        # 段不存在 → 在 ## ✅ 完成标记 之前插入
        insert_marker = "## ✅ 完成标记"
        if insert_marker not in text:
            return False  # task md 不规范,放弃
        new_section = f"\n{h2_title}\n{new_content}\n\n"
        text_new = text.replace(insert_marker, new_section + insert_marker)
    if text_new != text:
        file_path.write_text(text_new, encoding="utf-8")
        return True
    return False
```

**冲突策略**(对齐既有 `_REVERSE_SYNC_FIELD_WHITELIST` 策略):**飞书覆盖 OB**。理由:
- 飞书 app 是 ADHD 实时操作端(用户白天移动办公主用),OB 是文档端
- 用户在飞书 app 改「交付」/ 「用户故事」→ pull-today 应该把内容拉回 OB,而不是反过来
- dry-run 必须显示每个 H2 段 before → after diff,用户审完才 apply

### 父任务 link 双向同步特殊处理

**Forward(OB→飞书)**:
- OB `parent_task: "[[2026-05-20-XXX]]"` 解析 → vault rglob 找 `2026-05-20-XXX.md` → 读 frontmatter 拿 `feishu_record` → 飞书「父任务」link 字段写 `[<feishu_record>]`(link 字段值是数组形式)
- 如父 task 未 sync(无 `feishu_record`)→ warning + 跳过(不阻断主 sync)

**Reverse(飞书→OB)**:
- 飞书「父任务」link 字段返回父 record_id → 反查 OB 端(`_scan_ob_task_md_by_feishu_record` 已建索引)→ 拿到父 task md 文件 → 拼 wikilink `[[2026-05-20-XXX]]`
- 如父 record_id 在 OB 找不到(可能父 task 未被 pull) → frontmatter 写注释 `# parent_task: <record_id> (飞书 record,OB 无对应)`

## 实施任务(分 Phase 勾选清单)

### Phase 1:config.yaml 配置 schema(15 分钟)

- [ ] 给 `fields:` 段加 5 个新字段(delivery / user_story / quality / actual_hours / parent_task),按上方 Forward 字段映射 yaml 格式
- [ ] 给 `reverse.field_to_ob:` 段加 5 个 `*_field` 配置项
- [ ] 给 ROADMAP / CHANGELOG 加新版本号(v0.5.0?)+ 简短描述

### Phase 2:Forward 实现(40 分钟)

- [ ] `push_task_md` 函数(或对应 forward 函数)读 config.yaml 新字段 → 构造 payload
- [ ] `_extract_task_md_for_push` 类似函数加 H2 段抽取(用 `re.search(r"^## 📦 交付\s*$\r?\n(.*?)(?=\n## |\Z)", text, re.M | re.DOTALL)` 模式)
- [ ] `parent_task` 特殊处理:wikilink 解析 + vault find + feishu_record 查找
- [ ] 错误处理:父 task 无 feishu_record 时 warning + 跳过该字段
- [ ] 测试 1 条 task md 端到端 dry-run + apply,验证飞书 record 5 字段都正确

### Phase 3:Reverse(pull-today)实现(40 分钟)

- [ ] `_extract_fields_from_feishu_row` 函数加 5 字段抽取
- [ ] `_REVERSE_SYNC_FIELD_WHITELIST` 扩展 3 frontmatter 字段
- [ ] `_REVERSE_SYNC_H2_WHITELIST` 新加 list,作为 H2 段同步白名单
- [ ] `_compute_field_diff` 函数加 frontmatter 5 字段 diff
- [ ] 新加 `_compute_h2_diff` 函数(或在现有 diff 里加分支),用 `update_h2_section_in_task_md` 实现 H2 段替换
- [ ] dry-run 输出格式扩展:每个 H2 段 before → after 都显示
- [ ] 测试 1 条 task md 端到端:在飞书 app 改「交付」→ pull-today --apply → 验证 OB 端 `## 📦 交付` 段被更新

### Phase 4:反向建 task md 扩展(15 分钟)

- [ ] `_create_task_md_from_feishu_record` 函数模板加:
  - frontmatter `quality: {quality} / actual_hours: {actual_hours} / parent_task: {parent_task_wikilink}`
  - 正文加 `## 📦 交付\n{delivery_text}\n\n## 👥 用户故事\n{user_story_text}\n\n`(空就空段)
- [ ] 测试:飞书侧建一个新 task(写满 5 字段)+ 勾「是否今日」=true → pull-today --apply → OB 端建出新 task md,frontmatter + 正文 H2 段都对应

### Phase 5:文档 + handoff back(20 分钟)

- [ ] `docs/feishu-schema.md` 加 5 新字段说明
- [ ] `docs/VERSION.md` / `docs/ROADMAP.md` 加 v0.5.0 changelog
- [ ] 写完成回执 `2026-05-28-task-md-补5字段-完成回执.md` 到 `docs/handoff/OB对接/`,包含:
  - 实施成果(commit hash / 行数 / 改了哪些文件)
  - 测试结果(Phase 2/3/4 端到端测试通过)
  - OB 端待办清单(如有,例:如果你想批量给历史 task md 补这 5 字段,跑某个 helper 脚本;或刷新 _task.base 视图等)
  - 偏离 spec 的地方(如果你优化了某个设计)

## 验收标准

完成后跑这 5 项自检:

1. ✅ **Forward 端到端**:在 OB 端建一个 task md,写满 5 字段 → 跑 `python3 sync.py --task-md <path> --apply` → 飞书 record 5 字段都正确显示
2. ✅ **Reverse 端到端**:在飞书 app 改某个 task 的 5 字段 → 跑 `python3 sync.py --pull-today --apply` → OB task md 5 字段都被正确更新(frontmatter + 正文 H2 段)
3. ✅ **反向建端到端**:在飞书侧建新 task,勾「是否今日」=true,写满 5 字段 → pull-today --apply → OB 端新建的 task md 模板含 5 字段
4. ✅ **父 task 特殊场景**:OB task A 的 `parent_task: "[[task-B]]"` 但 task-B 未 sync → forward 应该 warning + 不阻断 + 其他 4 字段照常同步
5. ✅ **dry-run 显示完整**:dry-run 输出 H2 段的 before → after diff(用户能审清楚再 apply)

## 不包括(OB CC 单独承担)

OB 端的工作已经全部完成,无需重做:
- ✅ task 模板(03 Resources/素材库/模版/task 模版.md)— 已加 5 字段
- ✅ rules base-and-frontmatter.md task md schema 表 — 已同步
- ✅ rules feishu-project-sync.md 1:1 映射表 — 已同步
- ✅ rules feishu-project-sync.md 反向同步字段范围 audit — 已加

实施完成后,**OB CC 不需要再改任何 OB vault 文件**。仅需在 vault 内验证 5 项端到端测试 + 把完成回执的"OB 端待办清单"(如有)排进 backlog。

## 沟通约定

- ❓ **遇到设计不明** → 在本文件加 `## 实施过程问题` section 留言,OB CC 下次会话来时会读
- ⚠️ **发现 OB 端 bug**(如本 handoff 描述与实际 OB 模板不一致)→ 立刻停 + 写 `## OB 端待修复` section
- 🚀 **完成后** → 写「完成回执」+ 一句话回执给用户带回 OB CC,让 OB CC 走 mem-search 召回 + 端到端验证

## 启动指令(给 feishukanban-ob-sync CC)

1. **第一步**:读 OB 端模板 + rules(确认 schema 一致)
   ```bash
   cat "/Users/aim5/Documents/OB/03 Resources/素材库/模版/task 模版.md"
   sed -n '139,210p' "/Users/aim5/Documents/OB/.claude/rules/base-and-frontmatter.md"
   sed -n '1,45p' "/Users/aim5/Documents/OB/.claude/rules/feishu-project-sync.md"
   ```

2. **第二步**:读 sync.py 关键函数定位(本 handoff 给的 line 编号可能因 sync.py 改动有偏移)
   ```bash
   grep -n "push_task_md\|_extract_task_md_for_push\|_REVERSE_SYNC_FIELD_WHITELIST\|_extract_fields_from_feishu_row\|_create_task_md_from_feishu_record\|_compute_field_diff" sync.py
   ```

3. **第三步**:按 Phase 1-5 实施,每 Phase 完成跑一次单元测试(如有)

4. **第四步**:写完成回执

## 状态变更记录

| 日期 | 状态 | 说明 |
|------|------|------|
| 2026-05-28T14:30 | handoff-pending | OB CC 创建,待 feishukanban-ob-sync CC 接手 |
| 2026-05-28T18:00 | handoff-completed | 实施完成。详见 [2026-05-28-task-md-补5字段-完成回执.md](2026-05-28-task-md-补5字段-完成回执.md) |

## 完成记录

实施 CC 在 v0.5.0 完成了 Phase 1-5。Forward + Reverse + 反向建三处映射全部落地,dry-run 端到端验证通过(forward 5 字段 payload 完整 / parent_task 兜底 warning / reverse 真实场景命中)。**真机 apply 验证留给 OB CC 在自己 vault 跑**(handoff 原 5 项验收测试 #1-3)。详见 [完成回执](2026-05-28-task-md-补5字段-完成回执.md)。
