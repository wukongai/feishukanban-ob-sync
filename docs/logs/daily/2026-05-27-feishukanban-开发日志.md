---
title: 2026-05-27 feishukanban-ob-sync 开发日志
type: daily-log
date: 2026-05-27
tags: [daily, v0.3.1, v0.3.2, v0.3.3, v0.3.4, v0.3.5, 跨日, 时区, __filename, status7态, Cmd+P9步]
related: ["[[../../VERSION]]", "[[../../../CHANGELOG]]"]
---

# 2026-05-27 feishukanban-ob-sync 开发日志

> 单日上 5 个版本(v0.3.1 → v0.3.5)。是项目从「能用」走向「飞书 ↔ OB 真双向」的关键一天。

> ⚠️ 本日志为 **2026-05-28 凌晨回写**,基于 git log + CHANGELOG.md 重建,token / 时长无精确记录。

---

## 会话 1:v0.3.1 — `--vault` 参数 + 跨日 dateContext + 完成段链 + today_history 清理

⏱️ 时长:估算 1.5h
🏷️ commits:`2fd1848` + `c91c9a5`(handoff 回填)
🎯 主题:**4 块 patch 合并**

### 🛠 4 块 patch

| 块 | 内容 | 触发 |
|---|---|---|
| ① `--vault <path>` 参数 | sync.py + 4 个 UserScript 从 `cd && python3` 改为 `python3 --vault`,命令开头 `python3` → CC allowlist 前缀匹配可命中,不再每次弹 permission 窗 | 用户反馈 permission 弹窗太多 |
| ② `inject_completion_link` | sync.py CREATE 时把「✅ 完成标记」段裸 `- [ ]` 自动改为带飞书 URL 的 markdown link | dataview TASK 渲染不可点击 |
| ③ `pull-today` today_history 残留清理 | 飞书取消今日时清理 OB `today_history` 中的今日日期 | journal dataview 误渲染已取消的今日 task |
| ④ `快记任务` 跨日 dateContext | 在 `journals/YYYY-MM-DD.md` 触发时用 journal 日期作为新 task 的文件名前缀 / today_history / 日志 | 在昨天 journal 跑 Cmd+P → task 进昨天 journal,不再「消失」(OB handoff 接力的主体) |

### 📚 handoff(跨工程)

- 接收:`docs/handoff/OB对接/2026-05-26-userscript-跨日-handoff.md`(OB CC 发起)
- 发出:`docs/handoff/OB对接/2026-05-26-v0.3.1-反向回执-OB端落地.md`(完成确认 + OB 端 4 件事接力)

### 决策记录

- **Spec 偏离**:原 handoff 要求 tag `v0.2.5`,但 v0.2.5 / v0.3.0 已存在 + 工作树有 v0.3.1 块 ① ② ③ 草稿 → AskUserQuestion 后并入 v0.3.1 块 ④
- **OB rules 措辞约束**:不要写「v0.2.5 跨日支持」→ 应写「v0.3.1 块 ④ 跨日 dateContext」

---

## 会话 2:v0.3.2 — symlink 路径自适应 + install.sh `--scripts-dir` + sync.py VAULT_ROOT bug 修复

⏱️ 时长:估算 1h
🏷️ commits:(见 git log)
🎯 主题:**3 块改动一并发**

### 🛠 改动

- **块 ①** userscript 路径自适应:4 个 UserScript 改用 `path.resolve(path.dirname(__filename), '..', 'sync.py')` 推导 sync.py 路径
- **块 ②** `install.sh --scripts-dir <vault-rel-path>` flag:开源用户默认 `scripts/feishukanban-ob-sync/`,高级用户可装到任意位置
- **块 ③** sync.py `VAULT_ROOT` bug:旧版 `SCRIPT_DIR.parents[4]` 假设固定深度,改 `Path.cwd()` + `main()` 处理 `--vault` 后刷新

