---
title: skill 约束补强 — 执行明细每日单条 + 交付路径强制绝对路径
type: handoff
status: 待对方接收
created: 2026-06-11
from: Content-factory 内容工厂会话(Claude Opus 4.7)
to: feishukanban-ob-sync 项目维护者
related:
  - "[[../../../.claude/skills/同步任务到飞书/SKILL.md]]"
  - "[[../../../sync.py]]"
tags:
  - handoff
  - skill约束
  - 防呆设计
---

# skill 约束补强:执行明细每日单条 + 交付路径强制绝对路径

## 背景

2026-06-11 在 Content-factory 内容工厂会话中,Claude(我)调用 `/同步任务到飞书` skill 把一条调研类 task(record_id `recvlV5IDsBZ5B`)同步到飞书,前后 apply 了 **3 次**(多花用户一轮往返),根本原因是**两处 skill 文档已写、Claude 未严格遵守**的约束。用户原话:

> "执行明细的更新发发不对,执行明细里每天是一条状态记录,而不是每天多条,具体过程落地到复盘,每一条代表一天,否则容易错误同步到飞书文档的时候"
>
> "交付内容中的文件,如果不是 OB 文件夹,中必须给出绝对路径,飞书里必须是给出 wiki 直接连接。请你检查一下飞书同步任务这个 skill,我记得对于文件要求里面有些,为什么你没有遵守"

本 handoff 把两个错误拆透 + 自我反思为什么没遵守 + 给飞书同步项目维护者的改进建议,目的是**通过文档强约束 + 工具侧拦截让下次 Claude 不再犯**。

---

## 错误 1:执行明细同日拆多行

### 我写的(违规)

```markdown
## 📈 执行明细

- 2026-06-11 | Done | 计划=调研 yikart/AiToEarn / 估时=4 / 用时=2 / 完成度=标准完成 / 复盘=...
- 2026-06-11 早 | 派 researcher agent 启动调研(首次 socket 断,重试一次成功)
- 2026-06-11 上午 | 30 次工具调用 / 12 个信息源交叉验证 / 70.8k tokens
- 2026-06-11 上午 | 落 `docs/research/...`(300 行 / 17KB)
- 2026-06-11 上午 | 新建 `docs/backlog/...` 占位
- 2026-06-11 上午 | 任务标完成同步飞书
```

### 后果

sync.py 推飞书子表时按日期合并,**同日 6 行只识别第一行**作为 state record。第一行状态是 `Done` 但**前一版本是 `Doing`**,造成飞书子表「当日状态:Doing · 终极状态:Done」长期不一致,用户截图反馈后才发现。其他 5 行叙事内容**在飞书侧完全丢失**,只留在 OB 本地 Dataview 看。

### 正确写法

```markdown
## 📈 执行明细

- 2026-06-11 | Done | 计划=... / 估时=4 / 用时=2 / 完成度=标准完成 / 复盘=派 researcher agent 走 WebSearch + WebFetch(首次 socket 断,重试一次成功);30 次工具调用 / 12 信息源交叉验证;落调研报告;新建 backlog;同步飞书。结论:不部署 + 仅借鉴 MCP 接口
```

**每天 1 条 state record,过程串「复盘=」字段用分号 `;` 分隔**。

### skill 文档现状

[`.claude/skills/同步任务到飞书/SKILL.md`](../../../.claude/skills/同步任务到飞书/SKILL.md) 「📈 执行明细 `--detail`」段写了**单条格式**:

```
--detail "YYYY-MM-DD | 状态 | 计划=… / 估时=… / 用时=… / 完成度=… / 复盘=…"
```

但**没明确"同日只能一条"**的硬约束,也**没写多行会被合并的后果**。Claude(我)惯性按"每个动作记一条"的思维拆多行,文档没堵住这条路。

---

## 错误 2:交付段用相对路径(非 vault 内文件)

### 我写的(违规)

