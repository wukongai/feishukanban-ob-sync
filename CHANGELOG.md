# Changelog

> `feishukanban-ob-sync` — Obsidian ↔ 飞书项目管理多维表双向同步工具。

## [v0.4.2] - 2026-05-28 — Cmd+P「快记任务」加「⬅ 回上一步」(state machine 重构)

> **背景**:v0.4.1 把 Cmd+P 流程从 9 步扩到 11 步后,用户反馈"一旦设置错误,要有退回上一步的操作"。原版只有 Esc=整体取消,中途选错只能整个重来 — 11 步太长,UX 摩擦明显。
>
> 解决:把整个 wizard 重构为 **state machine + while loop + sentinel 返回值**,每个 suggester 顶部加「⬅ 回上一步」选项,inputPrompt 类(标题 / DDL 手输 / subcategory 手输)用单字符 `^` 表示后退。

### 🎯 主要改动

| 改动 | 说明 |
|---|---|
| **state machine 框架** | 新增 `STEPS` 数组(扁平 13 项)+ `state` 对象 + `isStepActive()` 分支判断 + `findPrevActive()` 跳过非激活 step 的后退 + `runWizard()` while loop 调度 |
| **BACK / CANCEL sentinel** | step fn 返回 `BACK` = 回上一步;返回 `CANCEL` = 整体取消;返回 `null` = 继续下一步 |
| **`pickWithBack(qa, opts, vals, canBack)` helper** | 包装 suggester,canBack=true 时顶部加「⬅ 回上一步」选项 |
| **`inputWithBack(qa, label, ...)` helper** | 包装 inputPrompt,label 末尾自动加「(输入 ^ 回上一步)」提示,检测用户输入 `^` → 返回 BACK |
| **分支切换状态清理** | `stepCategory` 改大类时清空对侧分支 state(parentName/projectMinor 或 subcategoryList),避免后退再前进时脏数据 |
| **DDL 手输局部 loop** | DDL 选「📝 手输」后,inputPrompt 输入 `^` → 回 DDL 选项菜单(局部,不是回上一 step);选「⬅ 回上一步」才是回 Step 3 |
| **多选循环 back** | months / weeks selectMultiOrDefault:首次进入(未选任何值)顶部加「⬅ 回上一步」;选了 ≥1 个后不再支持后退(避免撤销栈复杂度) |

### 🔬 设计要点

#### 扁平 STEPS + 分支跳过

不用嵌套 step tree,STEPS 是单一数组 13 项;`isStepActive()` 根据 `state.category` 判断 parentLevel1/2/projectMinor 还是 subcategoryManual 激活。while loop 遇到非激活 step 直接 `i++; continue;`,后退时 `findPrevActive(i, state)` 跳过非激活 step。

#### Esc 语义不变

QuickAdd 的 Esc 返回 `undefined`,在 step fn 里被映射为 CANCEL,顶层 runWizard 返回 null → 用户看到「❌ 已取消」Notice。**没有改 Esc 语义为"后退"** — 老用户的 Esc 习惯保持。

#### Step 1(priority)不加「⬅ 回上一步」

`findPrevActive(0, state)` 返回 -1,canBack=false → suggester 顶部不显示该选项。用户视角:第一步没有上一步,菜单干净。

### 🛠 改动文件

| 文件 | 改动量 |
|---|---|
| `obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js` | 完全重构(~510 行 → ~565 行;原 module.exports 内联流程 → 13 个独立 stepFn + STEP_DISPATCH 表 + runWizard) |

### 🚫 不影响

- **sync.py / 模板 / 飞书表结构 / config 全部不动** — 纯 userscript 内部重构
- **老 task 不受影响** — 用户已建的 task md 不动

### ⚠️ 用户侧需要做的事

无 — 重启 Obsidian 让 QuickAdd 重新 require userscript 即可。

---

## [v0.4.1] - 2026-05-28 — Cmd+P「快记任务」加业务大类 + 执行状态选择

> **背景**:用户作为 ADHD 用户反馈 — Cmd+P 流程现状只能记产品项目相关 task,生活财务杂务 / 技能学习 / 领域学习 这类「非产品项目」事项一旦不进飞书看板就会被忘记。同时执行状态(`status`)是创建 task 时最重要的元数据之一,旧版写死 `todo` 没给选择步骤。
>
> 用户原话:"添加任务的流程中现在缺乏执行状态,而执行状态是创建时最重要的"+"生活财务的杂务,这个也需要进入看板,否则作为 ADHD 总是忘记"。

### 🎯 主要改动

| 改动 | 位置 | 说明 |
|---|---|---|
| **新增 Step 3「业务大类」** | userscript Step 3 | 4 选 1:📦 产品项目 / 🪣 杂务 / 🔧 技能工具 / 📚 领域学习。写入 `category` frontmatter,sync 推飞书「大类」select 字段(已有映射,sync.py 无需改) |
| **分支:产品项目走 3a/3b/3c** | Step 3a→3c | 原 Step 3(产品项目一级)/ Step 4(子级)/ Step 4.5(项目小类)→ 重命名为 3a/3b/3c,仅产品项目分支执行 |
| **分支:非产品项目走 3d** | Step 3d | 杂务/技能工具/领域学习 → 手输 subcategory(逗号分隔,可选);写入 `subcategory: [财务, 家务]` list,sync 推飞书「小类」multi-select 字段。titlePrefix = 【大类/小类】或【大类】 |
| **新增 Step 8「执行状态」** | userscript Step 8(标题前) | 7 态全量:Todo / Doing / SubDone / Done / Block / cancel / Idea(默认 Todo)。替换原写死 `status: todo`。映射对齐 `config.task_md_map` 7 态 |
| **task md 模板注释更新** | `obsidian-assets/templates/task-template.md` | `subcategory` 注释从「v0.3.8 淡化」改回「v0.4.1 非产品项目分支用」;`category` 注释加「Cmd+P Step 3 必选」 |

### 🔬 流程对比

**旧(v0.5.0)9 步**:
```
1 优先级 → 2 ADHD → 3 产品项目一级 → 4 子级 → 4.5 项目小类 →
5 DDL → 6 月 → 7 周 → 8 今日 → 9 标题(status 写死 todo)
```

**新(v0.4.1)**:
```
1 优先级 → 2 ADHD →
🆕3 业务大类(category)
   ├ 产品项目 → 3a 一级 → 3b 子级 → 3c 项目小类
   └ 其他三类 → 3d subcategory 手输
→ 4 DDL → 5 月 → 6 周 → 7 今日 → 🆕8 执行状态 → 9 标题
```

### 🛠 改动文件

| 文件 | 改动 |
|---|---|
| `obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js` | 顶部注释(`v0.3.8` → `v0.4.1`)+ Step 3 业务大类 suggester + 产品项目分支 if/else 包裹 + Step 3d 手输 + Step 8 状态 suggester + 生成 content 时改 `status: ${statusChoice}` / 加 `categoryLine` / `subcategoryLine` |
| `obsidian-assets/templates/task-template.md` | category / subcategory 注释更新 |

### ⚠️ 用户侧需要做的事

#### ✅ 必做:飞书表「大类」字段确认 4 个 enum

如果飞书 task 表「大类」字段已建,确认 4 个 enum 选项都有:
- 产品项目 / 杂务 / 技能工具 / 领域学习

如缺少,用 `feishu-cli bitable field` 或飞书后台 UI 补全 — sync 时飞书侧若没对应 enum 会 silently skip 该字段,task 不会被归类。

#### ✅ 推荐:飞书后台建「按大类分组」看板视图

视图分组 by 「大类」字段,4 个泳道(产品项目 / 杂务 / 技能工具 / 领域学习)— 这样 ADHD 看板上 4 个泳道并存,杂务也能被看见(用户原始动机)。

### 🚫 不影响

- **sync.py 无任何改动** — category / subcategory 的 forward push 在 v0.3.x 就已支持(`parse_task_md` line 1112-1113 + `build_fields_payload` line 2038-2040 通用 select 分发 case),只是 userscript 一直没填值
- **老 task 不受影响** — 已存在的 task md `category:` / `status: todo` 维持原值

---

## [v0.5.0] - 2026-05-28 — task md ↔ 飞书 5 字段补全 + **完整反向同步**(16 frontmatter + 7 H2 段) + Step 3 反向 push + 闭环修

> **Step 3 扩展(本版本 3 块连续叠加)**:
> - 🔥 修 `--task-md` 路径不存在的 fallback(Auto Note Mover 把 task md 移到 02 Area/08 炒股/ 后 sync.py 找不到)
> - 🔥 修 `_scan_ob_task_md_by_feishu_record` 扫范围从 04 Inbox/task → 全 vault(解决 Auto Note Mover 移走后 pull-today 误判"飞书有 OB 无" + 死循环重建)
> - ⭐ 加 `--push-all-today` 反向 OB→飞书 批量推 + Cmd+P「🎯 批量推今日 task」 userscript
> - 🔧 H2 段顺序对齐飞书看板视图顺序(用户故事 → 验收 → 思路 → 概述 → 交付 → 资料 → 复盘)
> - 🔧 dataview cache 根治:userscript 等 fs/metadata cache 同步 + 多 command ID + plugin API + journal preview rerender

### 🆕 v0.5.0 Step 3 新增能力

#### 1. `--push-all-today` 反向批量 push(对称 pull-today)

```bash
# 场景:AI 助手补充 OB task md 内容 → 一键批量推飞书
python3 sync.py --push-all-today          # dry-run 看哪些会推
python3 sync.py --push-all-today --apply  # 真推
```

- 扫全 vault 找 `today=true` task md → 各自调 `push_task_md` 单条 push
- 冲突策略:OB 覆盖飞书(对称 pull-today 的"飞书覆盖 OB")
- 防御:`build_fields_payload` 空字段不写,不会清空飞书侧已有数据
- userscript:Cmd+P 「🎯 批量推今日 task 到飞书(反向)」

#### 2. `push_task_md` refactor 加 `_silent_fail`

原 sys.exit(1) → 加 `_silent_fail=True` 时返回 dict `{success, action, record_id, error, path}`,让批量调用方汇总错误而非中断。

#### 3. `--task-md` 路径不存在 fallback

userscript 创建 task md → Auto Note Mover 根据关键词(「炒股」/「财务」等)移动 → userscript 传给 sync.py 的原路径失效。

修复:`push_task_md` 路径不存在时,自动 vault rglob 同名 .md,优先 `04 Inbox/task/`,fallback 全 vault。

#### 4. `_scan_ob_task_md_by_feishu_record` 全 vault 扫 + duplicate 检测

`pull_today_from_feishu` 的 ob_index 不再仅扫 `04 Inbox/task/`,改扫全 vault(排除 .obsidian / .git / .trash 等):
- 解决"飞书有 OB 无"误判(原因:Auto Note Mover 移走后没被识别)
- 解决死循环:sync.py 重建 task md → Auto Note Mover 又移走 → 留下 duplicate
- 加 duplicate 检测:同一 rec_id 多 task md → 取 mtime 最新 + 报警让用户清理

#### 5. H2 段顺序对齐飞书看板视图

模板 + userscript + 反向建 sync.py 3 处统一改为:**用户故事 → 验收条件 → 执行思路 → 执行概述 → 交付 → 相关资料 → 复盘**(对齐用户截图所见的飞书看板字段顺序)。

#### 6. dataview cache 根治