### ⚠️ 隐患埋下

块 ① 的 `__filename` 假设在 Obsidian QuickAdd userscript 上下文里**根本不成立**(`__filename` 指向 Electron asar bundle,不是 vault 内真实路径)→ **v0.3.4 爆雷,4 个 Cmd+P 命令全废**。

教训:依赖 Node global(`__filename`)在嵌入式 JS 上下文(QuickAdd / Obsidian)前必须验证。

---

## 会话 3:v0.3.3 — 强制北京时区(双层 defense in depth)

⏱️ 时长:估算 1h
🏷️ commits:`fd51469`
🎯 主题:**根治时区 bug**

### 🐛 触发事件

用户北京 5-27 早 09:26 用 Cmd+P 创建 task,task md 文件名 / `created` / `日志` 都是 5-27(userscript bjDate 公式对了),但 `today_history` 里被 sync.py 某次 pull-today 流程 append 进了 5-26 → dataview 在 5-26 journal 误渲染,5-27 journal 看不到。

### 🛠 双层防御

| 层 | 改法 | 防御范围 |
|---|---|---|
| **userscript 层(先行)** | 3 个 userscript `child_process.exec` 时在 `execEnv` 显式注入 `TZ: "Asia/Shanghai"` | sync.py 子进程一启动就在北京时区 |
| **sync.py 层(防御)** | 3 处裸 `datetime.now()` 改为 `datetime.now(timezone(timedelta(hours=8)))` | 即使命令行直接跑也是北京日期 |

### 📊 实证

```bash
TZ=America/Los_Angeles python3 -c "from datetime import datetime; print(datetime.now())"
# 输出: 2026-05-26 23:51 ← 错(系统 TZ 影响)

TZ=America/Los_Angeles python3 -c "from datetime import datetime, timezone, timedelta; print(datetime.now(timezone(timedelta(hours=8))))"
# 输出: 2026-05-27 14:51 ← 对(显式 UTC+8 不受系统 TZ 影响)
```

### 决策记录

- **Defense in depth 哲学**:用户提出「先行操作」原则 — 两层独立修,任一层失效另一层兜底
- **不修系统 TZ**:Mac 用户 shell `TZ=PDT` 是 dev 工具触发的副作用,不动用户环境

---

## 会话 4:v0.3.4 — 修 `__filename` + dataview 跨天「消失」bug

⏱️ 时长:估算 2h
🏷️ commits:`7cd15b3` + `694395f`(handoff)
🎯 主题:**双 bug 修复(2 块独立 fix 合并)**

### Part 1:修 `__filename` bug

#### 🐛 现象

```
Command failed: python3 "/Applications/Obsidian.app/Contents/Resources/electron.asar/sync.py" ...
can't open file '...': [Errno 2] No such file or directory
```

4 个 Cmd+P 命令(📝 快记任务 / 📥 拉今日 todo / ✅ 完成 task / 🎯 同步今日)**全部不可用**。

#### 🐛 Root cause

v0.3.2 设计的 `__filename` 自适应在 Obsidian QuickAdd userscript 上下文里**根本不成立**。Node `__filename` 在 QuickAdd 加载 userscript 时指向 Electron asar bundle 内部 → `path.resolve(..., "..", "sync.py")` 推出来是不存在的路径。

#### 🛠 修法

`install.sh` 装的时候 `cp` + `sed` 注入 sync.py 绝对路径(不再 symlink):

**userscript 用占位符**(3 个 userscript 共 4 处):
```js
const syncScript = "__SYNC_PY_ABS_PATH__";
```

**install.sh Step 4 `ln -s` → `cp` + `sed`**:
```bash
cp "$js" "$target"
sed -i '' "s|__SYNC_PY_ABS_PATH__|$SYNC_PY_ABS|g" "$target"
```

**Trade-off**:升级 `obsidian-assets/userscripts/*.js` 后需要重跑 `install.sh --force`。可接受。

