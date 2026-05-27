---
created: 2026-05-27T20:00:00
status: handoff-pending
from_project: OB(Claudian)
to_project: feishukanban-ob-sync(Claude Code in VS Code)
to_repo: /Users/aim5/Documents/CodingProject/feishukanban-ob-sync/
spec: null
plan: null
priority: P1
estimated_effort: 1
tags:
  - handoff
  - status
  - subdone
  - idea
  - v0.3.5
---

# Handoff: status 字段 SubDone/Idea 双向 sync 支持(v0.3.5)

## 一句话需求

把 `status` 字段从 OB 5 态(todo/doing/done/block/cancel)升级到**完全对齐飞书「执行状态」7 态**(新增 SubDone + Idea),修复 sync.py 反向 sync 时 SubDone 被降级为 doing 的 bug,正向支持 frontmatter.status 直接映射到飞书 enum。

## 背景

### 触发事件

2026-05-27 用户飞书项目看板「执行状态」字段加了 **SubDone** 选项(Orange Lighter),用于"主任务下挂的子任务已完成,主任务本身还没收尾"的场景。截图反馈:"看板上有 subdone,可能 task 的属性中没有同步到"。

### 诊断结果(OB CC 走完 systematic-debugging)

飞书表「执行状态」字段实际有 **7 个选项**(cli 拉的 schema):
```
Doing(Green Darker) / Todo(Gray Light) / SubDone(Orange Lighter)
Done(Gray Darker) / Block(Red Dark) / Idea(Gray Light) / cancel(Blue Lighter)
```

OB 端 sync.py + config.yaml 只承认 5 态(`todo/doing/done/block/cancel`),缺 **subdone/idea**。

具体 bug 定位(4 处):

| # | 位置 | 当前行为 | 问题 |
|---|------|---------|------|
| 1 | `sync.py:2585-2589` `_create_task_md_from_feishu_record` | `"SubDone": "doing", "Idea": "todo"` | 反向 sync 飞书→OB 创建 task md 时,SubDone 被降级 doing,Idea 被降级 todo。frontmatter 完全看不到 subdone/idea 语义 |
| 2 | `sync.py:984-989` `parse_task_md_for_push` status_map | 5 态(todo/doing/done/block/cancel)| 用户在 OB task md frontmatter 写 `status: subdone` → 函数返回 default `" "`(todo)→ 飞书侧也是 Todo,完全丢语义 |
| 3 | `sync.py:1585-1590` `build_fields_payload` + `config.yaml` `fields.status.map` | 基于 inline checkbox 字符(`[ ]/[/]/[x]/[-]`) → 飞书 enum | 4 字符表达不出 7 态,subdone/idea 无法正向同步 |
| 4 | `config.yaml` `reverse.status_map` | 缺 SubDone 键 | `sync.py --pull-today` 反向同步 today 字段时,飞书 SubDone 落到 default `" "`(todo),inline 字符层也丢语义 |

### OB 端用户决策(2026-05-27)

- ✅ **OB 端持有 subdone/idea**,完全对齐飞书看板 7 状态
- ✅ **dataview 渲染从 TASK → LIST + 7 status emoji**(已在 OB vault 内完成,见下方"OB 端已完成清单")
- ✅ **inline checkbox 4 字符保留作为 Tasks 插件 + Cmd+P 完成 task 兼容层**,**不强求 7 态 1:1 inline 字符**(subdone 视觉同 doing,idea 视觉同 todo;frontmatter.status 是真相源)

## 目标

1. **正向**(OB → 飞书):OB frontmatter `status: subdone` / `status: idea` 在 `sync.py --task-md --apply` 时正确映射到飞书 enum `SubDone` / `Idea`
2. **反向**(飞书 → OB):飞书 record「执行状态」= SubDone / Idea 在 `sync.py --pull-today` 时正确写入 OB frontmatter `status: subdone` / `status: idea`(不再降级)
3. **OB 5 个老 status 行为保持不变**(回归测试)

## 非目标(明确不做)