`quickadd-拉今日todo.js` Step 4 改造:
- 等 1.5s 让 fs watcher + metadata cache 同步(sync.py 外部改 frontmatter 后 Obsidian 有 race)
- 试 5 个可能的 dataview command ID(`dataview:dataview-drop-cache-and-reload` / `dataview:dataview-force-refresh-views` / `dataview:dataview-rebuild-current-view` / `dataview:dataview-rebuild` / `dataview:rebuild`)
- 直接调 `app.plugins.plugins["dataview"].index.reload()` plugin API
- 重新打开 today journal 触发 preview rerender

`quickadd-批量推今日-task-md.js` 同款机制。

### 🛠 改动文件汇总(v0.5.0 完整 + Step 2 + Step 3)

| 文件 | 改动 |
|---|---|
| `sync.py` | `push_task_md`:路径 fallback + `_silent_fail` refactor |
|  | `_scan_ob_task_md_by_feishu_record`:scan_root 改 vault_root + duplicate 检测 |
|  | `_create_task_md_from_feishu_record`:扫 vault 防重复 + H2 段顺序新版 |
|  | `push_all_today_task_md` 新函数 + `--push-all-today` CLI |
| `obsidian-assets/userscripts/quickadd-拉今日todo.js` | dataview cache 根治(等待 + 多 command ID + plugin API + journal rerender)|
| `obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js` | 内嵌模板补 5 字段 + H2 段顺序新版 |
| `obsidian-assets/userscripts/quickadd-批量推今日-task-md.js`(新)| 调 `--push-all-today --apply` + 解析 stdout + Notice |
| `obsidian-assets/templates/task-template.md` | frontmatter 加 actual_hours/quality/parent_task + H2 段顺序新版 |
| `install.sh` | QuickAdd choices JSON 加 `push-all-today-choice` |
| `config.yaml` + `config.example.yaml` | `field_name: 父任务` → `field_name: 相关任务` |

> **背景**:OB 端 5 月 28 日给 task 模板新加了 5 字段(完成质量 / 用时 / 父任务 / 交付正文段 / 用户故事正文段),sync.py 同步实现 **forward + reverse + 反向建** 三处映射,完成 OB ↔ 飞书 task 字段双向闭环。
>
> **Step 2 扩展(本版本同期)**:用户反馈"不只 5 字段,我要全部反向同步" → 调飞书 API 拉一手字段表后发现 OB rules 误标"飞书无对应"的字段实际存在,反向同步范围扩展为 **16 frontmatter + 7 H2 段**(原 v0.5.0 5 字段基础 + 加 efficiency / project_minor / iteration_* / parent_project + execution_summary / acceptance / **thinking** / **resources** / retrospective_text)。
>
> 用户原话:"任务 md 中最重要的是最重要的是交付内容" + "不是 5 个字段吧,我需要的是全部字段拉回啊"。

### 🔥 P0 修 bug:飞书字段名「父任务」→「相关任务」

Step 2 调飞书 API 拉一手字段表时发现,飞书表里**根本没有「父任务」字段** — 实际字段名是「**相关任务**」(`fldm6h6LjN`,link 双向自关联,飞书自动反向显示成"子任务")。v0.5.0 第一版 config 写错字段名 → forward apply 时飞书 cli 会返回"字段不存在"错误。

修复:
- `config.yaml` + `config.example.yaml`:`field_name: 父任务` → `field_name: 相关任务`
- `sync.py:_extract_fields_from_feishu_row`:`_link_first_id(_get("父任务"))` → `_link_first_id(_get("相关任务"))`

### 🐛 修 v0.3.7 老 bug:`parent_project` 反向同步 startswith 启发 fallback 污染

Step 2 实施时发现 `_extract_fields_from_feishu_row` 有一段 v0.3.7 加的 fallback:
```python
if not parent_project and title.startswith("【布丁"):
    parent_project = "00 布丁"
```

在完整反向同步场景下,这会把所有「【布丁」开头的 task md 的 `parent_project` 改为 "00 布丁",**篡改用户实际选的子级关联**(如 "布丁开发" / "布丁内容")。实测 dry-run 命中 4 条假 diff。

修复:**完全删除** startswith 启发 fallback。反向 parent_project 只取「产品项目」link 字段的 text(无 link → 空 → PRESERVE 保留 OB)。

### 📊 反向同步覆盖范围(Step 2 后)

| 类别 | v0.5.0 第一版 | v0.5.0 Step 2 后 |
|---|---|---|
| **Frontmatter 反向同步白名单** | 11 字段 | **16 字段**(+ efficiency / project_minor / iteration_week / iteration_month / parent_project)|
| **正文 H2 段反向同步白名单** | 2 段(交付 / 用户故事)| **7 段**(+ 执行概述 / 验收条件 / 执行思路 / 相关资料 / 复盘)|

⭐ 特别澄清:OB rules 之前标「执行思路 / 相关资料」为"飞书无对应,sync 静默跳过" — **错误**。调飞书 API(`feishu-cli bitable field list`)一手验证:`fldFbyifxQ`(执行思路 text)和 `fldulkShMa`(相关资料 text)都存在。v0.5.0 Step 2 把这两段纳入双向同步。

### 🎯 5 字段双向同步

| 飞书字段 | 类型 | OB 表达 | Forward | Reverse |
|---|---|---|---|---|
| **完成质量** | select 单选 | frontmatter `quality: 高/中/低` | ✅ | ✅ |
| **用时** | number | frontmatter `actual_hours: 1.5` | ✅ | ✅ |
| **父任务** | link(自关联本表) | frontmatter `parent_task: "[[<父 task 文件名>]]"` | ✅ wikilink → vault 反查 record_id | ✅ record_id → ob_index → wikilink |
| **交付** | text | 正文「## 📦 交付」H2 段 | ✅ | ✅ ⭐ 首次反向同步正文段 |
| **用户故事** | text | 正文「## 👥 用户故事」H2 段 | ✅ | ✅ |

### 🔬 算法亮点

#### parent_task 双向 wikilink ↔ record_id 解析

- **Forward**(OB→飞书):`resolve_parent_task_record_id()` — `[[2026-05-20-XXX]]` → vault `04 Inbox/task/2026-05-20-XXX.md`(直接路径优先 + rglob fallback) → 读 frontmatter `feishu_record` → 飞书 link 字段写 `[<rec_id>]`(数组形态)
- **Reverse**(飞书→OB):飞书 link 字段返回 `[{"id": "rec..."}]` → 反查 `_scan_ob_task_md_by_feishu_record` 索引 → 取该 path 的 stem → 拼 `[[<stem>]]`
- **失败兜底**:父 task 未 sync(无 feishu_record)/ vault 内找不到 → warning + 跳过该字段(**不阻断其他字段**同步)

#### H2 段反向同步(首次实现)

- 新函数 `update_h2_section_in_task_md(p, h2_title, new_content)`:
  - 段已存在 → 替换段内容(保留 H2 标题行)
  - 段不存在 → 在「## ✅ 完成标记」之前插入完整新 H2 段(老 task md 兼容)
  - 找不到「## ✅ 完成标记」标识 → 放弃插入(防御误改不规范 task md)
- 防御策略对齐 `PRESERVE_OB_IF_FS_EMPTY`:**飞书侧空 → 保留 OB**(避免误清 OB 内有效内容)
- 新白名单 `_REVERSE_SYNC_H2_WHITELIST = [("delivery", "## 📦 交付", "交付"), ("user_story", "## 👥 用户故事", "用户故事")]`

#### dry-run 显示完整 H2 段 diff

```
--- 🔄 字段同步详情(飞书 → OB,共 1 条 task md)---
  📝 2026-05-26-【布丁开发】功能：日常习惯打卡.md
     • 📑 交付: (空) → 交付物: / - [2026-05-08-习惯打卡UI重做-设计文档](https://fei...
```

多行内容自动 `\n` → ` / ` 压缩 + 截 50 字,方便用户审 diff。

### 🛠 改动文件

| 文件 | 改动 |
|---|---|
| `sync.py` | `parse_task_md`:加 delivery / user_story H2 段抽取 + quality / actual_hours / parent_task frontmatter 抽取 |
|  | `build_fields_payload`:task_md_fields 分发 case 加 quality(select 单选)/ actual_hours(number)/ parent_task(link 自关联,新 `resolve_parent_task_record_id` helper)/ delivery + user_story(text catch-all) |
|  | `push_task_md` dry-run 输出加 5 字段提示 |
|  | `_extract_fields_from_feishu_row`:加 ob_index 可选参数;返回 dict 加 quality / actual_hours / parent_task / delivery / user_story 5 key;`_text_value` / `_link_first_id` 新 helper |
|  | `_REVERSE_SYNC_FIELD_WHITELIST` 加 quality / actual_hours / parent_task |
|  | 新加 `_REVERSE_SYNC_H2_WHITELIST` / `_read_h2_section_content` / `update_h2_section_in_task_md` / `_diff_h2_sections_with_feishu` |
|  | `_diff_frontmatter_with_feishu` `PRESERVE_OB_IF_FS_EMPTY` 加 3 新字段 |
|  | `_create_task_md_from_feishu_record`:加 ob_index 参数;模板加 actual_hours / quality / parent_task frontmatter + ## 📦 交付 / ## 👥 用户故事 H2 段 |
|  | `pull_today_from_feishu`:`_compute_field_diff` 计算 H2 段 diff;3 个 apply 分支(plan_set_true / plan_skip / plan_set_false)都调 `_apply_h2_updates` 同步 H2;plan_missing 调 `_create_task_md_from_feishu_record` 时传 ob_index |
| `config.example.yaml` | `task_md_fields` 加 quality / actual_hours / parent_task / delivery / user_story 配置;`reverse.field_to_ob` 加 5 个 `*_field` 文档项 |
| `config.yaml` | 同上(用户私域) |
| `docs/feishu-schema.md` | 字段总数 22 → 27,加 5 新字段定义;feishu-cli 创建脚本加 5 行;v0.5.0 字段说明 section |
| `obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js` | **真机验收时发现的 bug 修补** — Cmd+P 快记任务 userscript **内嵌**模板字符串(不读 OB 端 task 模板文件),独立加 5 字段:frontmatter `actual_hours / quality / parent_task` 3 行 + 正文「## 📦 交付」/「## 👥 用户故事」2 个 H2 段(各带 HTML 注释)。**用户侧重装**:`bash install.sh --apply --force --scripts-dir ...` + Cmd+Q 重启 Obsidian 让 QuickAdd 加载新版 |

### ⚠️ 用户侧需要做的事

#### ✅ 必做 1:飞书表后台加 5 字段

按 `docs/feishu-schema.md` 的 feishu-cli 命令 + 你自己的 BASE/TABLE 跑一下,或在飞书后台 UI 手建:

- 「完成质量」select 单选,选项 `高 / 中 / 低`
- 「用时」number,formatter `0.0`
- 「父任务」link,**自关联到本表**(选当前 table_id 作为 link_table)
- 「交付」text
- 「用户故事」text

#### ✅ 必做 2:把 `config.example.yaml` 的 5 新字段配置同步到你的 `config.yaml`

找到 `task_md_fields:` 段 `execution_summary:` 下面,加 5 个新 block(完整内容见 `config.example.yaml` 的「v0.5.0 加:5 字段补全」section)。

#### ✅ 必做 3:OB 端 task 模板加 5 字段