```markdown
## 📦 交付

**调研报告**:`docs/research/2026-06-11-yikart-aitoearn-evaluation.md`(300 行 / 17KB)

**后续动作**:
- 已新增 backlog 占位 → `docs/backlog/P2-内容分发MCP接口设计-借鉴AiToEarn.md`
```

### 后果

- 两个文件都在 `Content-factory` 仓库内,**不在 OB vault 内,也无 symlink 软链进 vault**
- 飞书侧看到 `docs/research/...` 不知道是哪个仓库
- OB 双链 `[[docs/research/...]]` 在 vault 内找不到对应笔记 → 红色断链 / 误命中同名笔记(Content-factory 仓库下还有别的 `docs/research/` 笔记,且 vault 里也可能有同名文件)
- 用户在 OB 里点击无法跳转,失去 "Cmd + 点击 → Finder 定位" 的能力

### 正确写法

```markdown
## 📦 交付

**调研报告**:`/Users/aim5/Documents/CodingProject/Content-factory/docs/research/2026-06-11-yikart-aitoearn-evaluation.md`(300 行 / 17KB)

**后续动作**:
- 已新增 backlog 占位 → `/Users/aim5/Documents/CodingProject/Content-factory/docs/backlog/P2-内容分发MCP接口设计-借鉴AiToEarn.md`
```

**绝对路径包反引号(行内 code)**。OB 端 Cmd+点击 → Finder 定位;飞书端看到完整路径知道是哪个仓库。

### skill 文档现状

「📦 交付 / 相关资料」段其实**写得非常详细**(本来就是为了堵这个洞):

> ⚠️ **跨 OB 项目的产出物必须用绝对路径** —— 不要只写文件名 / 相对路径(如 `CHANGELOG.md` / `docs/handoff/xxx.md`),原因:
> - OB 双链 `[[xxx]]` 在 vault 内找不到对应笔记 → 红色断链 / 误命中同名笔记
> - 飞书侧看到没头没尾的文件名,不知道是哪个仓库的产出
> - 行内 code 包绝对路径在 OB 里**可 Cmd+点击 → Finder 定位**(macOS),飞书侧也能看清归属

文档已经把后果、原因、判断方法、范例都写了,**但 Claude 仍然失败** — 这意味着光靠"读文档+自觉"不够,需要**工具侧硬拦截**。

---

## 我为什么没遵守(自我反思,给文档作者参考)

### 1. 认知盲点 — 把"在内容工厂仓库内"当成"vault 内"

Content-factory 是 vault 外的独立 git 仓库(在 `CodingProject/Content-factory/`),但**我在内容工厂会话里工作时,潜意识把它当成了"项目自己的空间"**,没意识到 task md 是落在 OB vault 里的、它的读者(OB Dataview + 飞书)都看不到 Content-factory 仓库的 cwd。

这种盲点在**跨仓库会话**时特别普遍 — Claude 当前在哪个 cwd,就习惯用相对路径写产出。skill 文档需要假设"调用方 cwd 不在 vault 内"是默认场景。

### 2. 简化倾向 — 相对路径"看起来更整洁"

`docs/research/xxx.md` 比 `/Users/aim5/Documents/CodingProject/Content-factory/docs/research/xxx.md` 视觉上短得多,**Claude 在生成内容时天然倾向"简洁"**。文档里写"必须绝对路径"是规则,但 LLM 在生成时受美感偏好驱动,容易"漏看一眼"。

### 3. 执行明细的"每个动作一行"是 LLM 的默认拆解模式

我把过程拆 6 行是因为**默认认为"每个原子动作 = 一条记录"** — 这是 LLM 写日志/changelog 的本能。skill 文档只说"单条格式",没说"同日只能一条",我就误以为多行也可以(每行算一个明细 record)。

**核心问题**:LLM 的"原子动作 = 一条记录"惯性 vs sync.py 的"日期作为合并 key"机制冲突,文档没明示这层冲突。

### 4. dry-run 输出已经暗示了问题,我没看出来

第一次 dry-run 输出里:

```
📈 执行明细(1 条):
  - 2026-06-11 | doing | plan=让 fabal 在做 / estimate_hours=4.0
```

