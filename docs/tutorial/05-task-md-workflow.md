# Tutorial 05: v0.2 task md 化主流程

> 跟做完这篇,你掌握 v0.2 的 **4 个 Cmd+P 命令 + 1 个 Claudian 对话场景**,实现 task 全生命周期的全闭环。

**前置**:已完成 [INSTALL.md](../../INSTALL.md) 的 v0.2 一键部署。

---

## 一天的工作流

### ☀️ 早上:挑今日 todo(2 分钟仪式)

#### Step 1:在飞书 app 周看板挑 task

```
飞书 app(手机或电脑)→ 你的项目管理多维表 → 周看板视图
   ↓
长按某条 task → 详情 → 找「是否今日」字段 → 勾 ☑
   ↓
重复挑 3-5 条(今天要做的)
```

> **为什么用飞书 app 而不是 Obsidian?**
> - 飞书 app 移动端体验好,通勤路上能完成"今日规划"
> - 看板视图直观,优先级 / 项目分类一目了然
> - "看板是真相源"哲学 — 飞书侧主导,OB 跟从

#### Step 2:Obsidian Cmd+P「📥 拉今日 todo」

```
Cmd+P → 搜「拉今日 todo」→ 回车
   ↓
⏳ 5-10 秒(后台调 sync.py --pull-today --apply)
   ↓
✅ Notice:设 today=true: 3 条 / 已是 today,跳过: 0 条
```

**幕后做的事**:
- 拉飞书全表 record(自动分页)
- 筛「是否今日」=true 的 record
- scan OB `04 Inbox/task/` 建索引(by `feishu_record`)
- 对每条:
  - 飞书=true, OB today=false → 改 OB frontmatter `today: true`
  - 飞书=false, OB today=true → 改 OB frontmatter `today: false`(取消)
- 报告:N 设 true / M 设 false / K 跳过 / P 飞书有 OB 无

#### Step 3:打开 today journal 看渲染

```
Cmd+O → journals/<today>.md → 打开
   ↓
看「🎯 今日计划」段
   ↓
✅ 3 条 task 的 checkbox 已渲染(dataview TASK 查询自动捞 today=true 且 P0-P2 的 task md)
```

dataview 查询条件:
```dql
TASK
FROM "04 Inbox/task"
WHERE today = true
  AND (priority = "P0" OR "P1" OR "P2")
  AND (!completed OR completion = this.file.day)
```

---

### 🏃 白天:工作中创建 + 完成 task

#### Step 4:临时想到新任务 → Cmd+P「📝 快记任务」

```
Cmd+P → 搜「快记任务」→ 回车
   ↓
弹优先级菜单:🔺P0 / ⏫P1 / 🔼P2 / 🔽P3
选 P1
   ↓
弹输入框:输入标题
"修复 sync.py 的 \\s SyntaxWarning"
   ↓
⏳ 5-10 秒
   ↓
✅ Notice:task md 已建 + 飞书 record CREATE 成功
```