- ❌ **不改 inline checkbox 4 字符语义**(`[ ]/[/]/[x]/[-]`)— Tasks 插件 + Cmd+P「完成 task」UserScript 依赖标准字符,subdone/idea 在 inline 层视觉降级是 acceptable trade-off,**frontmatter.status 是真相源**
- ❌ **不改 journal 模式 inline task 的 status 处理**(老 journal 模式仍按 4 字符映射,不引入 frontmatter.status 概念)
- ❌ **不动 cancel** 状态 — 当前 schema 已有,反向 map 也有(只是 config.yaml 同行有遗漏,顺手补全)
- ❌ **不重构状态映射架构**(不引入"映射策略 driver" pattern,继续用现有 if-else / dict map)

## 接口契约

### OB 端输入(已生效)

OB CC 已经在 vault 内完成以下变更(2026-05-27,可 git pull obsidian-assets 同步):

| 文件 | 变更 |
|------|------|
| `03 Resources/素材库/模版/task 模版.md` | frontmatter `status:` 注释扩展为 7 态:`todo / doing / subdone / done / block / cancel / idea` |
| `03 Resources/素材库/模版/日志模版 5.0 1.md` | 「🎯 今日计划」+「🐿️ 今日非计划」两个 dataview 块从 TASK → LIST + 7 status emoji 渲染(详见下方查询模板) |
| `.claude/rules/base-and-frontmatter.md` | task md schema 注释更新 |
| `.claude/rules/feishu-project-sync.md` | journal dataview 渲染策略 v3 升级 + 7 状态对齐表 + 演进史 |
| `.claude/rules/task-and-habits.md` | task md 渲染描述更新 |
| `journals/2026-05-27.md` | 当天 journal dataview 同步改 |

### 7 状态对齐表(契约真相源)

| OB frontmatter status(小写) | 飞书「执行状态」(PascalCase) | OB dataview 渲染 emoji + 文字 | inline 兼容字符 |
|---|---|---|---|
| `todo` | `Todo` | ⬜ Todo | `[ ]` |
| `doing` | `Doing` | 🔄 Doing | `[/]` |
| `subdone` | `SubDone` | 🟧 SubDone | `[/]`(视觉同 doing,以 frontmatter 为准)|
| `done` | `Done` | ✅ Done | `[x]` |
| `block` | `Block` | 🚧 Block | `[-]`(视觉同 cancel)|
| `cancel` | `cancel` | ❌ cancel | `[-]` |
| `idea` | `Idea` | 💡 Idea | `[ ]`(视觉同 todo)|

⚠️ **特殊**:飞书侧 `cancel` 是**小写**(不是 `Cancel`)— 飞书后台手动建的时候没大写,保留现状(避免触发 SDK 大小写敏感不匹配)。其他 6 个都是 PascalCase。

### Dataview 查询模板(已在 OB 端生效)

```dataview
LIST WITHOUT ID
  choice(status = "todo", "⬜ Todo",
    choice(status = "doing", "🔄 Doing",
      choice(status = "subdone", "🟧 SubDone",
        choice(status = "done", "✅ Done",
          choice(status = "block", "🚧 Block",
            choice(status = "cancel", "❌ cancel",
              choice(status = "idea", "💡 Idea", "❓ Unknown"))))))) + " · " +
  link(file.path, file.name)
FROM "04 Inbox/task"
WHERE !contains(file.name, "_说明")
  AND contains(today_history, this.file.day)
  AND (priority = "P0" OR priority = "P1" OR priority = "P2")
SORT priority ASC, status ASC, created DESC
```

## 实施任务(分 Phase)

### Phase 1:修 sync.py 状态映射(4 处)

#### 1.1 修 `_create_task_md_from_feishu_record` 反向 sync(line ~2585-2589)

**当前**:
```python
status_map = {
    "Todo": "todo", "Doing": "doing", "Done": "done",
    "Block": "block", "SubDone": "doing", "Idea": "todo"
}
status = status_map.get(status_fs, "todo")
```

**改为**:
```python
status_map = {
    "Todo": "todo", "Doing": "doing", "Done": "done",
    "Block": "block", "SubDone": "subdone", "Idea": "idea",
    "cancel": "cancel",  # 补 cancel 映射(原来漏)
}
status = status_map.get(status_fs, "todo")
```

