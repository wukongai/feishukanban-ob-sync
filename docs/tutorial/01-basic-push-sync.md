# Tutorial 01: 基础正向 sync(OB → 飞书)

> 🎯 **目标**:理解 sync.py 正向同步的完整流程。读完你能解释:为什么要 dry-run 先看 / `[x]` 和 `[ ]` 都会怎么映射 / 为什么 sync 完会改 markdown 文件。
>
> ⏱️ **预计阅读**:10 分钟

---

## 场景

你今天写了 5 个 task 到 `journals/2026-05-19.md`,其中 3 个已经勾对勾完成:

```markdown
- [x] 【布丁】调研直播功能选型 🔼 ➕ 2026-05-19 ✅ 2026-05-19
- [x] 整理本周阅读笔记 ⏫ ➕ 2026-05-19 ✅ 2026-05-19
- [/] 写 PRD v2 草稿 🔺 ➕ 2026-05-19
- [ ] 优化 CI/CD 流程 🔼 ➕ 2026-05-19
- [-] 学新语言(暂停) 🔽 ➕ 2026-05-19 ❌ 2026-05-19
```

你希望 sync 一下,让飞书项目看板也反映这些状态。

---

## Step 1: dry-run 看看会做什么(无副作用)

```bash
python3 ./sync.py "journals/2026-05-19.md"
```

期望输出:

```
=== 解析 journal: journals/2026-05-19.md ===
找到 5 个 task

--- Task 1: 【布丁】调研直播功能选型
    状态: [x] → Done
    完成时间: 2026-05-19 → 1716000000000
    🆕 无飞书链接 → 将创建新 record
    ⏳ 调 cli 拉全表 record 建标题索引(查重用)... ✅ 共 402 条 record, 387 个独立标题
    ✅ 标题不重复,准备创建
    fields payload:
      任务标题: "【布丁】调研直播功能选型"
      执行状态: ["Done"]
      完成时间: 1716000000000
      执行迭代周: "26W20"
      执行迭代月: "26 年 5 月"

--- Task 2: 整理本周阅读笔记
    状态: [x] → Done
    ...

--- Task 3: 写 PRD v2 草稿
    状态: [/] → Doing
    🆕 无飞书链接 → 将创建新 record
    ...

--- Task 4: 优化 CI/CD 流程
    状态: [ ] → Todo
    ...

--- Task 5: 学新语言(暂停)
    状态: [-] → Block
    放弃时间: 2026-05-19
    ...

📊 完成: 5 [新建] / 0 [更新] / 0 [跳过] / 0 [失败]
```

**重点检查**:
1. **任务标题**:emoji metadata 应该已经去掉,只保留干净标题
2. **状态映射**:`[x]→Done`, `[ ]→Todo`, `[/]→Doing`, `[-]→Block`
3. **完成时间**:ISO 日期 → 毫秒时间戳(飞书 datetime 字段格式)
4. **执行迭代周/月**:自动从完成日推导(如 2026-05-19 → 第 ISO 21 周 → 26W21)
5. **没有错误 / 警告**(✅ 标志)

---

## Step 2: 解读"为什么是 dry-run 不是直接写"

```
🆕 无飞书链接 → 将创建新 record
⏳ 调 cli 拉全表 record 建标题索引(查重用)
```

dry-run 模式下,sync.py 会:

| 行为 | dry-run | apply |
|------|---------|-------|
| 调 feishu-cli 写 record | ❌ | ✅ |
| 修改 markdown 文件 | ❌ | ✅(写回 record URL 到 task 行) |
| 调 cli 查重(标题反查) | ✅(读不写) | ✅ |
| 调 cli 拉飞书 enum 选项 | ✅(读不写) | ✅ |

**核心安全 → 调"读"cli 接口看会做什么,但永远不"写"**。

> **铁律**:任何**写飞书 / 写 markdown** 的 apply 操作之前,必须先 dry-run。

---

## Step 3: 想 sync 已完成的 → 加 `--only-completed`

```bash
python3 ./sync.py "journals/2026-05-19.md" --only-completed
```

效果:
- Task 1 `[x]` ✅ 同步
- Task 2 `[x]` ✅ 同步
- Task 3 `[/]` ❌ 跳过
- Task 4 `[ ]` ❌ 跳过
- Task 5 `[-]` ✅ 同步(被视为完成)

**推荐场景**:日终复盘 / 批量补录,只关心"今天完成了什么",不关心 in-progress 的 task。

---

## Step 4: dry-run 通过 → apply 真实写入

```bash
python3 ./sync.py "journals/2026-05-19.md" --only-completed --apply
```

执行后会发生 2 件事:

### 4.1 飞书侧:CREATE 3 个新 record