**幕后做的事**(Macro v2):
1. 计算北京日期 `<bjDate>`
2. 创建 `04 Inbox/task/<bjDate>-修复 sync.py 的 \\s SyntaxWarning.md`
3. 填 frontmatter(`priority: P1` / `status: todo` / `today: false` / `created: ...` 等 18 字段骨架)
4. 填正文 5 个 H2 段骨架(`## 📝 执行概述` 等)
5. 调 `sync.py --task-md --apply`(铁律 #1 飞书例外 — 单条 CREATE 自动 apply)
6. sync.py CREATE 飞书 record → 回写 `feishu_record` + `feishu_url` 到 task md

#### Step 5:做完一条 → Cmd+P「✅ 完成当前 task」

```
打开任意 task md(可以是早上挑的 today todo,也可以是临时建的)
   ↓
Cmd+P → 搜「完成 task」→ 回车
   ↓
⏳ 5-10 秒
   ↓
✅ Notice:task 完成!OB done + 飞书 UPDATE Done(record: recXXX)
```

**幕后做的事**:
1. 检查 current note 是 task md(`04 Inbox/task/` 下)
2. 检查 frontmatter 有 `feishu_record`(说明已 sync 过)
3. 改 frontmatter:
   - `status: todo/doing` → `done`
   - `done_date: <bjDate>`
4. 改 inline checkbox(在「## ✅ 完成标记」段):
   - `- [ ]` → `- [x] ... ✅ <bjDate>`
5. 调 `sync.py --task-md --apply`(铁律 #1 飞书例外扩展 — 单条 UPDATE 完成态自动 apply)
6. 飞书侧:执行状态 → Done + 完成时间 → today + 执行迭代周/月 自动填

---

### 🌙 晚上:自动统计 + 收工(3 分钟)

#### Step 6:Claudian 对话「统计今天工作」

打开 Claudian 对话(Obsidian 内置)或者在 Mac 终端用 `claude` cli,说:

```
你: 统计今天工作
   ↓
Claudian: 走 5 步 SOP
   1. 调 scripts/auto_collect_today.py 采集
      - git log --since=1day(扫 zhixing-game / OB / ... 项目仓库)
      - vault 今日 mtime 改的 .md/.py/.js/.css 等
   2. 读 today journal + 本周报
   3. LLM 归纳为 5-10 个主题
   4. dry-run 给你审:每个主题标题 + 描述 + 关联 plan + 价值优先级
   5. 等你说「全部都做」/「跳过 #3 #5」/ 等明确批准
   6. apply:
      - 在 today journal 末尾(or 「📝 今日复盘」前)加「📊 今日自动统计」section
      - 为每个主题在飞书 batch CREATE record(status=Done, P3, 完成时间=today)
```

**触发关键词**(说任一即可):
- "统计今天工作"
- "汇总今日"
- "auto-stats today"
- "今天做了什么 → 写日志和飞书"
- "总结今天 / 复盘今天"

**为什么不用 Cmd+P 触发?**
- LLM 归纳层质量很重要,Python 脚本只能项目级分组(噪音多)
- Claudian 主导能关联到具体计划 / spec 文档(`auto_collect` 只给原始数据)
- 跨平台:在 Claudian 对话里更顺畅(可以接着追问 / 修主题)

---

## 4 个 Cmd+P 命令完整清单

| 命令 | 何时用 | 走铁律 #1 SOP? |
|------|--------|---------------|
| **📝 快记任务** | 任何时候想到新 task | ❌ 跳过(铁律 #1 飞书例外 — 单条 CREATE) |
| **📥 拉今日 todo** | 早上挑完今日 todo 之后 | ❌ 跳过(只改 OB frontmatter,飞书侧只读) |
| **✅ 完成当前 task** | 做完一条 task 后 | ❌ 跳过(铁律 #1 飞书例外扩展 — 单条 UPDATE 完成态) |
| **🎯 同步今日 task 到飞书** | 批量同步(老接口,仍可用) | ✅ 走 dry-run + 用户审批 |

---

## 排障

### Q1: Cmd+P 命令 sync 步骤失败

**症状**:Notice「⚠️ 飞书同步失败」+ 错误信息

**排查**:
1. 看 Notice 具体错误(可能是 OAuth 过期 / 网络断 / cli 路径错)
2. Mac 打开终端跑:
   ```bash
   cd <你的 vault>
   python3 scripts/feishukanban-ob-sync/sync.py --task-md "04 Inbox/task/<刚建的文件>" --apply
   ```
3. 看 stdout/stderr 具体报错
4. 常见原因:
   - `feishu-cli auth check` 看 token 状态(可能过期)
   - vault 内 config.yaml 缺 base_token / table_id

**降级**:即使 sync 失败,task md 已创建,手动跑 sync 即可。

### Q2: Cmd+P「✅ 完成当前 task」报「task md 没有 feishu_record」

**原因**:task md 还没 sync 过飞书(从来没 CREATE 过 record)

**修复**:先跑 `python3 scripts/feishukanban-ob-sync/sync.py --task-md "<task md path>" --apply` 让它 CREATE,然后再 Cmd+P 完成。

### Q3: today journal「🎯 今日计划」段没渲染 task

**排查**(按顺序):
1. **检查 task md 的 `today` 字段**:打开你勾了「是否今日」的 task md,看 frontmatter `today: true` 是否存在
   - 没 true → 跑 Cmd+P「📥 拉今日 todo」
2. **检查 priority**:dataview 只渲染 P0-P2(P3 进「🐿️ 今日非计划」段)
3. **检查 dataview 插件 + JS 是否启用**(Settings → Community Plugins → Dataview)
4. **Cmd+R 刷新 journal**

### Q4: 飞书 record 已有 OB 没建 task md

**说明**:sync.py --pull-today 不自动建 task md(避免反向映射错乱)。

**workaround**:
- 在 OB 端 Cmd+P「📝 快记任务」手建一条同名的(然后手动改 frontmatter `feishu_record` 关联)
- 或者无视,只在飞书 app 上做这条 task

---

## 进阶:编辑 task md 详细字段

新建 task 后,task md 默认只有 frontmatter 18 字段骨架 + 5 个 H2 段空。

**用法**:在 task md 写以下 H2 段,sync 时自动同步到飞书对应字段:

| task md H2 段 | 飞书字段 |
|--------------|---------|
| `## 📝 执行概述` | 执行概述 |
| `## ✅ 验收条件` | 验收条件 |
| `## 💡 执行思路` | 执行思路 |
| `## 🔗 相关资料` | 相关资料 |
| `## 🪞 复盘` | 复盘 |

frontmatter 字段也可手动改:
- `category: 产品项目`
- `subcategory: [开发, 重构]`
- `adhd_priority: 待抢救`
- `estimate_hours: 2`
- `efficiency: 高`(完成后填)

改完跑 Cmd+P「✅ 完成当前 task」或手动 sync 即可同步。

---

## 关联

- [README.md](../../README.md) — 主入口
- [ARCHITECTURE.md](../ARCHITECTURE.md) — 系统架构
- [feishu-schema.md](../feishu-schema.md) — 飞书表 22 字段定义
- [tutorial/01-04](.) — v0.1 legacy 教程(基础同步 / 短链 / 反向 / 字段定制)