同时同步改注释 docstring(line ~2539):
```
- 执行状态 → status(Todo→todo / Doing→doing / SubDone→subdone / Done→done / Block→block / Idea→idea / cancel→cancel)
```

#### 1.2 修 `parse_task_md_for_push` status_map(line ~984-989)

**当前**:
```python
status_map = {
    "todo": " ", "doing": "/", "done": "x", "block": "-", "cancel": "-",
}
status_str = fm.get("status") or "todo"
status_char = status_map.get(status_str, " ")
```

**改为**:
```python
status_map = {
    "todo": " ", "doing": "/", "subdone": "/",  # subdone 视觉同 doing(inline 兼容层)
    "done": "x", "block": "-", "cancel": "-",
    "idea": " ",  # idea 视觉同 todo
}
status_str = fm.get("status") or "todo"
status_char = status_map.get(status_str, " ")
```

⚠️ **同时把 frontmatter.status 原值带出去**(供 `build_fields_payload` 直接用):

在 task dict 里加一个 `"fm_status": status_str` 字段(line ~1057-1065 返回的 dict 加这一项)。

#### 1.3 修 `build_fields_payload` status 处理(line ~1585-1590)+ `config.yaml` fields.status

**当前 sync.py**:
```python
# 执行状态(单选 wrapped in list,飞书多选字段要 array)
status_cfg = fields_cfg.get("status", {})
if status_cfg:
    mapped = status_cfg["map"].get(f"[{task['status_char']}]")
    if mapped:
        out[status_cfg["field_name"]] = [mapped]
```

**改为(优先 task_md_map 直接 7 态对齐,fallback 老 inline char 映射)**:
```python
# 执行状态(单选 wrapped in list,飞书多选字段要 array)
status_cfg = fields_cfg.get("status", {})
if status_cfg:
    # v0.3.5(2026-05-27):task md 模式优先用 frontmatter.status 直接 7 态映射
    # 避免 inline 4 字符表达不出 subdone/idea
    fm_status = task.get("fm_status")
    if fm_status and "task_md_map" in status_cfg:
        mapped = status_cfg["task_md_map"].get(fm_status)
    else:
        # journal 模式(老接口)继续用 inline char → 飞书 enum 4 态映射
        mapped = status_cfg["map"].get(f"[{task['status_char']}]")
    if mapped:
        out[status_cfg["field_name"]] = [mapped]
```

**`config.yaml` fields.status 加 task_md_map**:
```yaml
status:
  field_name: 执行状态
  # journal 模式(老接口)inline char → 飞书 enum 4 态
  map:
    "[ ]": Todo
    "[/]": Doing
    "[x]": Done
    "[-]": Block
  # 🆕 task md 模式(v0.3.5,2026-05-27)frontmatter.status → 飞书 enum 7 态对齐
  task_md_map:
    todo: Todo
    doing: Doing
    subdone: SubDone
    done: Done
    block: Block
    cancel: cancel       # 飞书侧是小写,保留
    idea: Idea
```

#### 1.4 修 `config.yaml` reverse.status_map(2 处补全)

**当前**(line ~211-217):
```yaml
status_map:
  Done: "x"
  Todo: " "
  Doing: "/"
  Block: "-"
  Idea: " "
  cancel: "-"
```

**改为**(补 SubDone):
```yaml
status_map:
  Done: "x"
  Todo: " "
  Doing: "/"
  SubDone: "/"        # 🆕 v0.3.5:inline 视觉同 doing,frontmatter 端保留 subdone 语义
  Block: "-"
  Idea: " "
  cancel: "-"
```

⚠️ 这只是 inline char 映射(`pull_from_feishu` 写 journal task 行用)。同时确认 `_create_task_md_from_feishu_record`(Phase 1.1)是反向**创建 task md** 的真正接口,frontmatter 写入由那里负责。

### 🆕 Phase 1.5:task md 文件名去日期前缀(2026-05-27 用户追加决策)

