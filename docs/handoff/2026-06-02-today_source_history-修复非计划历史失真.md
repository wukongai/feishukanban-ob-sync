# Handoff：today_source_history — 修复非计划历史失真

**日期**：2026-06-02  
**优先级**：P2（历史数据失真，影响复盘准确性）  
**版本目标**：v0.7.2（patch）

---

## 问题描述

OB 日志里「今日非计划」区块，回看历史日（如 6-01）时，原本正确显示为非计划的任务，在 6-02 跑完 `--pull-today` 后**全部漂移到今日计划区块**，历史失真。

---

## 根因

`today_source` 是**单个全局字段**，但需要的是**按天快照**。

两条路径都会破坏历史：

| 路径 | 代码位置 | 破坏方式 |
|---|---|---|
| `plan_set_true`（拉入今日） | sync.py ~5381 | 强制写 `today_source: "planned"`，覆盖已有 `"unplanned"` |
| `plan_set_false`（移出今日） | sync.py ~5471 | 强制写 `today_source: ""`，清空已有 `"unplanned"` |

Dataview 渲染时读**当前实时值**，所以 6-01 unplanned 任务一旦经过任意一条路径，6-01 日志就失真。

---

## 修复方案：today_source_history（仿 today_history 设计）

新增 `today_source_history` 字段，与 `today_history` 平行，按天记录来源：

```yaml
today_history:        [2026-06-01, 2026-06-02]
today_source_history: [unplanned,  planned   ]
```

- 位置一一对应：`today_history[i]` 的来源是 `today_source_history[i]`
- 只追加，不回溯修改
- `today_source`（旧字段）继续保留，表示**最近一次**的来源（向后兼容）

---

## 需要改动的地方

### 1. sync.py：维护 today_source_history

**A. `plan_set_true`（~5374 行附近）**

```python
# 现在（有 bug）：
base = {
    "today": True,
    "today_history": history,
    "today_source": "planned",   # ← 覆盖了历史
}

# 改为：
# 读现有 today_source_history，append 今天的 source
try:
    fm_cur2, _, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
    src_history = fm_cur2.get("today_source_history", []) if fm_cur2 else []
    if not isinstance(src_history, list):
        src_history = []
except Exception:
    src_history = []
# 与 today_history 长度对齐，今天追加 "planned"
if len(src_history) < len(history):
    src_history.append("planned")

base = {
    "today": True,
    "today_history": history,
    "today_source": "planned",           # 保留旧字段（最近值）
    "today_source_history": src_history, # 新字段（按天快照）
}
```

**B. `plan_set_false`（~5467 行附近）**

```python
# 现在（有 bug）：
base = {"today": False}
base["today_source"] = ""  # ← 清空了历史

# 改为：不清空 today_source（保留最后一次来源记录），也不动 today_source_history
base = {"today": False}
# today_source 保留原值，不清空
# today_source_history 不动
```

**C. `plan_skip` 字段 sync**

确认 `_build_field_diffs`（~4495 行注释）里 `today_source_history` 也不纳入飞书同步（与 today_source 同等处理，只在 OB 侧维护）。

**D. `--create-task`（~3249 行附近）**

新建任务时，如果有 `today_source`，同步写 `today_source_history`：

```python
today_source = _s(args.today_source)
today_source_history_line = (
    f"today_source_history: [{today_source}]" if today_source else "today_source_history:"
)
```

并在 task md 模板中加入该字段行（`today_source` 行下方）。

### 2. OB 日志模板：Dataview 改用 today_source_history 渲染

**`今日计划` 和 `今日非计划` 两个区块**，历史日的 `today_source` 判断改为按日期查 `today_source_history`：

```js
// 新增工具函数，根据日期从 today_source_history 查来源
const getDaySource = (p, dateISO) => {
  const hist = dv.array(p.today_history ?? []).map(d => d && d.toISODate ? d.toISODate() : String(d));
  const srcHist = dv.array(p.today_source_history ?? []);
  const idx = hist.indexOf(dateISO);
  if (idx >= 0 && idx < srcHist.length) return String(srcHist[idx]);
  return p.today_source ?? "";  // fallback 到旧字段（兼容没有 source_history 的老 task）
};

// 今日计划区块 where 条件改为：
const inPlan = p => inToday(p) && getDaySource(p, curISO) !== "unplanned";

// 今日非计划区块 where 条件改为：
const inUnplanned = p => inToday(p) && getDaySource(p, curISO) === "unplanned";
```

**修改范围**：
- `日志模版 5.0 1.md`（`03 Resources/素材库/模版/`）
- 已有历史日志文件（目前：5-30、5-31、6-01、6-02）

### 3. task 模板：加 today_source_history 字段

`obsidian-assets/templates/task-template.md`：在 `today_source` 行下方加：

```yaml
today_source_history:
```

### 4. 文档更新

- `docs/feishu-schema.md`：说明 `today_source_history` 字段（OB-only）
- `CHANGELOG.md`：v0.7.2 patch 说明

---

## Migration（已有 task 文件）

已有 task 文件没有 `today_source_history` 字段，Dataview 会 fallback 到旧 `today_source` 字段——**不需要一次性 migration**，新字段从下次 `plan_set_true` 触发开始累积。

历史日志里没有 `today_source_history` 的老任务，`getDaySource` 返回旧 `today_source` 值，行为与现在一致（不会更差）。

---

## 测试步骤

1. 挑一个 `today_source: unplanned` 的 task（如 `2026-06-01-skill 全局机制教程 + 一键发文.md`）
2. 跑 `--pull-today --apply`，确认：
   - 该 task 的 `today_source_history` 里追加了今天的 source
   - `today_source` 旧字段也正确
3. 打开该 task 创建日的日志，确认「今日非计划」仍显示它（不漂移到计划）
4. 打开今日日志，确认它出现在正确区块（计划或非计划）

---

## 版本号

`v0.7.2`（patch，向后兼容，不 breaking）

bump 位置：`README.md` 顶部 badge + `CHANGELOG.md` + git tag

---

## 起手命令（新 CC 窗口）

```
读 /Users/aim5/Documents/CodingProject/feishukanban-ob-sync/docs/handoff/2026-06-02-today_source_history-修复非计划历史失真.md，按里面的方案实施 today_source_history 修复（v0.7.2），先 git log -5 和 git status 了解当前状态，再按修改范围逐步实施，每步完成后告诉我进度，不要一次性全改完再汇报。
```