这一步**已经被 OB CC 在 2026-05-28 做完**:
- `03 Resources/素材库/模版/task 模版.md` 加 `quality / actual_hours / parent_task` frontmatter + ## 📦 交付 / ## 👥 用户故事 H2 段
- `.claude/rules/base-and-frontmatter.md` task md schema 同步
- `.claude/rules/feishu-project-sync.md` 1:1 映射表 + 反向同步白名单 audit

#### 可选 4:批量给历史 task md 补 5 字段

老 task md(2026-05-28 前建的)没有这 5 字段。如果想让历史 task md 也用上反向同步:
- 简单粗暴:每次完成历史 task 时手动在 frontmatter 加 quality / actual_hours,在正文加 ## 📦 交付 段
- 批量:写个 helper 脚本扫 `04 Inbox/task/*.md` → frontmatter 加缺的 key(空值即可)+ 正文在 `## ✅ 完成标记` 前插 ## 📦 交付 / ## 👥 用户故事 段

不补也行 — sync.py 会对缺字段 / 缺段静默跳过,不报错。

### 🧪 验收测试结果(实施 CC 跑)

- ✅ **Phase 2 Forward dry-run**:`/tmp/test-5字段-forward.md`(5 字段全填 + parent_task 指向已 sync 的 `2026-05-28-test-反向-subdone-v2.md`)→ payload 含「完成质量 ['高']」「用时 1.5」「父任务 ['recvkROcczcHOn']」「交付 多行文本」「用户故事 文本」5 字段
- ✅ **Phase 2 parent_task 兜底**:同上 md parent_task 改指 `[[2099-12-31-不存在的父任务]]` → dry-run 输出 `⚠️ parent_task 找不到 vault 内对应 task md → 跳过该字段` + payload 中无「父任务」字段(其他 4 字段照常)
- ✅ **Phase 3 Reverse pull-today dry-run**:真实场景命中 — `2026-05-26-【布丁开发】功能：日常习惯打卡.md` 飞书侧「交付」非空 + OB 端 ## 📦 交付 段空 → dry-run 显示 `📑 交付: (空) → 交付物: / - [2026-05-08-习惯打卡UI重做-设计文档](https://fei...`(多行 `\n` → ` / ` 截 50 字)

### 🚫 非目标(留 P2 backlog)

- 不做附件字段(飞书「附件」attachment 类型)— 架构复杂,需 OSS / 飞书文件 token 转换单独 spec
- 不动「执行思路」/「相关资料」字段 — OB 端有但飞书表无,继续 sync 静默跳过

## [v0.3.8] - 2026-05-28 — Cmd+P 快记任务加 Step 4.5「项目小类」三级分类