**背景**:用户截图反馈"OB 本地 task md 文件名前缀的 `YYYY-MM-DD-` 跟飞书任务标题不一致"。决定**新建 task md 不再加日期前缀**,与飞书任务标题字符级保持一致。

**用户原话(2026-05-27 北京时间晚)**:
> "任务名称放在前面,读取的是飞书名称,本地的名称中不需要前面加日期和飞书保持一致,排序通过 base 不需要用名称来看"

**OB 端已就位**(dataview 兼容历史 task md):
- journal dataview 用 `regexreplace(file.name, "^\d{4}-\d{2}-\d{2}-", "")` 渲染时切日期前缀
- 历史 task md(`2026-05-28-【布丁开发】xxx.md`)和未来 task md(`【布丁开发】xxx.md`)在 dataview 渲染都看不到日期 — 兼容期可以并存

**实施清单**:

#### 1.5.1 改 `_create_task_md_from_feishu_record` 不加日期前缀(sync.py line ~2604-2613)

**当前**(line ~2606):
```python
today_date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

task_dir = vault_root / "04 Inbox" / "task"
task_dir.mkdir(parents=True, exist_ok=True)
fpath = task_dir / f"{today_date}-{safe_title}.md"

if fpath.exists():
    return None
```

**改为**(去掉 today_date 拼接,加重名后缀处理):
```python
task_dir = vault_root / "04 Inbox" / "task"
task_dir.mkdir(parents=True, exist_ok=True)
fpath = task_dir / f"{safe_title}.md"

# 重名处理:加序号后缀(对齐 Obsidian 默认行为)
if fpath.exists():
    # 已存在 → 跳过(不创建重复 task md,避免误覆盖)
    return None
```

⚠️ 注:`today_date` 变量仍要保留(line 2606),后面 `today_history: [{today_date}]` 用得到(line 2635)。只删 `fpath` 拼接里的日期前缀。

#### 1.5.2 QuickAdd Macro v2 创建 task md 不加日期前缀

**位置**:`obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js`

**搜索关键词**:`YYYY-MM-DD-` / `${date}-` / `today_date` 等

**改动**:Macro 创建 task md 时,文件名直接用 `safeTitle.md`,不加 `${dateContext.dateStr}-` 前缀。

⚠️ **保留**:Macro 里其他用 dateContext.dateStr 的地方(`created` / `today_history` frontmatter 字段、journal wikilink 等)**不动**。只动文件名拼接。

#### 1.5.3 影响面评估

- **历史 task md**(已存在的 30+ 文件名带日期前缀):**不重命名**,接受兼容期
- **dataview 渲染**:用 regexreplace 切日期(OB 端已就位,渲染统一)
- **_task.base 视图**:base 视图的"文件名"列显示 file.name(带日期前缀)。用户接受 base 视图带前缀(base 视图本身有 displayName 配置可改,但用户决策不动)
- **wikilink 引用**:vault 内其他笔记如果有 `[[2026-05-28-某 task]]` wikilink,**不变**(老文件仍存在,wikilink 不破)
- **新建 task md 重名风险**:同一标题多次创建 → 第二次 `fpath.exists()` → return None 跳过创建(写 Notice 警告用户)

#### 1.5.4 测试用例(加入 Phase 4)

新增测试:
- 4.6:**反向创建文件名去日期前缀** — 在飞书 app 创建 record「任务标题」=`test-反向-文件名`,跑 `--pull-today --apply` → OB 创建文件应该是 `04 Inbox/task/test-反向-文件名.md`(不带日期前缀)
- 4.7:**QuickAdd Macro v2 创建文件名去日期前缀** — Cmd+P「📝 快记任务 v2」→ 输入标题 → 创建的 task md 文件名应该是 `<标题>.md`(不带日期前缀)
- 4.8:**重名跳过** — 在已有 `test.md` 的情况下再次创建同名 task → 跳过创建 + 给用户警告 Notice

### Phase 2:CHANGELOG.md + ARCHITECTURE.md 更新

#### 2.1 CHANGELOG.md(在最顶部加新 entry)