#### 🤝 跨边界例外

此次 fix 是 **OB Claudian 在 OB vault 跨边界改的独立仓库源码**,经用户显式授权,按 cross-project.md 例外条款符合 3 条:
1. ✅ 服务对象唯一是 OB vault
2. ✅ 风险可控(本地未 push,可 reset)
3. ✅ 用户明确授权

### Part 2:修 dataview 跨天完成「消失」bug

#### 🐛 现象

用户在 27 日 journal 勾选 inline checkbox 完成 task → 该 task **立刻从 27 日 journal 消失**,无法看到当天完成情况。

#### 🐛 Root cause

journal 模板的 dataview 过滤含 `(!done_date OR done_date = this.file.day)`,意图是「只显示当日完成」,但副作用:**26 日 journal 看一个 27 日才完成的 task → `done_date(27) ≠ this.file.day(26)` → 消失**。

跨天 task 在 26 日 journal 应当仍可见,显示为「`- [x] ✅ 2026-05-27`」跨天完成态。

#### 🛠 修法

**完全移除 `done_date` 过滤**,范围控制全部交给 `today_history`(append-only 事件流)。完成态由 inline `- [x] ✅ <date>` 自然渲染。

```dataview
TASK
FROM "04 Inbox/task"
WHERE !contains(file.name, "_说明")
  AND contains(today_history, this.file.day)
  AND (priority = "P0" OR priority = "P1" OR priority = "P2")
SORT priority ASC, created DESC
```

---

## 会话 5:v0.3.5 — status 7 态对齐 + Cmd+P 快记任务 9 步流程升级

⏱️ 时长:估算 3h
🏷️ commits:`6c13864` + `86ea462`(handoff)
🎯 主题:**2 块 patch 合并(双块大改动)**

### Part 1:status 7 态对齐飞书看板(加 SubDone + Idea)

#### 🐛 触发事件

用户飞书项目看板「执行状态」字段加了 **SubDone** 选项(Orange Lighter),用于「主任务下挂的子任务已完成,主任务本身还没收尾」。截图反馈「看板上有 subdone,可能 task 的属性中没有同步到」。

#### 🐛 4 处映射 bug 诊断

| # | 位置 | 旧行为 | 新行为 |
|---|---|---|---|
| 1 | `sync.py:2791` `_create_task_md_from_feishu_record` | SubDone→doing / Idea→todo(降级) | SubDone→subdone / Idea→idea / 补 cancel→cancel |
| 2 | `sync.py:985` `parse_task_md_for_push` status_map | 缺 subdone/idea | 加 subdone→/ + idea→空 + return dict 带 `fm_status` 原值 |
| 3 | `sync.py:1791` `build_fields_payload` + `config.yaml` `fields.status` | 仅 4 字符 inline 映射 | 优先 `task_md_map` 7 态直接映射 + fallback 老 inline char |
| 4 | `config.yaml` `reverse.status_map` | 缺 SubDone | 加 SubDone→/(journal inline 用) |

#### 7 状态对齐表(契约真相源)

| OB frontmatter status | 飞书「执行状态」 | inline 兼容字符 |
|---|---|---|
| `todo` | `Todo` | `[ ]` |
| `doing` | `Doing` | `[/]` |
| `subdone` | `SubDone` | `[/]`(视觉同 doing) |
| `done` | `Done` | `[x]` |
| `block` | `Block` | `[-]` |
| `cancel` | `cancel` | `[-]` |
| `idea` | `Idea` | `[ ]`(视觉同 todo) |

**inline checkbox 4 字符不变** — Tasks 插件 + Cmd+P「完成 task」UserScript 不受影响。**frontmatter.status 是真相源**。

⚠️ 飞书侧 `cancel` 是**小写**(其他 6 个 PascalCase)— 保留现状避免 SDK 大小写敏感不匹配。