> **背景**:用户在飞书项目看板新加了「项目小类」task 表 multi-select 字段(field #29),用于**三级分类**的最精细层 — 任务**内容细分类型**。
> 例:布丁内容(子级) → 干货 / 训练营 / 课程产品(项目小类);装备配置(子级) → Codex / claudecode / 软硬件(项目小类)。
> v0.3.5 Cmd+P 已经支持大类(L1)/ 小类(L2),v0.3.8 加 Step 4.5 让用户在创建 task 时一次性把 L3 也填好,飞书看板可按三级精细切片。

### 🎯 流程升级:Cmd+P 在小类(Step 4)和 DDL(Step 5)之间插 Step 4.5

| Step | 内容 | 现状 |
|---|---|---|
| 1 | 优先级 | v0.3.5 |
| 2 | ADHD 优先级 | v0.3.5 |
| 3 | 大类 parent_project(飞书产品项目表父=空) | v0.3.5 |
| 4 | 小类 parent_subproject(产品项目表父=L1) | v0.3.5 |
| **4.5** | **🆕 项目小类**(task 表 multi-select,飞书最近 5 条 distinct,多选循环 / 跳过) | **v0.3.8** |
| 5 | DDL | v0.3.5 |
| 6 | 执行月 | v0.3.5 |
| 7 | 执行周 | v0.3.5 |
| 8 | 是否今日 | v0.3.5 |
| 9 | 标题 | v0.3.5 |

### 🛠 改动文件

| 文件 | 改动 |
|---|---|
| `sync.py` | `parse_task_md` 加 `project_minor: list[str]` 抽取(用 `_ensure_list`);`build_fields_payload` 让 `project_minor` 走 `subcategory` 同 multi-select 分支;`cmd_quickadd_options` 加 `recent_project_minor` 字段;`get_recent_iteration_options` 让 `sort_key_fn` 可选(`None` 时不排序按 set 顺序取 top N,适合无自然排序的 enum) |
| `obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js` | Step 4.5 插入 project_minor 多选循环(复用 `selectMultiOrDefault` helper);helper 加 `defaultValue=null` 分支显示「❌ 跳过 / 不填」而非「⏭ 用默认(null)」;frontmatter 输出加 `project_minor: [...]` 行 |
| `obsidian-assets/templates/task-template.md` | 加 `project_minor:` 字段定义 + 注释;`subcategory` 注释标注「v0.3.8 起淡化使用」 |
| `config.example.yaml` | 加 `task_md_fields.project_minor.field_name: 项目小类` |

### 🔌 sync.py `--quickadd-options` JSON 输出新增字段

```json
{
  "active_top_level": [...],
  "subprojects_by_parent": {...},
  "recent_months": [...],
  "recent_weeks": [...],
  "recent_project_minor": ["训练营", "干货", "claudecode", "Codex", "软硬件"]   // 🆕 v0.3.8
}
```

数据源:飞书主表 `default_view_id` 拉最近 200 条 record,扫「项目小类」字段 distinct 值,无自然排序按 set 顺序取前 5(用户视角 = "最近用过的几个,不一定最新")。

### ⚠️ 用户侧需要做的事

#### ✅ 必做 1:在你的 `config.yaml` 加 4 行

找到 `task_md_fields:` 段下面的 `subcategory:` 块,后面紧接着加:

```yaml
  # v0.3.8 加:项目小类(task 表 multi-select enum)
  project_minor:
    field_name: 项目小类           # select(多)
```

#### ✅ 必做 2:重装 userscripts

```bash
bash /Users/aim5/Documents/CodingProject/feishukanban-ob-sync/install.sh \
  --apply --force \
  --scripts-dir "01 Project/00 进行中/06 小工具开发/feishukanban-ob-sync"
```

(注意你的 `--scripts-dir` 自定义路径必须显式传)

#### ✅ 必做 3:`Cmd+Q` 重启 Obsidian → `Cmd+P` 测试

应该看到 Step 4 小类之后弹「项目小类」(`🏷 训练营 / 🏷 干货 / 🏷 claudecode / 🏷 Codex / 🏷 软硬件`),可多选循环。

### ⚠️ 与 `subcategory`(老「小类」字段)的关系

- **老字段「小类」**(飞书 field [3]):保留,**不在 Cmd+P 弹**,跟 task md `subcategory` 对应
- **新字段「项目小类」**(飞书 field [29]):Cmd+P Step 4.5 主动选,跟 task md `project_minor` 对应

两个字段语义相近但用法不同:
- `subcategory`:历史字段,新 task 推荐不填
- `project_minor`:新主推,**三级分类的最精细层**

未来如果完全废弃 subcategory,改 task-template 把这行删除即可。

### ⚖️ 8 条原则自评

| # | 原则 | 评分 | 备注 |
|---|---|---|---|
| 1 | 解耦 | ⭐⭐⭐⭐⭐ | parent_project / parent_subproject / project_minor 三级分明,各自独立字段 |
| 2 | 可扩展 | ⭐⭐⭐⭐⭐ | 加新维度(如「task 难度」)只需 config + Step + helper 复用,代码零改 |
| 3 | 灵活修改 | ⭐⭐⭐⭐ | Step 4.5 插入位置在 userscript 一处控制 |
| 4 | 渐进披露 | ⭐⭐⭐⭐ | 跳过选项让 ADHD-friendly 流程仍能秒速跑 |
| 5 | 鲁棒性 | ⭐⭐⭐⭐⭐ | config 未配 project_minor.field_name → cmd_quickadd_options 跳过 / recent_project_minor 为空 → userscript 跳过 Step 4.5 |
| 6 | 人可读 | ⭐⭐⭐⭐ | project_minor 命名清晰,跟飞书侧字段名「项目小类」直接对应 |
| 7 | 高复用 | ⭐⭐⭐⭐⭐ | `get_recent_iteration_options` 通用化,以后任何 multi-select enum 字段都能复用 |
| 8 | 工程化清晰 | ⭐⭐⭐⭐ | Python ast + node --check 双语法校验 + smoke test recent_project_minor |

---

## [v0.3.7] - 2026-05-28 — pull-today 反向字段 diff sync(飞书改 status 后 OB 实时同步)

> **背景**:v0.3.6 之前 `pull-today` 设计上**只同步 `today` 字段**,对**现存** task md(已有 feishu_record 关联的)走 `plan_skip` / `plan_set_true` / `plan_set_false` 分支时,**完全不动 status / priority / 其他字段**。
>
> 用户实测痛点(2026-05-28):"5 月 28 日 AI 日报已经是 done,但依然显示的是 todo,改成 subdone 也不行,问题在于看板是实时修改状态,需要在修改后拉回新的状态"。 ADHD 友好的"飞书是真相源"体验完全破坏 — 每次飞书 app 改 status / priority 都要回 OB 手改 frontmatter。
>
> v0.3.7 把 `pull-today` 从"今日 sync"升级为"今日 + 字段 diff sync",**飞书覆盖 OB**(飞书是 ADHD 实时操作端,OB 是文档端)。dry-run 必显示每个字段 before → after,user 可看清楚再 apply。

### 🆕 反向 diff sync 字段白名单

8 个字段:`priority` / `status` / `category` / `subcategory` / `adhd_priority` / `estimate_hours` / `due` / `done_date`

不含:
- `title`(改文件名风险大)
- `created` / `feishu_record` / `feishu_url`(不应反向覆盖)
- `today` / `today_history` / `today_source`(已有专门逻辑)
- `iteration_week` / `iteration_month`(多选 list + 飞书字段复杂,v0.3.8 候选)
- `parent_project`(v0.2.5 helper 读写死的"项目"字段名,实际是"产品项目" link 字段,需解析 link record → 名字,v0.3.8 修)

### 🛡️ 防误清防御:**飞书空 → 保留 OB**

`category` / `subcategory` / `adhd_priority` / `estimate_hours` / `due` / `done_date` 6 个字段:**飞书侧空 + OB 有值 → 不动 OB**(避免误清用户手填数据)。

`status` / `priority` 例外:它们必有值(飞书侧默认 Todo/P3),空是异常,不需要 preserve 逻辑。

### 🔧 实现

3 个新 helper:
- `_extract_fields_from_feishu_row(row, fields_meta, config) → dict`:从飞书 row 抽 OB frontmatter 同步字段(v0.2.5 `_create_task_md_from_feishu_record` 的字段抽取逻辑拆出,DRY)
- `_strip_wikilink(v) → str`:OB wikilink 形态 → 裸名字
- `_diff_frontmatter_with_feishu(p, fs_fields) → (updates, summary)`:读 OB frontmatter + 飞书字段 diff + 防误清

`pull_today_from_feishu` 新增 Step 4.5 预计算 diff,三分支(plan_set_true / plan_skip / plan_set_false)apply 时合并 `today_*` updates + 字段 diff updates,一次 `update_md_frontmatter` 调用。

`_format_yaml_value` 加 **wikilink 双引号特例**:`[[xxx]]` 形态写回时用双引号包裹(`"[[xxx]]"`),与 OB 端约定一致。

### 📝 改动文件

- `sync.py`:
  - `_format_yaml_value`(line ~485):加 wikilink 双引号特例
  - 新加 `_extract_fields_from_feishu_row`(line ~2814)
  - 新加 `_REVERSE_SYNC_FIELD_WHITELIST` 常量
  - 新加 `_strip_wikilink` helper
  - 新加 `_diff_frontmatter_with_feishu` helper(line ~2940)
  - 重构 `_create_task_md_from_feishu_record` 调 helper(DRY,保持 v0.3.6 行为)
  - 重构 `pull_today_from_feishu`:Step 4.5 预计算 diff,三分支合并 sync
- `CHANGELOG.md` / `README.md` / `docs/ARCHITECTURE.md` / `install.sh`:文档 + 版本号同步

### ✅ 用户实测(2026-05-28)

用户报告"5月28日AI日报 / 上传pdfAI教育报告 / 案例文章付费看 / JWT的token过期方案 / 日常习惯打卡"5 条 task md 都成功反向同步:
- `status: todo → done / doing / subdone` 4 case 全覆盖
- `priority: P1 → P2` 2 case
- 0 false positive(due / parent_project 都没误改)

### ⚖️ 8 条原则自评

| # | 原则 | 评分 | 备注 |
|---|---|---|---|
| 1 | 解耦 | ⭐⭐⭐⭐⭐ | 3 个 helper 独立,可单独测;diff 计算与 apply 分离 |
| 2 | 可扩展 | ⭐⭐⭐⭐⭐ | 加新同步字段 → 加白名单一行;特殊字段(iteration_*)在 helper 加 elif 分支 |
| 3 | 灵活修改 | ⭐⭐⭐⭐ | PRESERVE_OB_IF_FS_EMPTY 集合可调,白名单可加减 |
| 4 | 渐进披露 | ⭐⭐⭐⭐ | dry-run 必显示 before → after,user 看清楚再 apply |
| 5 | 鲁棒性 | ⭐⭐⭐⭐⭐ | 飞书空保留 OB(防误清),parent_project 暂禁(避免 v0.2.5 bug 放大) |
| 6 | 人可读 | ⭐⭐⭐⭐⭐ | helper docstring 详细,diff 输出格式直观 |
| 7 | 高复用 | ⭐⭐⭐⭐ | `_extract_fields_from_feishu_row` 同时服务反向建 + diff sync |
| 8 | 工程化 | ⭐⭐⭐⭐⭐ | dry-run 验证 → false positive 修 → apply → commit + push 完整链 |

### 🔮 v0.3.8 候选

- parent_project 反向 sync:正确读"产品项目" link 字段,解析 link record → 名字
- iteration_week / iteration_month 反向 sync:多选 list,需要 enum 反查

---

## [v0.3.6] - 2026-05-28 — `today_source` 字段:ADHD 自觉察「计划 vs 非计划」

> **背景**:ADHD 友好的「今日聚焦」需要区分两种 today task — **计划好的**(早晨 pull-today 拉来的)vs **临时插入的**(当天 Cmd+P 快记任务建的)。 v0.3.5 之前两者都是 `today: true`,看不出哪些是规划好的、哪些是中途冒出来分心的,自觉察缺一个抓手。
>
> v0.3.6 加 `today_source` frontmatter 字段(`planned` / `unplanned` / 空)+ sync.py / userscript / template 三处联动写入,OB dataview 可以按来源切片渲染。

### 🆕 today_source 字段语义

| 值 | 含义 | 写入触发 |
|---|---|---|
| `planned` | 前一晚 / 早晨已规划 | `sync.py --pull-today` 设 today=true 时(plan_set_true / `_create_task_md_from_feishu_record`) |
| `unplanned` | 当天临时插入 | Cmd+P 「📝 快记任务」 + 「是否今日」=是 时 |
| 空 | 不在今日 / 历史 task / 手改 today | pull-today 设 today=false 时清空(对称) |

### 🛠 改动点

| 文件 | 改动 |
|---|---|
| `sync.py` `update_md_frontmatter` (line 519) | 空字符串特例:`value == ""` 时写 `key:`(纯空),避免 `_format_yaml_value("")` 返回 `''` 被 dataview 当 truthy 漏过滤 |
| `sync.py` `_create_task_md_from_feishu_record` (line 2911) | 模板加 `today_source: planned`(pull-today 自动建的 = 早晨规划) |
| `sync.py` `pull_today_from_feishu` plan_set_true (line 3083) | update 三字段:`today` + `today_history` + `today_source: planned` |
| `sync.py` `pull_today_from_feishu` plan_set_false (line 3117) | 对称清空 `today_source: ""`(取消今日 = 无来源标记) |
| `obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js` (line 355) | Cmd+P 临时建 task:today=true 时 `today_source: unplanned`,否则空 |
| `obsidian-assets/templates/task-template.md` | 加 `today_source` 字段定义 + 注释;priority 注释澄清"不再表达计划/非计划";status 注释扩展到 7 态(v0.3.5 补) |

### ⚠️ 用户侧需要做的事

- ☐ `install.sh --apply --force` 重装(让 sync.py 新逻辑 + userscript today_source 注入 + task-template 注释生效)
- ☐ 老 task md(v0.3.6 之前建的)`today_source` 字段缺失 → dataview 视为空 → 默认归"计划"段(可接受,语义保守)
- ☐ OB 端 journal 模板 dataview 如需按 today_source 切片渲染 → OB 侧自己改 query(本仓库不动 OB 模板)

### ⚖️ 8 条原则自评

| # | 原则 | 评分 | 备注 |
|---|---|---|---|
| 1 | 解耦 | ⭐⭐⭐⭐ | today_source 写入 3 处(pull-today / Cmd+P / 反向建),都独立 |
| 2 | 可扩展 | ⭐⭐⭐⭐⭐ | 加新 source 类型(如 `inherited` / `recurring`)只需补一行,代码零改动 |
| 3 | 灵活修改 | ⭐⭐⭐⭐⭐ | OB dataview 决定如何渲染,sync.py 只负责写值 |
| 4 | 渐进披露 | ⭐⭐⭐⭐ | 字段语义清楚,新 task 自动填,老 task 空值兜底 |
| 5 | 鲁棒性 | ⭐⭐⭐⭐⭐ | `update_md_frontmatter` 空字符串特例修了 dataview truthy 误判 bug |
| 6 | 人可读 | ⭐⭐⭐⭐ | planned / unplanned / 空 三态语义清楚 |
| 7 | 高复用 | ⭐⭐⭐⭐ | today_source 通用于任何"按来源分类"场景 |
| 8 | 工程化清晰 | ⭐⭐⭐⭐ | sync.py / userscript / template 三处一致改 |

### 🔮 下一步候选(v0.3.7)

handoff 反向回执已记的 follow-up:`pull-today` 对**现存** task md 反向 sync status / priority / iteration_*(目前只同步 today 字段,飞书改 status 后 OB 不响应)。

---

## [v0.3.5] - 2026-05-27 — status 7 态对齐 + Cmd+P 快记任务 9 步流程升级

> **2 块 patch 合并**(v0.3.4 模式):
> - **Part 1**:status 7 态对齐飞书看板(加 SubDone + Idea)— OB CC 跨边界例外修
> - **Part 2**:Cmd+P 快记任务升级 9 步交互 + sync.py `--quickadd-options` batch 接口 — 让飞书看板能按 ADHD优先级 / 大类小类 / 周月 / DDL 维度直接筛选

---

## Part 1:status 7 态对齐飞书看板(加 SubDone + Idea)

> **背景**:用户飞书项目看板「执行状态」字段加了 SubDone 选项(Orange Lighter),用于"主任务下挂的子任务已完成,主任务本身还没收尾"的场景。截图反馈"看板上有 subdone,可能 task 的属性中没有同步到"。OB CC 走完 systematic-debugging 诊断发现 OB 端 schema 只 5 态,sync.py 4 处映射逻辑都缺 subdone/idea。
>
> **决策**:OB 端持有 subdone/idea,完全对齐飞书看板 7 态。inline checkbox 4 字符**不变**(`[ ]/[/]/[x]/[-]`),subdone 视觉同 doing,idea 视觉同 todo,**frontmatter.status 是真相源**。

### 🐛 修复 4 处映射 bug

| # | 位置 | 旧行为 | 新行为 |
|---|------|--------|--------|
| 1 | `sync.py` `_create_task_md_from_feishu_record` (line 2791) | `SubDone→doing` / `Idea→todo`(降级)| `SubDone→subdone` / `Idea→idea` / 补 `cancel→cancel`(保留 7 态语义)|
| 2 | `sync.py` `parse_task_md_for_push` status_map (line 985) | 缺 subdone/idea | 加 `subdone→/` + `idea→ `(inline 兼容层) + return dict 带 `fm_status` 原值 |
| 3 | `sync.py` `build_fields_payload` (line 1791) + `config.yaml` `fields.status` | 仅 4 字符 inline char → 飞书 enum | 优先 `task_md_map` 7 态直接映射,fallback 老 inline char 映射(journal 模式) |
| 4 | `config.yaml` `reverse.status_map` | 缺 SubDone | 加 `SubDone→/`(pull 写 journal inline 用)|

### 7 状态对齐表(契约真相源)

| OB frontmatter status | 飞书「执行状态」 | inline 兼容字符 |
|---|---|---|
| `todo` | `Todo` | `[ ]` |
| `doing` | `Doing` | `[/]` |
| `subdone` | `SubDone` | `[/]`(视觉同 doing)|
| `done` | `Done` | `[x]` |
| `block` | `Block` | `[-]` |
| `cancel` | `cancel` | `[-]` |
| `idea` | `Idea` | `[ ]`(视觉同 todo)|

⚠️ 飞书侧 `cancel` 是**小写**(其他 6 个 PascalCase)— 飞书后台手建时没大写,保留现状避免触发 SDK 大小写敏感不匹配。

### 🔗 OB 端配套(handoff 同步)

- task 模板 frontmatter `status` 注释扩展为 7 态
- journal 模板 dataview 从 TASK → LIST + 7 status emoji 渲染
- rules 3 处更新(base-and-frontmatter / feishu-project-sync / task-and-habits)

详见 `docs/handoff/OB对接/2026-05-27-status-subdone-idea-handoff.md` + 反向回执。

### 📝 改动文件

- `sync.py`(3 处:line 985 `parse_task_md_for_push` / line 1791 `build_fields_payload` / line 2791 `_create_task_md_from_feishu_record`)
- `config.example.yaml`(2 处:`fields.status.task_md_map` 新加 + `reverse.status_map` 补 SubDone)
- `config.yaml`(用户私域同步,本仓库不 commit)
- `docs/ARCHITECTURE.md`(status 数据模型一行扩展为 7 态)

### ⚠️ 注意

- inline checkbox 4 字符**不变**,Tasks 插件 + Cmd+P「完成 task」UserScript 行为不受影响
- journal 模式(inline task)继续走老 4 字符映射,**没有引入 frontmatter.status 概念**
- 用户测试前需手动把 `config.yaml` 的 `fields.status.task_md_map` + `reverse.status_map.SubDone` 同步到位

---

## Part 2:Cmd+P 快记任务 9 步流程升级 + sync.py `--quickadd-options` batch 接口

> **核心动机**:ADHD 友好工作流 = 飞书看板按维度筛选(优先级 / ADHD 优先级 / 大类小类 / 周月 / DDL)。
> v0.3.4 之前 Cmd+P 只填 5 个字段,task 同步飞书后还要去看板**二次手填**剩下 5 个 → 决策疲劳。
> Part 2 把所有看板筛选字段一次性弹完,飞书侧从此直接按维度切片,不用回头补数据。

### 🎯 新 9 步流程(原 5 步 → 9 步,但都带「跳过」选项)

| # | 字段 | 选项来源 | 默认 |
|---|---|---|---|
| 1 | 优先级 | 写死 P0/P1/P2/P3 | 必填 |
| 2 | **ADHD 优先级** 🆕 | 写死 待抢救 / 有 DDL / 自由待办 | 可跳过 |
| 3 | **大类**(parent_project) 🆕 | 飞书产品项目表 `活跃=true AND 父产品=空` | 可跳过 |
| 4 | **小类**(parent_subproject) 🆕 | 飞书产品项目表 `活跃=true AND 父产品=选中大类` | 可跳过 |
| 5 | **截止日期 DDL** 🆕 | preset:今天/明天/本周末/下周末/本月底/手输 | 可跳过 |
| 6 | **执行月**(多选)🆕 | 飞书最近 5 个 enum + ⏭ 默认(=created 当月) | 默认 |
| 7 | **执行周**(多选)🆕 | 飞书最近 5 个 enum + ⏭ 默认(=created 当周) | 默认 |
| 8 | 是否今日 | 写死 需求池/今日 | 必填 |
| 9 | 标题 | inputPrompt | 必填 |

### 🔌 sync.py `--quickadd-options` batch 接口

避免 Cmd+P 启动多次 python3 进程(每次 ~1s)。一次性 JSON 返回 4 类数据:

```bash
python3 sync.py --vault <vault> --quickadd-options
# 输出:
{
  "active_top_level": [{"name":"布丁","record_id":"rec..."}, ...],
  "subprojects_by_parent": {"rec...":[{"name":"布丁开发","record_id":"..."}],...},
  "recent_months": ["26 年 6 月","26 年 5 月", ...],
  "recent_weeks":  ["26W23（6月1日-6月7日）","26W22（5月25日-5月31日）", ...]
}
```

#### 关键实现细节

- **关联表读取**:`_extract_link_table_records()` 扫飞书产品项目表 record list(`--limit 200`,cli 上限),返回 enrich 后的 `[{name, record_id, active, parent_ids}, ...]`,过滤逻辑(活跃 / 父=空 / 父=指定)在 Python 侧做。
- **iteration 最近 5 个**:`get_recent_iteration_options()` 用 `default_view_id` 过滤拉主表(避免拉到老 record 漏新 iteration 值 — cli 不传 view_id 时是按创建时间 ASC 拉,前 200 条都是老 record),distinct + 正则前缀匹配 + DESC 排序 + top 5。
- **正则前缀匹配**:`^(\d{2})W(\d{1,2})` / `^(\d{2})\s*年\s*(\d{1,2})\s*月` — 容忍飞书侧 option name 加尾部说明(如 `26W22(5月25日-5月31日)`)。
- **active 字段可选**:`link_table_active_field` 未配 → 默认 `active=True`(向后兼容)。

### 🔧 sync.py 配套改造:`parse_task_md` + `build_fields_payload`

#### parse_task_md 新增字段
- `iteration_month: list[str]` — frontmatter list / 单 str / 空,都规范化为 list
- `iteration_week: list[str]`
- `parent_subproject: str` — 小类 wikilink 抽出

#### build_fields_payload 改逻辑(iteration_* 写飞书优先级)
1. frontmatter 显式 list 非空 → 直接写(多选 list,支持跨季)
2. 否则 done_date 非空 → 老 derive 算法(完成 task 补录历史,沿用 v0.3.4 行为)
3. 都没 → 跳过

#### parent_project 语义澄清(沿用 v0.2.4 行为,补充文档)
- userscript 选了小类 → `parent_project = 小类名` → 飞书 link 指向最精细 record(按二级看板筛选)
- 只选大类 → `parent_project = 大类名`
- `parent_subproject` 是 OB 侧 metadata(可空),sync 不推飞书

### 📝 task md frontmatter schema 变化

```yaml
# 旧 v0.3.4
iteration_week:           # 单值,sync 时根据 done_date 自动算
iteration_month:          # 同上

# 新 v0.3.5 Part 2(向后兼容)
iteration_week: [26W22(5月25日-5月31日), 26W23(6月1日-6月7日)]   # list
iteration_month: [26 年 5 月, 26 年 6 月]                       # list
```

旧单值字符串仍兼容(`_ensure_list` 包成 1-elem list)。

### 📦 改动文件(Part 2)

- `sync.py` +~210 行
  - 新 fn:`_extract_link_table_records` / `_iter_week_sort_key` / `_iter_month_sort_key` / `get_recent_iteration_options` / `cmd_quickadd_options`
  - `parse_task_md` 加 `iteration_month / iteration_week / parent_subproject` + `_ensure_list` helper
  - `build_fields_payload` iteration_* 改优先用 frontmatter
  - argparse 加 `--quickadd-options` flag
- `obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js` 整体重写(376 → ~420 行)
  - `getDateContext()` / `isoWeek()` / `selectMultiOrDefault()` 3 个 helper
  - Step 0 batch options + Step 1-9 交互
  - 保留 v0.3.1 跨日 / v0.3.3 TZ 注入 / v0.3.4 `__SYNC_PY_ABS_PATH__` 占位符
- `obsidian-assets/templates/task-template.md`:parent_project 注释扩展;iteration_* 注释 单值 → list
- `config.example.yaml` +3 行:`task_md_fields.parent_project.link_table_active_field`

### ⚠️ Part 2 用户侧需要做的事

#### ✅ 必做 1:`config.yaml` 加一行

找到 `task_md_fields.parent_project:` 块,在 `link_table_parent_field` 下面加:

```yaml
  parent_project:
    field_name: 产品项目
    link_table_id: tblZ5Zu8v6m5AUx0
    link_table_name_field: 产品项目名
    link_table_parent_field: 父产品
    link_table_active_field: 当前是否活跃     # ← v0.3.5 加这一行
    strip_prefix_regex: '^\d+\s+'
```

不加这行 → Cmd+P 大类菜单会显示**所有 11 个项目**(含归档,不过滤活跃)。

#### ✅ 必做 2:重装 userscripts

```bash
bash /Users/aim5/Documents/CodingProject/feishukanban-ob-sync/install.sh --apply --force
```

v0.3.4 起 userscripts 是 `cp + sed` 不是 symlink,**必须重跑 install**!然后 `Cmd+Q` 重启 Obsidian。

### 🧪 Part 2 验证 4 场景

1. **完整流程**:9 步全填(不选跳过)→ task md 8 个字段都对
2. **全跳过流程**:大类/小类/ADHD/DDL 全跳过 → 只有 priority + isToday + 标题 + 默认 month/week
3. **跨多月项目**:Step 6 多选 26 年 5 月 + 6 月 → frontmatter `iteration_month: [26 年 5 月, 26 年 6 月]`
4. **ADHD="有 DDL" + DDL 跳过**:弹警告 Notice + 允许继续

### ⚖️ Part 2 8 条原则自评

| # | 原则 | 表现 |
|---|---|---|
| 1 | 解耦 | ⭐⭐⭐⭐⭐ 大类/小类 数据源完全飞书侧,加项目只改飞书不改代码 |
| 2 | 可扩展 | ⭐⭐⭐⭐⭐ `--quickadd-options` 接口可加新选项(如 estimate_hours preset)不动 userscript 主流程 |
| 3 | 灵活修改 | ⭐⭐⭐⭐ 9 步顺序在 userscript 一处控制 |
| 4 | 渐进披露 | ⭐⭐⭐ 9 步偏多但每步都有「跳过」,实际可降到 6 步内 |
| 5 | 鲁棒性 | ⭐⭐⭐⭐⭐ Step 0 batch 失败 → 降级菜单跳过 / iteration 字段未配 → 跳过 / 飞书空 → 用本地 derive 默认 |
| 6 | 人可读 + 可教学 | ⭐⭐⭐⭐ JSDoc + 注释保留 v0.3.1/v0.3.3/v0.3.4 历史 |
| 7 | 高复用 + 易移植 | ⭐⭐⭐⭐ `link_table_active_field` 配置项让别人 clone 仓库后选用 |
| 8 | 工程化清晰 | ⭐⭐⭐⭐ Python ast + node --check 双语法校验 + 真飞书 cli smoke test |

## [v0.3.4] - 2026-05-27 — 修 __filename + dataview 跨天 两个 bug

> **2 个独立 bug fix 合并到同一版本号**(v0.3.2 / v0.3.3 修补)。
> Part 1:`__filename` 推导失败导致 4 个 Cmd+P 命令全部不可用(本次会话 01:00 实测发现)。
> Part 2:dataview 跨天完成 task "消失"bug(v0.3.4 主体)。

---

## Part 1:修 `__filename` bug(OB CC 跨边界例外修)

> **现象**:Cmd+P 跑「📝 快记任务 / 📥 拉今日 todo / ✅ 完成 task」全部报错:
> ```
> Command failed: python3 "/Applications/Obsidian.app/Contents/Resources/electron.asar/sync.py" ...
> can't open file '/Applications/Obsidian.app/Contents/Resources/electron.asar/sync.py': [Errno 2] No such file or directory
> ```

### 🐛 根因

v0.3.2 设计的"`__filename` 自适应"在 Obsidian QuickAdd userscript 上下文里**根本不成立**:

```js
// v0.3.2 写法(失败)
const syncScript = path.resolve(path.dirname(__filename), "..", "sync.py");
```

Node 的 `__filename` global 在 QuickAdd 加载 userscript 时**指向 Electron asar bundle 内部**(`/Applications/Obsidian.app/Contents/Resources/electron.asar/...`),**不是** vault 里 .js 的真实位置 → `path.resolve(..., "..", "sync.py")` 推出来是不存在的路径。

漏改 4 处:
- `quickadd-拉今日todo.js` line 34
- `quickadd-完成task.js` line 140
- `quickadd-快记任务-v2-task-md.js` line 113(Step 2.5 调 `--resolve-project` 查飞书子项目)
- `quickadd-快记任务-v2-task-md.js` line 308(Step 7 调 `--task-md` sync 飞书)

⚠️ 用户实测发现 v2 macro **小类(subcategory)二级菜单不出现**,根因就是 line 113 调用 sync.py 失败 → catch 走降级 → 跳过二级 suggester。

### 🛠 修法

`install.sh` 装的时候 `cp` + `sed` 注入 sync.py 绝对路径:

**1. userscript 用占位符**(3 个 userscript 4 处):
```js
// v0.3.4: install.sh 装的时候 sed 替换占位符为 sync.py 绝对路径
const syncScript = "__SYNC_PY_ABS_PATH__";
```

**2. install.sh Step 4 `ln -s` → `cp` + `sed`**:
```bash
cp "$js" "$target"
# macOS sed -i 需要 '' 参数(BSD sed)
sed -i '' "s|__SYNC_PY_ABS_PATH__|$SYNC_PY_ABS|g" "$target"
```

**Trade-off**:升级 `obsidian-assets/userscripts/*.js` 后需要重跑 `install.sh --force`(symlink 不自动跟着更新)。这是 install 工具的本意,可接受。

### 📝 改动文件

- `install.sh` Step 4(banner v0.3.3 → v0.3.4,Step 4 ln → cp + sed,+22 -7)
- `obsidian-assets/userscripts/quickadd-拉今日todo.js`(line 34 占位符)
- `obsidian-assets/userscripts/quickadd-完成task.js`(line 140 占位符)
- `obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js`(line 113 + line 308 两处占位符)

### ⚠️ 跨边界例外说明

本次 fix **OB Claudian 在 OB vault 跨边界改的独立仓库源码** — 经用户显式授权,按 [cross-project.md 2026-05-26 例外条款](https://github.com/wukongai/OB) 符合 3 条:
1. ✅ 服务对象唯一是 OB vault
2. ✅ 风险可控(本地未 push,可 reset)
3. ✅ 用户明确授权

**OB CC 做了**:edit 3 个 userscript + edit install.sh + 重跑 install.sh 重装 vault 内文件 + 4 个 Cmd+P 用户实测通过 + 写本 CHANGELOG 段 + 写反向回执(`docs/handoff/OB对接/2026-05-27-v0.3.4-__filename-修复-跨边界例外-反向回执.md`)+ git commit。

**OB CC 没做**:git push(留给独立 CC review + push)。

### ✅ 验证(用户实测通过 2026-05-27)

- ✅ ① 📝 快记任务:优先级 → 大类 → **小类二级菜单出现** → 是否今日 → 标题 → task md 创建 + 飞书 CREATE 成功
- ✅ ② 📥 拉今日 todo:同步成功(无 electron.asar 错)
- ✅ ③ ✅ 完成 task:frontmatter status:done + 飞书 UPDATE 成功
- ✅ ④ 🎯 同步今日 task 到飞书:Claudian 自动调起

---

## Part 2:修 dataview 跨天完成"消失"bug

> **现象**:用户在 27 日 journal 勾选 inline checkbox 完成 task → 该 task 立刻从 27 日 journal 消失,无法看到当天的完成情况。

### 🐛 根因

journal 模板的 dataview 过滤条件包含 `(!done_date OR done_date = this.file.day)`(或更早版本的 `(!completed OR completion = this.file.day)`),这个条件本意是"只显示当日完成的,过去日完成的不显示",但**副作用**:

- 当日 journal 看一个 task:`done_date = today` → 显示 ✓
- 26 日 journal 看一个 27 日才完成的 task(`today_history=[26,27]`,`done_date=2026-05-27`):`done_date(27) ≠ this.file.day(26)` → **消失 ❌**

跨天 task 在 26 日 journal 应该仍然可见(显示为 `- [x] ✅ 2026-05-27` 跨天完成态),用户复盘"那天看到什么"的语义被破坏。

### 🛠 修法

**完全移除 `done_date` / `completed` 过滤**,把范围控制全部交给 `today_history`(`sync.py --pull-today` 维护的"曾经是今日"日期数组)。完成状态由 inline `- [x] ✅ <date>` 自然渲染:

```dataview
TASK
FROM "04 Inbox/task"
WHERE !contains(file.name, "_说明")
  AND contains(today_history, this.file.day)
  AND (priority = "P0" OR priority = "P1" OR priority = "P2")
SORT priority ASC, created DESC
```

### 📝 改动文件

**Vault 端**(用户私域):
- `journals/2026-05-25.md` — 删旧字段 `(!completed OR completion = this.file.day)`(2 处 dataview block)
- `journals/2026-05-26.md` — 删新字段 `(!done_date OR done_date = this.file.day)`(2 处)
- `journals/2026-05-27.md` — 删旧字段 `(!completed OR completion = this.file.day)`(2 处)
- `03 Resources/素材库/模版/日志模版 5.0 1.md`(templater 主模板)— 删 done_date 过滤(2 处),防止以后创建的 journal 复发

**仓库端**(本 repo):
- `docs/tutorial/05-task-md-workflow.md` — 更新示例 dataview 块
- `obsidian-assets/rules/feishu-project-sync.md` — 更新示例 + TASK 查询语义说明段,记录历史教训

### ✅ 验证步骤(用户测)

1. 重新打开 `journals/2026-05-27.md`(刷新 dataview)
2. 看「🎯 今日计划」section,确认勾选完成的 task 仍显示成 `- [x] ✅ 2026-05-27`(不再消失)
3. 也可看 26 日 journal,确认 27 日才完成的 task 在 26 日也能看到完成态(跨天显示)

### ⚠️ 注意

- **该修复不动 sync.py**,只改 journal/template/docs 中的 dataview 查询语法
- 当 today_history 残留 ≠ 当日的日期时(如 task 早就完成但 today_history 没清),旧 journal 也会"反复"显示。这属于 `sync.py pull-today` 的 today_history 清理范畴(v0.3.0 已建立事件流机制),本次不重叠

## [v0.3.3] - 2026-05-27 — 强制北京时区(双层 defense in depth)

> **根因**:Mac 系统时区 = Asia/Shanghai,但 user shell `.zshrc` 设了 `export TZ=America/Los_Angeles`。Obsidian 从 shell 启动时继承这个 env,userscript `exec` 子进程时把 `process.env` 整体传给 sync.py → sync.py 的裸 `datetime.now()` 算成 PDT 时间(比北京晚 15-16h)。
>
> **实证**:
> ```
> $ TZ=America/Los_Angeles python3 -c "from datetime import datetime; print(datetime.now())"
> 2026-05-26 23:51:42       ← PDT 时间,算到了"昨天"
>
> $ python3 -c "from datetime import datetime, timezone, timedelta; print(datetime.now(timezone(timedelta(hours=8))))"
> 2026-05-27 14:51:42+08:00 ← 显式 UTC+8,正确
> ```
>
> **故障表现**:user 北京 5-27 早 09:26 用 Cmd+P 创建 task,task md 文件名 / `created` / `日志` 都是 5-27(userscript bjDate 公式与系统 TZ 无关,算对了),但 `today_history` 里被 sync.py 某次 pull-today / 反向 pull 流程 append 进了 5-26 → dataview 在 5-26 journal 误渲染该 task,5-27 journal 看不到。

### 🛡 块 ① — sync.py 3 处裸 `datetime.now()` 改为显式 UTC+8

| 行 | 函数 | 影响 |
|---|---|---|
| 656 | `feishu_doc_synced_at` 时间戳 | 飞书 doc 同步时间记录 |
| 844 | `sync_date`(delivery format 模板代入) | 交付字段格式化 |
| 2297 | `today`(老 `--pull` 反向流程的"今日" journal 位置) | 决定 task 写入哪份 journal |

写法统一:`datetime.now(timezone(timedelta(hours=8)))`。**已存在的 3 处(line 2603 / 2739 / 2792)在 v0.2.5 / v0.3.0 时已用显式 UTC+8,本次补齐剩下的 3 处**。

### 🚪 块 ② — 3 个 userscript exec env 强制 `TZ: "Asia/Shanghai"`

userscript `child_process.exec` 跑 sync.py 时,在 execEnv 加 `TZ: "Asia/Shanghai"`:

```js
const execEnv = {
  ...process.env,
  PATH: `${userPaths.join(":")}:${process.env.PATH || ""}`,
  TZ: "Asia/Shanghai",  // v0.3.3 加
};
```

涉及文件:
- `quickadd-快记任务-v2-task-md.js`(2 处:resolveCmd 的 execEnvEarly + syncCmd 的 execEnv)
- `quickadd-完成task.js`(1 处)
- `quickadd-拉今日todo.js`(1 处)

**defense in depth**:即使 user shell `.zshrc` 设了 `TZ=America/Los_Angeles`,userscript 启动 sync.py 子进程时强制覆盖为北京,sync.py 的裸 `datetime.now()`(如果还有遗漏)也会自动算北京。

### 🎯 这两层是 user 提出的「先行操作」原则落地

> 「创建文件的时候需要自动把时间转换成北京时间,这是先行操作而不是后续再修改,只要是 OB 调用 CC 创建文件都要先做这个转换。」

- **外层(先行)**:userscript exec 注入 `TZ=Asia/Shanghai` — 在 sync.py 启动前已经把时区"翻译"好了
- **内层(防御)**:sync.py 显式 UTC+8 — 即使有人裸命令行跑 sync.py(没经 userscript),仍然算北京

### ⚠️ 用户侧需要手动清理的残留数据

v0.3.3 修了**今后**的写入路径。已存在 task md 的 `today_history` 里残留的错误日期需要**手动 grep + 清理**。

诊断命令:
```bash
# 找所有 today_history 含跨日的 task md(可能有日期错配)
grep -l "today_history:.*,.*" /Users/aim5/Documents/OB/04\ Inbox/task/
```

逐个 open,看 `today_history` 是不是真的应该是多日(比如 task 跨好几天都聚焦过),还是 v0.3.3 之前的时区 bug 残留(单日 task 却有相邻两天)。

### 🔧 升级路径

1. `git pull` 拉 v0.3.3
2. **重装 UserScripts**:`bash install.sh --apply --force`(覆盖 vault 里的 4 个 userscripts/*.js)
3. **重启 Obsidian**(QuickAdd 重新加载 userscripts;新 exec env 才生效)
4. 清理已存在 task md 的 `today_history` 残留(见上)

### ⚖️ 8 条原则自评

| # | 原则 | 本次表现 |
|---|---|---|
| 1 | 解耦 | ⭐⭐⭐⭐⭐ 用户 shell TZ 设置 vs. 工具行为完全解耦 |
| 2 | 可扩展 | ⭐⭐⭐⭐⭐ 显式时区写法,后续加新 datetime 调用可复制 pattern |
| 3 | 灵活修改 | ⭐⭐⭐⭐ 双层修复,各自独立可单独回滚 |
| 4 | 渐进披露 | ⭐⭐⭐ user 不需要知道时区机制就能跑;高级 user 看 CHANGELOG 知道为啥 |
| 5 | 鲁棒性 | ⭐⭐⭐⭐⭐ 外层(userscript) + 内层(sync.py) 双保险,任一层失效另一层兜底 |
| 6 | 人可读 + 可教学 | ⭐⭐⭐⭐⭐ CHANGELOG 完整故障路径 + 实证 shell 输出 |
| 7 | 高复用 + 易移植 | ⭐⭐⭐⭐ `TZ=Asia/Shanghai` 是 POSIX 标准,跨 mac/linux/wsl |
| 8 | 工程化清晰 | ⭐⭐⭐⭐ 验证脚本(`TZ=PDT python3 -c "..."`)收录 CHANGELOG |

---

## [v0.3.2] - 2026-05-26 — symlink 路径自适应 + install.sh `--scripts-dir` + sync.py VAULT_ROOT bug 修复

> 三块 patch:userscript `__filename` 自适应、install.sh `--scripts-dir` flag、sync.py `VAULT_ROOT` 跟错位置修复。配 OB 端 handoff 在 vault 内迁移 symlink 到「统一外部工具」位置,解决用户"vault 整洁"诉求。

### 🎯 块 ① — userscript 路径自适应(`__filename` 推导)

#### 问题

3 个调 `sync.py` 的 userscript 都硬编码 `${vaultRoot}/scripts/feishukanban-ob-sync/sync.py`,把"装在 vault 哪"和"代码"耦合。用户想把 symlink 搬到别处统一管理 → userscript 必须跟着改 → 等于每次路径迁移都是 breaking。

#### 修复

把硬编码替换为 `path.resolve(path.dirname(__filename), '..', 'sync.py')`,用 Node.js `__filename` 推导 sync.py 真实位置。

**约定**:install.sh 必须把 sync.py 装在 userscripts/ 的**上一级**(同 `SCRIPTS_TARGET` 父目录),这是 install.sh 既有行为,无破坏。

#### 涉及文件

- `obsidian-assets/userscripts/quickadd-拉今日todo.js`(1 处)
- `obsidian-assets/userscripts/quickadd-完成task.js`(1 处)
- `obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js`(2 处:resolveCmd + syncCmd)
- 不动 `quickadd-同步飞书项目.js`(它走 Claudian skill,不调 sync.py)

#### 收益

**以后再迁移 symlink 路径,userscript 一行不用改**。彻底消除 vault 内位置 ↔ userscript 代码 的耦合。

---

### 🛠 块 ② — install.sh 加 `--scripts-dir <vault-rel-path>` flag

#### 问题

`install.sh` 把 `SCRIPTS_TARGET="$VAULT/scripts/feishukanban-ob-sync"` 写死,用户私域结构(如 `01 Project/00 进行中/06 小工具开发/...`)装不进去,只能装到 vault 根的 `scripts/` 目录。

#### 修复

加 `--scripts-dir <vault-relative-path>` flag,默认值 `scripts/feishukanban-ob-sync`(开源友好,不改默认就是 v0.3.1 行为)。Step 3 / Step 4 / Step 6 QuickAdd choices JSON / Step 7 config.yaml 提示路径**全部跟随 `--scripts-dir`**。

```bash
# 开源默认(老用户拉新版无感)
./install.sh --apply

# 装到 vault 私域位置(用户自定义)
./install.sh --apply --scripts-dir "01 Project/00 进行中/06 小工具开发/feishukanban-ob-sync"
```

输入清洗:去掉前后多余的 `/`,接受 `foo/bar` / `/foo/bar` / `foo/bar/` 等格式。

#### 配套

`.quickadd-choices.json`(install.sh 输出)的 4 个 `path` 字段自动跟随新 `SCRIPTS_DIR`,用户复制到 `data.json` 就是对的。

---

### 🐛 块 ③ — sync.py `VAULT_ROOT` bug 修复

#### 问题(隐藏 bug,实际跑了很久)

sync.py 第 60 行(原):
```python
VAULT_ROOT = SCRIPT_DIR.parents[4]
```

假设 sync.py 在 `OB/01 Project/00 进行中/06 小工具开发/CC命令/飞书项目同步/sync.py`(parents[4] = OB)。

**实际情况**(v0.2.x 起):sync.py 是 symlink → 仓库,`Path(__file__).resolve()` 跟符号链接跳到 `/Users/aim5/Documents/CodingProject/feishukanban-ob-sync/sync.py`,`parents[4]` = `/Users/aim5/`(完全错的 vault 根)。

**为什么没爆**:userscripts 都通过 `--vault` 显式传 vault 路径,sync.py 主流程用 `os.chdir(vault_path)` + 相对路径,绕开了这个全局变量。但 line 797 / 1814 / 1960 三处 `build_fields_payload` 调用链用的还是错的 `VAULT_ROOT`——**C 路径 backlinks** 拼绝对路径时会找错位置(用户未碰到,但属于潜在数据 bug)。

#### 修复

```python
# 新:初始 = cwd,main() 处理 --vault 后刷新
VAULT_ROOT = Path.cwd()

# main() 里 chdir 之后:
global VAULT_ROOT
VAULT_ROOT = vault_path
```

dry-run 跑 `--pull-today` 验证无回归(扫了 34 个 task md,7 条今日全对齐)。

---

### 🔧 升级路径

**代码层(老用户拉 v0.3.2)**:
1. `git pull`
2. **不需要**重新跑 install.sh(userscript 自适应化,旧 symlink 位置照样工作)
3. 重启 Obsidian(QuickAdd 重新加载 userscripts)

**vault 整洁(可选,用户要求"统一外部工具")**:
1. 等 OB CC 执行 `docs/handoff/OB对接/2026-05-26-symlink路径自适应-handoff.md`
2. OB CC 选定新路径,跑 `install.sh --scripts-dir <新路径> --apply --force`
3. 删旧 `scripts/feishukanban-ob-sync/` 目录(install.sh 不自动删,手动 `rm -rf`)
4. 改 `.obsidian/plugins/quickadd/data.json` 4 个 choice path 字段(install.sh 输出的 snippet 已经是新值)
5. 重启 Obsidian,测 4 个 Cmd+P 命令

---

### ⚖️ 8 条原则自评

| # | 原则 | 本次表现 |
|---|---|---|
| 1 | 解耦 | ⭐⭐⭐⭐⭐ userscript 不再依赖 install.sh 装在哪;install.sh 不再依赖 userscript 路径硬编码 |
| 2 | 可扩展 | ⭐⭐⭐⭐⭐ `--scripts-dir` 留出扩展点,装到 vault 任意位置都行 |
| 3 | 灵活修改 | ⭐⭐⭐⭐⭐ 路径迁移成本从"改 6 个文件"降到"跑一次 install.sh + 手改 data.json" |
| 4 | 渐进披露 | ⭐⭐⭐⭐ 开源用户默认值无感;高级用户用 flag |
| 5 | 鲁棒性 | ⭐⭐⭐⭐ `__filename` 即使返回 symlink 真实路径(仓库内位置)也能跑通——sync.py 在仓库就在 userscripts 上一级,功能不破 |
| 6 | 人可读 + 可教学 | ⭐⭐⭐⭐ 注释解释了"为什么 __filename 自适应能避免硬编码";handoff 文档全流程清晰 |
| 7 | 高复用 + 易移植 | ⭐⭐⭐ Node 标准 + bash 标准,跨平台无障碍 |
| 8 | 工程化清晰 | ⭐⭐⭐⭐ install.sh dry-run 验证 + sync.py CLI 验证,handoff 文档约定回执流程 |

---



> 四块 patch 合并:`--vault` CLI 参数、`inject_completion_link`、`pull-today` today_history 残留清理、`快记任务` 跨日 dateContext(OB handoff 移交)。

### 🎯 块 ① — `--vault` 参数 + 项目级 settings.json

#### 问题背景

Claude Code 在跑 `cd /Users/aim5/Documents/OB && python3 .../sync.py --pull-today` 这类命令时,**每次都弹 permission 授权窗** — 哪怕给 `Bash(python3:*)` 开了 allow 也没用。根因:Claude Code 的 allowlist 是**前缀匹配**,`cd` 开头会绕过所有 allow 规则。

#### sync.py 新增 `--vault <path>` 参数

```bash
# 新写法(命令开头是 python3,allowlist 友好)
python3 /path/to/sync.py --vault /Users/aim5/Documents/OB --pull-today

# 老写法仍然可用(从 vault 内任意子目录跑,自动找 .obsidian/)
cd /Users/aim5/Documents/OB && python3 /path/to/sync.py --pull-today
```

实现细节:`main()` 最开头若收到 `--vault`,校验 `.obsidian/` 存在后 `os.chdir(vault_path)`,其余代码完全不动 — **100% 向后兼容**,不传 `--vault` 时行为完全等价于 v0.3.0。

#### 4 个 UserScript 同步更新

`quickadd-拉今日todo.js` / `quickadd-完成task.js` / `quickadd-快记任务-v2-task-md.js`(2 处)从 `cd "${vaultRoot}" && python3 "${syncScript}" ...` 改为 `python3 "${syncScript}" --vault "${vaultRoot}" ...`。颗粒度统一,去除对 cwd 的隐式依赖。

#### 新增项目级 `.claude/settings.json`

allow 本项目实际会用到的命令(python3 / pip3 / feishu-cli / 常见 git 子命令 / 只读工具),deny 危险操作(force push / reset --hard / 写 config.yaml)。其他 CC 用户 clone 仓库后开箱即用,无需各自重复授权。

---

### 🔗 块 ② — `inject_completion_link`:完成段裸 checkbox 自动转带链 markdown

#### 问题

`task 模版.md` 的「## ✅ 完成标记」段写了 `- [ ] <title>`,UserScript 文案说"sync 后自动改为带飞书 record URL 的链接",但 sync.py 此前**没实际实现**这一步。结果 dataview TASK 渲染时看不到点击直达飞书的链接。

#### 实现

新增 `inject_completion_link(md_path, title, record_url) -> bool` 函数,在 `push_task_md` CREATE 流程末尾调用:
- 找「## ✅ 完成标记」H2 段标题
- 该段下第一个 `- [ ]` / `- [x]` checkbox 行
- 行 body 替换为 `[<原 body>](record_url)`,变成 dataview 可点击 link
- 幂等:已是 `[text](url)` 形式 → 不动;UPDATE 流程不触发(行可能已被用户手改)

---

### 🧹 块 ③ — `pull-today`:today_history 残留清理

#### 问题

v0.3.0 的 `today_history` append-only 设计有一个未覆盖场景:
- 用户飞书勾「是否今日」→ sync.py set OB `today=true` + append `today_history`
- 用户飞书取消「是否今日」→ sync.py set OB `today=false`,**但 today_history 仍含今日**
- journal dataview 用 `contains(today_history, this.file.day)` → 任务仍渲染在今日 journal
- 用户期望:取消今日 = 今日 journal 不再显示

#### 实现

`_scan_ob_task_md_by_feishu_record` 抽取 `today_history` 字段;`pull_today_from_feishu` 的 `plan_set_false` 触发条件改为 `entry["today"] OR (今日 in today_history)` — 当 OB today_history 含今日但飞书取消今日时,也走 set_false(并清理 today_history 中的今日,若实现细节如此)。`_scan` 返回字典加 `today_history: list[str]` 字段。

> 注:本块完整 spec 详见 sync.py 函数内注释,本 CHANGELOG 主要给版本对齐用。

---

### 🕐 块 ④ — `快记任务`:跨日 dateContext(OB handoff 移交)

#### 问题

Mac 系统时区 `America/Los_Angeles` + 用户在北京工作的跨日场景:
- PDT 5-26 晚 18:26 = 北京 5-27 早 09:26
- 用户在 `journals/2026-05-26.md` 工作(心理上还在 5-26)
- 跑 Cmd+P「📝 快记任务」 → userscript 用 `bjDate` = `2026-05-27`
- 新 task 文件名 `2026-05-27-xxx.md`,frontmatter `today_history: [2026-05-27]`,`日志: [[journals/2026-05-27]]`
- 用户当前 journal(5-26) dataview 查 `contains(today_history, "2026-05-26")` → false → **task 不显示,体验上"消失"**

#### 实现

`obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js` 顶部加 `getDateContext(app)` helper:
- 当前 active file 是 `journals/YYYY-MM-DD.md`(严格正则)→ 用 journal 日期
- 其他场景(task md / 任意 md / 无 active file)→ fallback 北京时间(原 bjDate 行为)

Step 4 把 `bjDate` 替换为 `dateContext`(影响:文件名前缀 / `日志:` wikilink / `today_history` 初值);新增 `createdISO = ${dateContext}T${bjISO.slice(11)}` 替代 `bjISO` 写入 `created` 字段(日期跟随上下文,时间部分始终北京时间,跨工程时间戳一致)。

#### 边界

- 用户在 `journals/2026-05-26.md` → `dateContext = "2026-05-26"`
- 用户从 task md / Inbox / 任意 md 触发 → `dateContext = bjDate`
- Obsidian 启动后直接 Cmd+P(无 active file)→ `dateContext = bjDate`
- 非标准命名 journal(如 `journals/detail/2026-05-26 周二.md`)→ 不匹配正则 → fallback bjDate(保守行为)

详见 `docs/handoff/OB对接/2026-05-26-userscript-跨日-handoff.md`。

---

### 🔧 升级路径(全部四块统一升)

老用户拉了 v0.3.1 后需要:
1. `git pull`(只动 sync.py / userscript / settings.json,不动 config.yaml)
2. **重装 UserScripts**:`bash install.sh --apply --force`(覆盖 vault 里的 4 个 userscripts/*.js)
3. 重启 Obsidian(QuickAdd 重新加载 userscripts)
4. 重启 Claude Code(项目级 settings.json 在会话启动时加载)
5. 新建 task md 验证:`inject_completion_link` 是否把「✅ 完成标记」段裸 checkbox 自动改成带链 link
6. 飞书勾今日 → 跑 `python3 sync.py --vault /OB --pull-today --apply` → 再取消飞书今日 → 再跑一次 → 验证 today_history 中的今日被清,journal 不再渲染
7. 跨日测试:在 `journals/<昨天>.md` 中跑 Cmd+P「📝 快记任务」 → 验证新 task 文件名前缀 / `today_history` / `日志` 都是「昨天」日期

### 📊 已知 follow-up

- sync.py line 180 有个 `\s` regex SyntaxWarning(无功能影响),P3 修
- `scan_vault_record_ids` (老 `--pull` 流程)的 `vault_root = Path(".")` 仍是 hard-code,但因 `--vault` 已 chdir,实际行为正确;P3 改成 `find_vault_root()`

---

## [v0.3.0] - 2026-05-26 — **今日聚焦历史保真:`today_history` 事件流**

### 🎯 问题背景

v0.2.0 用 `today: true/false` 单字段管理"是否今日"。痛点:**全局 single source of truth,改 1 次影响所有历史 journal**。场景:
- 5/26 标 today=true,做了一半
- 5/27 早上飞书取消「是否今日」+ `sync.py --pull-today` → OB today=false
- 回看 5/26 journal,dataview 查 `WHERE today=true` → **task 消失**,历史丢失

dataview 是实时投影,无法做"时间穿越"。

### ✨ 解决方案:事件流持久化

task md frontmatter 新增 `today_history` 字段(YAML inline list,append-only,去重):

```yaml
today: false                  # 当前状态(动态)
today_history:                # 事件流:曾经 today=true 的日期列表
  - 2026-05-26
  - 2026-05-27
```

dataview 查询改为 `contains(today_history, this.file.day)` → **5/26 journal 永远显示曾经在 5/26 聚焦过的 task**,不论后续 today 字段如何变化。

### 🔧 实施细节

#### sync.py 改动

1. **`_format_yaml_value`** 加 list 支持(`[a, b, c]` inline 格式),底层 enabler 让 `update_md_frontmatter` 能写 list 字段
2. **`pull_today_from_feishu`** 在 set OB today=true 时,read 当前 today_history → append 当日(去重)→ 一次性 update both fields
3. **`_create_task_md_from_feishu_record`**(`--pull-today --apply` 自动建 task md 时)初始化 `today_history: [{today_date}]`
4. **设 today=false 时**:**不动 today_history**(历史保留)

#### Obsidian assets 改动

- **`quickadd-快记任务-v2-task-md.js`**:创建 task md 时 init `today_history: []`(空 list,等用户飞书勾今日时 sync.py 自动 append)

### 🔄 OB 端配套(独立改动)

OB CC 同步改:
- **task md 模板**(`03 Resources/素材库/模版/task 模版.md`)加 `today_history` 字段定义
- **journal 模板 + 今日 journal**:「🎯 今日计划」+「🐿️ 今日非计划」dataview 查询从 `today = true` 改为 `contains(today_history, this.file.day)`
- **历史 task 批量 backfill**:扫 12 个 today=true 的 task md,根据 created 日期 init today_history
- **rules 更新**(`feishu-project-sync.md`「今日 todo 双层架构」section 加事件流持久化说明)

### 📐 设计要点

- **append-only**:取消 today 不删除历史(允许"曾经"语义)
- **去重**:同一天反复设 today=true 只 append 1 次
- **类型安全**:`_format_yaml_value` 递归处理 list 元素,纯日期 → 无引号,符合 dataview 类型推断
- **向后兼容**:无 today_history 字段的旧 task md → `contains` 返回 false → 不显示(自然降级,需 backfill 或 sync.py 自动维护)

### 🆙 升级路径(OB 端)

1. 拉新版 sync.py(symlink 用户自动同步)
2. 跑一次 `sync.py --pull-today --apply` → 所有飞书侧 today=true 的 task 自动 init today_history
3. 历史 task 跑 backfill 脚本(参考 OB CC 实施记录)
4. 模板 + journal 模板 + 今日 journal 改 dataview 查询条件

### 🐛 已知边界

- task md 创建时 today_history=[],只有走过 `sync.py --pull-today` 才会 append。如果用户跳过 sync 直接手敲 `today: true` → today_history 不变,需手动维护或下次 pull-today 自动修复
- dataview `contains([2026-05-26], this.file.day)` 当 list 元素为 string 时,this.file.day 是 date 对象,dataview 内部做类型匹配(实证可行)

---

## [v0.2.0] - 2026-05-26 — **task md 化架构 + 完整工作流 + 一键部署**

### 🎯 重大架构升级 — task 升级为 "first-class entity"

v0.1 是 inline 子弹笔记式(`- [ ]` 在 journal 内,emoji 元数据),v0.2 把每个 task 升级为**独立 md 文件**,frontmatter ↔ 飞书 20 字段 **1:1 对齐**:

- 每个 task = `04 Inbox/task/YYYY-MM-DD-<标题>.md` 独立笔记
- frontmatter 18 字段:`priority` / `status` / `today` / `category` / `subcategory` / `adhd_priority` / `estimate_hours` / `feishu_record` / `feishu_url` / `iteration_week` / 等
- 正文 5 个 H2 段:`📝 执行概述` / `✅ 验收条件` / `💡 执行思路` / `🔗 相关资料` / `🪞 复盘`
- 跨日全景视图 — `_task.base` 6 个视图(🎯今日计划 / 🐿️今日非计划 / 🔥待抢救 / ⏰有 DDL / ✅已完成 / 📋全部)

### ✨ 新增功能

#### 1. 🎯 三大工作流场景全闭环

| 场景 | 工作流 | 触发 |
|------|--------|------|
| ① **OB 创建 task → 飞书** | 弹优先级 → 输标题 → 自动 CREATE 飞书 record | Cmd+P 「📝 快记任务」 |
| ② **飞书今日 todo → OB 日志** | 飞书 app 勾「是否今日」=true → 拉到 OB today journal 渲染 | Cmd+P 「📥 拉今日 todo」 |
| ③ **自动统计今日工作** | git commit + 文件改动 → LLM 归纳为主题 → 写日志 + batch CREATE 飞书 | Claudian 对话关键词 |

#### 2. ⌨️ 4 个 QuickAdd UserScript(Cmd+P 入口)

存放于 `obsidian-assets/userscripts/`:
- `quickadd-快记任务-v2-task-md.js` — 场景 ①(主入口,2026-05-25)
- `quickadd-拉今日todo.js` — 场景 ②(2026-05-26)
- `quickadd-完成task.js` — task 完成 + sync 飞书一键闭环(2026-05-26)
- `quickadd-同步飞书项目.js` — 批量 sync(走 dry-run + 审批)

#### 3. 🔧 `sync.py` 新增 `--task-md` 和 `--pull-today` 模式

```bash
# task md 模式(2026-05-25):单条 task md 推送飞书 CREATE/UPDATE
python3 sync.py --task-md path/to/task.md --apply

# 今日 todo 同步(2026-05-26):飞书「是否今日」=true → OB frontmatter today=true
python3 sync.py --pull-today --apply
```

#### 4. 🤖 `auto_collect_today.py` helper(场景 ③)

`scripts/auto_collect_today.py` — 扫今日 git commits + vault 文件改动,输出 JSON 给 LLM 归纳。

#### 5. 🚀 `install.sh` 一键部署

新用户从 0 到能用的 onboarding 从 30 分钟降到 5 分钟:
- 自动 symlink scripts 到 vault
- 复制 templates / base / rules 模板到 vault
- 生成 QuickAdd choices JSON snippet 让用户粘贴

### 🔴 铁律 #1 飞书例外扩展(3 种自动 apply 场景)

| 场景 | 触发 | 操作类型 | 风险 |
|------|------|--------|------|
| 单条 CREATE 新 task | Cmd+P「📝 快记任务」 | CREATE | 空 record,无覆盖 |
| 单条 UPDATE 完成 task(新) | Cmd+P「✅ 完成当前 task」 | UPDATE | 只改 status/done_date |
| pull-today 同步 today 字段(新) | Cmd+P「📥 拉今日 todo」 | UPDATE OB frontmatter | 不写飞书,无破坏 |

### 🗂 obsidian-assets/(新增整套 OB 资产)

```
obsidian-assets/
├── userscripts/   (4 个 QuickAdd UserScripts)
├── templates/     (task 模版)
├── base/          (_task.base 6 视图)
└── rules/         (feishu-project-sync.md 主规则)
```

### 📚 文档大幅扩充

- `docs/ARCHITECTURE.md`(新)— 系统架构 + 数据流图
- `docs/feishu-schema.md`(新)— 飞书表 22 字段定义 + 一键创建命令
- `docs/tutorial/05-task-md-workflow.md`(新)— v0.2 主流程教程

### ⚠️ Breaking Changes(v0.1 → v0.2)

- **配置文件结构变化**:`config.yaml` 加 `task_md_fields` section(原 `fields` section 不变)
- **新增飞书字段依赖**:必须先用 `feishu-cli bitable field create` 加「是否今日」字段(参考 `docs/feishu-schema.md`)
- **老 `--pull` 模式标记 legacy**:仍可用,但建议改用 `--pull-today`(写到 task md frontmatter 而不是 journal inline)

### 🛠 修复

- `_format_yaml_value` 加 boolean 支持(原 `str(True)` = "True" 大写,改为 "true" 小写,符合 YAML 标准 + dataview 解析)

---

## [v0.1.0] - 2026-05-19 — **初版开源**

### 核心功能

- `sync.py`:OB journal task ↔ 飞书 record 双向同步
  - 正向 sync:OB 勾 [x] → 飞书自动填字段
  - 反向 pull:飞书「是否今日」→ OB 日志写 inline
  - 短链自动反查 + record_id O(1) cache
  - 字段映射 yaml 配置驱动
- 4 篇 tutorial(`docs/tutorial/01-04`)
- skill-claude-code.md(让 Claude Code 用户一键调用)
- 完整 README + INSTALL(30 分钟新手 onboard)

### 关键 bug 修复(对比内部版本)

- `inject_url_into_line` 保留所有 emoji 到行尾(原正则只匹配第一个 emoji 前空白)
- base URL 替代 wiki 长链(wiki SDK + bitable SDK iframe race condition 修复)
- 短链自动反查机制(用户不再需要管短链/长链转换)

---

## 设计哲学

详见 `docs/ARCHITECTURE.md`「8 条架构原则反向打分」section。