```markdown
## [v0.3.5] - 2026-05-27 — status 7 态对齐飞书看板(加 SubDone + Idea)

> **背景**:用户飞书项目看板「执行状态」字段加了 SubDone 选项,截图反馈"看板上有 subdone,可能 task 的属性中没有同步到"。OB CC 诊断发现 OB schema 只 5 态,sync.py 4 处映射逻辑都缺 subdone/idea。

### 🐛 修复 4 处映射 bug + 1 处文件名规范

| # | 位置 | 旧行为 | 新行为 |
|---|------|--------|--------|
| 1 | `sync.py:2585` `_create_task_md_from_feishu_record` | SubDone→doing / Idea→todo(降级)| SubDone→subdone / Idea→idea(保留语义)|
| 2 | `sync.py:984` `parse_task_md_for_push` status_map | 缺 subdone/idea | 加 subdone(→`/`)+ idea(→` `) |
| 3 | `sync.py:1585` `build_fields_payload` + config.yaml | 仅 4 字符映射 | 优先 task_md_map(7 态直接) + fallback 老 inline char 映射 |
| 4 | `config.yaml` reverse.status_map | 缺 SubDone | 加 SubDone→`/` |
| 5 | **`sync.py:2606` 文件名拼接 + `Macro v2` userscript** | task md 文件名 `YYYY-MM-DD-<title>.md` | 去日期前缀:`<title>.md`(对齐飞书任务标题)|

### 🔗 OB 端配套(handoff 同步)

- task 模板 frontmatter `status` 注释 7 态
- journal 模板 dataview 从 TASK → LIST + 3 字段(任务标题去日期 / 飞书看板链接 / 本地链接)
- rules 3 处更新(base-and-frontmatter / feishu-project-sync / task-and-habits)
- dataview `regexreplace(file.name, "^\d{4}-\d{2}-\d{2}-", "")` 兼容历史带日期前缀的 task md

### 📝 改动文件

- `sync.py`(4 处)
- `config.yaml`(2 处:fields.status.task_md_map + reverse.status_map.SubDone)
- `docs/ARCHITECTURE.md`(status 映射 section)

### ⚠️ 注意

inline checkbox 4 字符**不变**(`[ ]/[/]/[x]/[-]`)。subdone 视觉同 doing,idea 视觉同 todo,**frontmatter.status 是真相源**。
```

#### 2.2 ARCHITECTURE.md(如有 status 映射 section 同步更新)

`grep -n "status" docs/ARCHITECTURE.md` 看是否有 status 映射的描述,若有,加一段 7 态对齐说明。

### Phase 3:版本号 bump

`grep -rn 'v0.3.4\|version' --include="*.py" --include="*.yaml" --include="*.json" --include="*.sh"` 找版本号位置,bump 到 `v0.3.5`。

### Phase 4:本地测试(用户配合)

**4.1 正向 OB → 飞书(subdone)**

1. 在 OB vault 新建 task md `04 Inbox/task/2026-05-27-test-subdone.md`
2. frontmatter:`status: subdone`,priority: P3,today: false
3. 跑 `python3 sync.py --task-md "04 Inbox/task/2026-05-27-test-subdone.md"`(dry-run)
4. dry-run 预览:`执行状态: ["SubDone"]` ✅
5. 加 `--apply` 真实写入
6. 用户在飞书 app 看 record 「执行状态」= SubDone ✅
7. 测完删 test record + 删 OB task md

**4.2 正向 OB → 飞书(idea)** — 同上,frontmatter `status: idea`,验证飞书侧 Idea

**4.3 反向 飞书 → OB(SubDone)**

1. 用户在飞书 app 创建 record「任务标题」=`test-反向-subdone`,「执行状态」=SubDone,「是否今日」=true
2. 跑 `python3 sync.py --pull-today`(dry-run)
3. dry-run 预览:即将创建 `04 Inbox/task/2026-05-27-test-反向-subdone.md`,frontmatter `status: subdone` ✅
4. 加 `--apply` 真实写
5. OB vault 看 task md `status: subdone` ✅
6. 测完删

**4.4 反向 飞书 → OB(Idea)** — 同上