| record_id | 任务标题 | 执行状态 | 完成时间 |
|-----------|---------|---------|---------|
| rec_xxx1 | 【布丁】调研直播功能选型 | Done | 2026-05-19 |
| rec_xxx2 | 整理本周阅读笔记 | Done | 2026-05-19 |
| rec_xxx3 | 学新语言(暂停) | Block | 2026-05-19 |

### 4.2 OB 侧:markdown 文件自动改写

```diff
- - [x] 【布丁】调研直播功能选型 🔼 ➕ 2026-05-19 ✅ 2026-05-19
+ - [x] [【布丁】调研直播功能选型](https://<tenant>.feishu.cn/base/<base_token>?table=<tbl>&view=<view>&record=rec_xxx1) 🔼 ➕ 2026-05-19 ✅ 2026-05-19

- - [x] 整理本周阅读笔记 ⏫ ➕ 2026-05-19 ✅ 2026-05-19
+ - [x] [整理本周阅读笔记](https://<tenant>.feishu.cn/base/<base_token>?table=<tbl>&view=<view>&record=rec_xxx2) ⏫ ➕ 2026-05-19 ✅ 2026-05-19

- - [-] 学新语言(暂停) 🔽 ➕ 2026-05-19 ❌ 2026-05-19
+ - [-] [学新语言(暂停)](https://<tenant>.feishu.cn/base/<base_token>?table=<tbl>&view=<view>&record=rec_xxx3) 🔽 ➕ 2026-05-19 ❌ 2026-05-19
```

⚠️ **inject_url_into_line bug 修复(2026-05-19)**:`🔼 ➕ 2026-05-19 ✅ 2026-05-19` 这些 emoji metadata **全部保留**,不会丢任何一个。老版本只匹配第一个 emoji 前空白,会吃掉后续 metadata,这是本仓库相对老 sync 实现的核心改进。

---

## Step 5: 第二次跑 sync(UPDATE 路径)

假设第二天你又勾对勾完成了 Task 3,markdown 已经有飞书链接:

```markdown
- [x] [写 PRD v2 草稿](https://...record=rec_xxx4) 🔺 ➕ 2026-05-19 ✅ 2026-05-20
```

再跑:

```bash
python3 ./sync.py "journals/2026-05-19.md" --only-completed
```

dry-run 看到:

```
--- Task 3: 写 PRD v2 草稿
    🔗 已有飞书链接 rec_xxx4 → 走 UPDATE 路径
    状态: [x] → Done(变化:Doing → Done)
    完成时间: 2026-05-20 → 1716086400000
    fields payload:
      执行状态: ["Done"]
      完成时间: 1716086400000
```

apply 后,飞书 record `rec_xxx4` 的执行状态从 `Doing` 改成 `Done`,完成时间被填上。

---

## 流程总结

```
你写 task 到 journal.md
    ↓
[首次] dry-run --only-completed → 看 payload 没问题
    ↓
[首次] apply → 飞书 CREATE + markdown 写回 URL
    ↓
[次日] 勾对勾完成 + 改优先级 + 加交付物
    ↓
[次日] dry-run --only-completed → 看 UPDATE diff
    ↓
[次日] apply → 飞书 UPDATE 字段
```

---

## 常见疑问

### Q1: sync 会不会改我已经写好的 task 文字?

不会。sync 只在 **task 行末尾追加 metadata 或在前面插入 markdown link**,不会改任务标题、不会改优先级 emoji、不会改 `[ ]` 状态字符。

### Q2: 我手动改了飞书后台的字段,下次 sync 会被覆盖吗?

**会** — sync 是"以 OB 为准"的单向逻辑。如果你想"以飞书为准",见 [Tutorial 03: 反向 pull](./03-reverse-pull.md)。

### Q3: dry-run 显示某个 enum 选项未命中怎么办?

例:`执行迭代周: "26W22" 未命中飞书 enum`。这是飞书表的"执行迭代周"单选字段还没建 `26W22` 选项。处理:

- 推荐:去飞书后台手动添加 enum
- 兜底:sync 会静默跳过这个字段,其他字段照常写入(不阻断)

### Q4: 我想跳过某些 task 不 sync 怎么办?

当前没有"跳过"标记。变通方式:
- 删掉 ✅ 完成日 → `--only-completed` 不会同步它
- 改成 `[/]` 进行中 → `--only-completed` 不会同步它
- 删掉整个 task 行(也行,但失去历史)

未来增强:加 `⏸️` emoji 或 `<!-- skip -->` 注释作为跳过标记。

---

## 下一步

- 📖 [Tutorial 02: 短链自动反查 + cache](./02-short-link-auto-lookup.md) — 理解从飞书后台复制短链贴 OB 的流程
- 📖 [Tutorial 03: 反向 pull](./03-reverse-pull.md) — 飞书侧新建 task 拉回 OB
- 📖 [Tutorial 04: 字段映射定制](./04-field-mapping-customization.md) — 改 config.yaml 加新字段