**写得清清楚楚只识别了 1 条**(我塞了 6 行),但我在汇报里只说"我加在执行明细的 5 行时间线说明没被 sync 识别,只在 OB 本地 Dataview 里看得到" — **我把这个识别失败定性成"OK 的丢弃"而不是"需要修的 bug"**,因为「Done 状态」那一行已经在第一条里、我以为状态没问题。

实际上**第一条仍然是 `Doing` 状态**(我之前 Edit 时只改了交付/复盘段,执行明细的状态字段没同步改),dry-run 已经显示 `doing`,我视而不见。

---

## 给飞书同步项目维护者的改进建议

### A. SKILL.md 文档补强(最低成本,先做)

#### A1. 「📈 执行明细」段加硬约束

在 `--detail` 格式说明旁边加一个 **⚠️ 反例 + 后果** 块:

```markdown
#### ⚠️ 执行明细硬约束:同一日期只能一条 state record

❌ 错误写法(同日拆多行):
- 2026-06-11 | Doing | 计划=...
- 2026-06-11 早 | 派 agent 启动
- 2026-06-11 上午 | 落产出
- 2026-06-11 下午 | Done | 任务完成

后果:sync.py 按日期合并 → 飞书子表只识第一条(Doing),其他被合并/丢弃,
造成「当日状态」与「终极状态」不一致,需要返工。

✅ 正确写法(每日单条 + 过程串复盘):
- 2026-06-11 | Done | 计划=... / 用时=2 / 完成度=标准完成 /
  复盘=派 agent 启动(socket 断重试);落产出;同步飞书。结论:...

多天进展写多条不同日期的 record,但同日严禁拆多行。
```

#### A2. 「📦 交付」段加更醒目的强约束 + 反例

现状是"⚠️"警告但藏在普通段落里,建议**升格为独立子段** + 顶部突出:

```markdown
#### 🚨 交付路径硬约束(违反 = 飞书侧丢失归属)

调用方 cwd 不在 OB vault 内(如 Content-factory / zhixing-game 等独立仓库)时,
**绝对禁止用相对路径**写交付:

❌ `docs/research/xxx.md`         ← 飞书侧不知道哪个仓库,OB 双链断链
❌ `[[docs/research/xxx]]`        ← 同上,且可能误命中 vault 内同名笔记
❌ `CHANGELOG.md`                 ← 多个仓库都叫这名,完全无归属

✅ vault 内笔记 → `[[xxx]]`        ← OB 双链直接跳
✅ 有 URL → `[标题](https://...)`  ← 飞书 / OB 都可点
✅ vault 外文件 → `` `/Users/.../绝对路径` ``  ← OB Cmd+点击跳 Finder,飞书侧清晰

判断流程:
1. Grep vault 看有没有同名笔记 / symlink → 有 → `[[]]`
2. 有可访问 URL → `[标题](url)`
3. 都没有 → **绝对路径 + 反引号包** (`` `/Users/...` ``)
```

#### A3. 加一段「Claude 常见错误模式」给 LLM 看的提示

```markdown
#### 🤖 Claude 调用本 skill 时的常见错误(自检)

LLM 在生成内容时有几个本能倾向会触雷,apply 前必须自检:

1. **执行明细拆多行**:LLM 习惯"每个动作一条",但 sync.py 按日期合并 → 只识第一条
   → 同日合并成一行,过程塞复盘
2. **相对路径写交付**:LLM 在当前 cwd 下习惯用相对路径
   → 强制绝对路径(或 OB 双链)
3. **状态字段没同步改**:Edit 状态时只改 frontmatter,忘了改执行明细行的状态字段
   → 执行明细的 state 必须与 frontmatter `status` 同步
4. **dry-run 输出里的"识别 N 条"**:LLM 容易把"只识 1 条"当成 OK,
   实际是"剩下的丢失" → dry-run 看到"识别条数 < 实际写的条数" 必须停下来修
```

### B. sync.py 工具侧硬拦截(中等成本,可选 v0.8+)

#### B1. 解析交付段时检测相对路径

```python
# sync.py 解析 --delivery / 📦 交付 段时
def lint_delivery_paths(delivery_md: str) -> list[str]:
    """检测交付段里的可疑相对路径,返回警告列表"""
    warnings = []
    for line in delivery_md.splitlines():
        # 匹配反引号包的路径
        for path in re.findall(r'`([^`]+)`', line):
            if path.startswith(('docs/', 'src/', '.claude/', 'scripts/')):
                warnings.append(f"⚠️ 疑似相对路径(应改绝对): `{path}`")
        # 匹配 OB 双链但内容像路径
        for link in re.findall(r'\[\[([^\]]+)\]\]', line):
            if '/' in link:
                warnings.append(f"⚠️ 双链含 '/',疑似路径(应改绝对): [[{link}]]")
    return warnings
```

在 dry-run / apply 时输出警告,`--strict-delivery-paths` flag 下变错误拒推。

#### B2. 执行明细同日多行检测

```python
def lint_detail_same_day(details: list[dict]) -> list[str]:
    warnings = []
    by_date = {}
    for d in details:
        by_date.setdefault(d['date'], []).append(d)
    for date, items in by_date.items():
        if len(items) > 1:
            warnings.append(
                f"⚠️ {date} 有 {len(items)} 条执行明细 → 仅首条会推飞书,"
                f"其余 {len(items)-1} 条丢失。合并到首条的「复盘=」字段。"
            )
    return warnings
```

dry-run 时强制显示该警告;`--strict-detail-one-per-day` flag 下拒推。

### C. SKILL.md 最末的「📋 自检清单」加两条

现有 checklist 已经覆盖大部分场景,补两条:

```markdown
- [ ] **执行明细同日只一条**:翻执行明细段,每个日期有且仅有 1 行;过程已塞「复盘=」字段分号分隔?
- [ ] **交付路径全绝对/全双链**:vault 外文件用 `` `/Users/.../绝对路径` ``;vault 内用 `[[]]`;**无任何 `docs/xxx` / `src/xxx` 之类相对路径**?
```

---

## 验证标准

补强生效的标志:

1. **文档侧**:SKILL.md 加上述反例块 + 自检清单两条后,下次 Claude 调用应能在生成阶段就避开两个错误
2. **工具侧**(可选):`sync.py --apply` 检测到同日多行 / 相对路径时,**dry-run 输出顶部红字警告**,`--strict-*` 模式下拒推
3. **回归测试**:用本次错误的 task md 副本跑一遍,dry-run 应该警告"6 行同日明细 → 5 条丢失"+"交付段 2 处疑似相对路径"

---

## 关联资料

- 错误案例 task md(已修正):`/Users/aim5/Documents/OB/04 Inbox/task/2026-06-08-【内容工厂】调研体验开源项目:yikart_AitoEarn,自媒体开源项目.md`(record `recvlV5IDsBZ5B`)
- 内容工厂会话 memory(已写入新规则):`/Users/aim5/.claude/projects/-Users-aim5-Documents-CodingProject-Content-factory/memory/feedback-task-execution-detail-one-per-day.md`
- skill 当前版本:`/Users/aim5/.claude/skills/同步任务到飞书/SKILL.md`
- sync.py 当前版本:`/Users/aim5/Documents/CodingProject/feishukanban-ob-sync/sync.py`(v0.8.x)

---

## 接收 / 反馈

请 feishukanban-ob-sync 维护者(用户本人)在采纳/部分采纳/暂缓后:

1. 在本目录 sibling 位置写 `2026-06-11-skill约束补强-反向回执.md`,说明:
   - 采纳了哪些(文档补强 + 工具拦截分别)
   - 暂缓 / 不做的部分 + 原因
   - 落地的 commit hash / SKILL.md 版本号
2. 内容工厂会话(我)收到回执后,会把新规则同步到本项目 memory + 必要时更新 `.claude/rules/`