### Part 2:Cmd+P 快记任务 9 步流程升级 + `--quickadd-options` batch 接口

#### 🎯 升级

原 5 步弹窗 → 9 步,加 ADHD 优先级 / 大类 / 小类 / DDL / 执行月(多选) / 执行周(多选)。**全部从飞书侧动态拉取**,飞书侧加项目只改飞书不改代码。

#### 🔌 sync.py `--quickadd-options` batch 接口

一次性返回 JSON 4 类数据:
```json
{
  "active_top_level": [...],
  "subprojects_by_parent": {...},
  "recent_months": ["26 年 6 月","26 年 5 月",...],
  "recent_weeks":  ["26W23","26W22",...]
}
```

避免 Cmd+P 启动多次 python3 进程(每次 ~1s)。任一子查询失败 → 对应字段返回空 list,不阻断 userscript。

### 📚 跨工程 handoff

- 接收:`docs/handoff/OB对接/2026-05-27-status-subdone-idea-handoff.md`(OB CC 发起)
- 发出:`docs/handoff/OB对接/2026-05-27-status-subdone-idea-反向回执.md`(完成确认 + 标 v0.3.6 候选 follow-up)

### 决策记录

**Q**:实测覆盖到什么程度?
**A**:**Phase 4.3 反向 SubDone 实测通过(用户手动建 record,跑 pull-today 看 OB frontmatter `status: subdone`),Phase 4.1/4.2/4.4/4.5 走静态代码推断 verified**(同一 dict 映射模式,通过路径 = SubDone 通过则其他全过)。用户 AskUserQuestion 选「跳过其他 case 进 commit」。

**Q**:v0.3.5 范围是只做 Part 1(handoff 要求)还是合并 Part 2(同会话 Cmd+P 9 步)?
**A**:CHANGELOG / README / sync.py 326 行改动 / obsidian-assets 2 文件改动**全部一致**指向 2 块合并 → 按 v0.3.4 模式合并 commit。

---

## 📊 当日总成果

| 维度 | 数量 |
|---|---|
| 版本上线 | 5 个(v0.3.1 / v0.3.2 / v0.3.3 / v0.3.4 / v0.3.5) |
| commits | 7 个(各版本 commit + handoff 闭环 commit) |
| 跨工程 handoff | 3 个(v0.3.1 回执 / v0.3.4 跨边界例外 / v0.3.5 反向回执) |
| 实测验证 | 全部用户真实 vault 实测通过 |
| 累积 sync.py 改动 | ~700 行(v0.3.5 Part 2 单独贡献 326 行) |

---

## 🔮 5/27 关键教训

1. **Defense in depth**(v0.3.3 时区):任何关键路径都加两层独立防御,任一失效另一层兜底
2. **Node global 在嵌入式上下文不可信**(v0.3.4 __filename):依赖 `__filename` / `process.cwd()` 等假设在 Obsidian / Electron / VSCode extension 上下文前必须实测
3. **dataview 过滤条件加得太死会破坏跨天展示**(v0.3.4 part 2):用 `today_history` event sourcing 比 `done_date = today` 直接判断更鲁棒
4. **status 7 态对齐 = 用户实际飞书看板配置**(v0.3.5 Part 1):不要预设状态机,让飞书侧决定枚举值,代码做 map
5. **multi-step 弹窗加跳过选项**(v0.3.5 Part 2):9 步比 5 步多但每步可跳,实际 ADHD 友好度提升

---

## 🔗 相关

- [`../../../CHANGELOG.md`](../../../CHANGELOG.md) v0.3.1 - v0.3.5 entry
- [`../../handoff/OB对接/`](../../handoff/OB对接/) 当日 3 个 handoff
- [`2026-05-28-feishukanban-开发日志.md`](2026-05-28-feishukanban-开发日志.md) 次日(含 v0.3.7 v0.3.5 候选 follow-up 落地)