**4.5 回归测试**(确保不破坏 5 老态)

各跑一遍 todo / doing / done / block / cancel 正反向,确认行为不变。

### Phase 5:git commit + tag(不 push,留给用户)

参考 2026-05-27 v0.3.4 跨边界例外的 commit message 格式:

```bash
git add -A
git commit -m "$(cat <<'EOF'
feat(v0.3.5): status 7 态对齐飞书看板(加 SubDone + Idea)

修 sync.py 4 处映射 bug:
1. _create_task_md_from_feishu_record:SubDone/Idea 不再降级
2. parse_task_md_for_push status_map:加 subdone(→/) + idea(→空)
3. build_fields_payload + config.yaml:加 task_md_map 7 态直接映射
4. config.yaml reverse.status_map:加 SubDone

配套 OB 端已就位(详见 docs/handoff/OB对接/2026-05-27-status-subdone-idea-handoff.md):
- task 模板 frontmatter 7 态
- journal 模板 dataview TASK → LIST + 7 status emoji
- rules 3 处更新

inline checkbox 4 字符不变,frontmatter.status 是真相源。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

git tag v0.3.5
```

**不要** `git push`(留给用户跑 `git push all main && git push all v0.3.5` 双推 GitHub + Gitee)。

## 验收标准

实施完成后,目标 CC 自检:

- [ ] Phase 1:4 处代码改动完成,本地 grep `SubDone\|subdone\|Idea\|idea` 在 sync.py + config.yaml 看到完整一致
- [ ] Phase 2:CHANGELOG.md 新 entry v0.3.5;ARCHITECTURE.md 如有 status section 同步
- [ ] Phase 3:版本号 bump v0.3.5(全局 grep 找位置)
- [ ] Phase 4:5 项本地测试全过(4.1-4.5),用户确认 OB vault 看到正确 frontmatter + 飞书看板看到正确 enum
- [ ] Phase 5:git commit + tag v0.3.5,未 push(等用户 review)
- [ ] 反向回执:在 docs/handoff/OB对接/ 写 `2026-05-27-status-subdone-idea-反向回执.md`(完成记录 + 任何 OB 端 follow-up)

## 不包括(OB CC 单独承担)

- ✅ task 模板 frontmatter 注释(已完成)
- ✅ journal 模板 dataview LIST + 7 emoji(已完成)
- ✅ 当天 journal `2026-05-27.md` 同步改(已完成)
- ✅ rules 3 处更新(已完成)

## 沟通约定

- **设计不明 / 实施中浮现问题** → 写到反向回执的「Spec 偏离」/「Follow-up」section,等 OB CC 异议反馈
- **不要主动改 OB vault**(`/Users/aim5/Documents/OB/` 不可写)— 任何 OB 端待补充事项写到反向回执,OB CC 自己做
- **测试期间发现 frontmatter 7 态写入但飞书没接收** → 第一刀检查 `config.yaml` task_md_map 拼写;第二刀检查 `task.get("fm_status")` 是否真带过来了
- **测试期间发现飞书写入但 OB schema 漏值** → 检查 `_create_task_md_from_feishu_record` status_map(Phase 1.1)是否补全

## 启动指令

1. **读完本 handoff** 所有章节
2. **跑 startup 3 项核对**:
   - mem-search 看是否有类似的 status 映射 handoff 历史
   - 看 sync.py 当前实际代码,确认 line 号没变(因为 v0.3.4 已上线,可能 line 偏移)
   - Read `docs/handoff/OB对接/2026-05-26-v0.3.1-反向回执-OB端落地.md` 了解上次反向 sync 的实施风格
3. **从 Phase 1.1 开始按顺序实施**,每个 Phase 完成后简短自评
4. **Phase 4 测试前**告诉用户准备好"在飞书 app 创建一条 SubDone test record",别自己手动 mock 数据

## 完成记录(目标工程 CC 完成后填写)

待填:
- 实际耗时:
- 实际修改的代码行号:
- 偏离点(如有):
- Follow-up(如有):

## 状态变更记录

- 2026-05-27 20:00 北京 — OB CC 创建 handoff,status: handoff-pending
