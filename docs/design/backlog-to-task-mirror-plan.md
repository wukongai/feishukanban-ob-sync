---
created: 2026-06-04
status: plan-ready
type: plan
topic: 布丁 backlog ↔ OB task md 自动镜像 — 实施 plan
related_spec: "[[backlog-to-task-mirror.md]]"
estimated_total: 7-9 小时(分 7 Phase)+ 1 周观察
---

# 布丁 backlog ↔ OB task md 镜像 — 实施 plan

> 前置阅读:[[backlog-to-task-mirror.md]] 第 3.2 节字段 schema + 第五节 Phase 划分
> **执行原则**:每 Phase 独立可交付,做完任一 Phase 都有可见价值

---

## Phase 0:前置依赖(等 zhixing-game 回执)

**条件**:zhixing-game backlog status 全量对齐回执已交付(handoff `2026-06-04-backlog-status-对齐-handoff.md` 完成)
**预估**:对方 30~60 min,这边不做事
**判定**:vault 里 `04 Inbox/task/` 暂时不动,等 backlog 干净再说

> ⏸ Phase 1 不依赖 Phase 0,可以**并行开工**;但 Phase 4 backfill 必须等 Phase 0 完成

---

## Phase 1:中间件 `scripts/backlog_to_task.py`

**预估**:2-3 h
**位置**:`feishukanban-ob-sync/scripts/backlog_to_task.py`

### 1.1 CLI 接口

```bash
# 单文件同步(hook / userscript 调用)
python3 scripts/backlog_to_task.py --backlog <绝对路径> [--dry-run] [--vault <vault路径>]

# 批量扫描(漂移检测前置 / 兜底用)
python3 scripts/backlog_to_task.py --scan [--backlog-dir <目录>] [--dry-run]

# 模式:create(默认) / update / report-only
python3 scripts/backlog_to_task.py --backlog X --mode report-only
```

### 1.2 核心模块

```python
# 伪代码骨架
def main():
    args = parse_args()
    vault_root = args.vault or default_vault()
    backlog_md = args.backlog or scan_mode(args.backlog_dir)

    for backlog_path in backlog_md:
        bl = parse_backlog_frontmatter(backlog_path)
        slug = derive_slug(backlog_path)  # P1-习惯养成打卡

        existing = find_existing_task(vault_root, slug)
        if existing:
            update_task_mirror_fields(existing, bl, args.dry_run)
        else:
            create_task_md(vault_root, bl, slug, args.dry_run)

        log_to_sidecar(slug, action, args.dry_run)
```

### 1.3 frontmatter 映射表

| backlog 字段 | task md 字段 | 处理 |
|---|---|---|
| `title` 或 H1 | `# 【布丁开发】<title>` | 拼前缀 |
| `priority`(P0/P1/optim) | `backlog_priority` | 镜像 |
| `priority` | `priority` | 转 OB 三档:P0→P1,P1→P1,P2→P2,P3→P3,optim→P3,idea→P3,unrated→P3 |
| `status` | `backlog_status_seen` | 镜像(用于漂移检测) |
| `status` | `status` | **新建时固定 `todo`**(用户拍板),已存在不动 |
| `created` | `created` | 镜像(date-only 抽前 10 字符) |
| `estimate` | `estimate_hours` | 试图解析"1-2h"→ 2,"5~7天"→ 56;失败留空 |
| `tags` | `tags` | 合并 `[task, auto-from-backlog]` + backlog tags |
| `related_spec` | `## 🔗 相关资料` 区块插入 | 不去 frontmatter,放正文链接 |
| (新增) | `backlog_source: "[[<slug>]]"` | wikilink |
| (新增) | `backlog_path: "docs/backlog/<slug>.md"` | 相对仓库路径 |
| (新增) | `backlog_synced_at` | ISO datetime |
| (新增) | `parent_project: "[[布丁]]"` | 固定值 |

### 1.4 task md 模板(新建时套用)

```yaml
---
priority: {{mapped_priority}}
status: todo                  # 用户拍板
today: false
today_source:
today_source_history:
today_history: []
created: {{backlog.created}}
done_date:
due:
category:
subcategory:
project_minor:
adhd_priority:                # 空,用户填
estimate_hours: {{parsed_estimate}}
actual_hours:
efficiency:
quality:
parent_project: "[[布丁]]"
parent_subproject:
parent_task:
parent_inspiration:
日志:
feishu_record:                # 空,等用户决定推飞书
feishu_url:
iteration_week: []
iteration_month: []
completion_month:
backlog_source: "[[{{slug}}]]"
backlog_path: "docs/backlog/{{slug}}.md"
backlog_priority: {{backlog.priority}}
backlog_status_seen: {{backlog.status}}
backlog_synced_at: {{now_iso}}
tags:
  - task
  - auto-from-backlog
---

# 【布丁开发】{{title}}

## 👥 用户故事

## ✅ 验收条件

## 💡 执行思路

## 📝 执行概述
(自动从 backlog 镜像 — 见 [[{{slug}}]])

## 📈 执行明细

## 📦 交付

## 🔗 相关资料
- 上游 backlog:[[{{slug}}]]
{{related_spec_links}}

## 🪞 复盘

## ✅ 完成标记
- [ ] 待用户决定推飞书后,sync.py --create-task 推一份
```

### 1.5 幂等性 — find_existing_task

```python
def find_existing_task(vault_root, slug):
    """grep vault 04 Inbox/task/*.md 找有没有 backlog_source [[slug]]"""
    task_dir = vault_root / "04 Inbox/task"
    for md in task_dir.glob("*.md"):
        text = md.read_text()
        if re.search(rf'^backlog_source:\s*"\[\[{re.escape(slug)}\]\]"', text, re.MULTILINE):
            return md
        if re.search(rf'^backlog_path:.*{re.escape(slug)}\.md', text, re.MULTILINE):
            return md
    return None
```

### 1.6 update 模式(已存在 task md 时)

**只更新映射字段,不动 user-managed**:
- 更新:`backlog_priority` / `backlog_status_seen` / `backlog_synced_at` / `parent_project`
- 不动:`status` / `today` / `today_source` / `adhd_priority` / `estimate_hours`(用户可能改了)/ `feishu_record` / `feishu_url` / `done_date` / 正文所有区块

### 1.7 日志

- 落地位置:`~/.claude/logs/backlog-to-task-YYYY-MM.log`
- 每行 JSON:`{"ts": ..., "slug": ..., "action": "create|update|skip|error", "vault_path": ..., "dry_run": bool}`

### 1.8 DoD

- [ ] CLI 三个模式都能跑(create/update/scan)
- [ ] `--dry-run` 默认开,显式 `--apply` 才写文件
- [ ] 在真实 vault 跑一次,新建 1 条 task md 验证 frontmatter 字段全对
- [ ] 重跑同一 backlog,不重复建(走 update,只改 synced_at)
- [ ] 日志写到 ~/.claude/logs/
- [ ] 单元 case 5 个:新建 / 重跑 / status 镜像 / estimate 解析失败 / tags 合并

---

## Phase 2:OB QuickAdd 升级 Template → Macro

**预估**:1.5-2 h
**前置**:Phase 1 dry-run 跑通

### 2.1 新建 UserScript 文件

位置:`feishukanban-ob-sync/obsidian-assets/userscripts/quickadd-新建布丁需求-后处理.js`

```javascript
// 接 Macro 上一步 Template 输出(刚创建的 backlog md 路径)
// 调中间件,落 task md
module.exports = async (params) => {
  const { app, quickAddApi, variables } = params;
  const { obsidian } = params;

  // 上一步 Template 已创建 backlog md,文件名格式 idea-{{NAME}}.md
  // 位置:应用产品/布丁/zhixing-game-docs/backlog/
  // 经 symlink → ~/Documents/CodingProject/zhixing-game/docs/backlog/

  const fileName = variables.NAME || quickAddApi.utility.getLastCreatedFilename();
  const backlogAbsPath = `/Users/aim5/Documents/CodingProject/zhixing-game/docs/backlog/idea-${fileName}.md`;

  const { exec } = require('child_process');
  const cmd = `python3 /Users/aim5/Documents/CodingProject/feishukanban-ob-sync/scripts/backlog_to_task.py --backlog "${backlogAbsPath}" --apply`;

  exec(cmd, (err, stdout, stderr) => {
    if (err) {
      new obsidian.Notice(`❌ task 镜像失败:${err.message}`, 8000);
    } else {
      new obsidian.Notice(`✅ 已镜像到 task 看板:${fileName}`, 5000);
    }
  });
};
```

### 2.2 install.sh 更新

把新 userscript 加入 install.sh Step 6 的 `.quickadd-choices.json` 输出(可选,因为 Macro 改造需要用户在 UI 手配)。

### 2.3 用户配置步骤(给用户的指引,放 tutorial/)

1. Cmd+P → QuickAdd: Manage Choices
2. 找到「🎮 新建布丁需求」(Template 类型)
3. 点🔄改成 Macro
4. 加 Macro step 1:**Template** → 选原模板 `好奇猫开发需求模版.md`,保留 fileNameFormat / folder
5. 加 Macro step 2:**UserScript** → 选 `quickadd-新建布丁需求-后处理.js`
6. 测试:Cmd+P → 新建一个测试 backlog → 看 vault 弹 Notice ✅

### 2.4 降级 fallback

如果用户不想升级 QuickAdd → 仍可用,只是依赖 Phase 5 漂移检测(每日 24h 内自动补)。

### 2.5 DoD

- [ ] UserScript 文件写好放对位置
- [ ] 用户配合 UI 改了一次 QuickAdd 类型
- [ ] 真实 Cmd+P 测试一遍:建 backlog → 自动 task md 出现在 `04 Inbox/task/`
- [ ] Notice 报告成功/失败
- [ ] tutorial/06-backlog-to-task-mirror.md 写好配置步骤

---

## Phase 3:zhixing-game `.claude/hooks/post-backlog-sync.py`

**预估**:1 h
**前置**:Phase 1 dry-run 跑通

### 3.1 hook 脚本

位置:`~/Documents/CodingProject/zhixing-game/.claude/hooks/post-backlog-sync.py`

```python
#!/usr/bin/env python3
"""
PostToolUse hook:监听 Write/Edit/MultiEdit 到 docs/backlog/<前缀>-*.md
触发后 exec feishukanban-ob-sync 的 backlog_to_task.py 中间件
失败 exit 0 不阻塞 CC
"""
import json
import sys
import os
import subprocess
import re
from pathlib import Path

BACKLOG_PATTERN = re.compile(r'/docs/backlog/(P[0-3]|optim|idea|unrated|fix)-[^/]+\.md$')
MIDDLEWARE = Path.home() / "Documents/CodingProject/feishukanban-ob-sync/scripts/backlog_to_task.py"

def main():
    try:
        if os.environ.get("BACKLOG_TO_TASK_DISABLE") == "1":
            sys.exit(0)

        payload = json.load(sys.stdin)
        tool_name = payload.get("tool_name", "")
        if tool_name not in ("Write", "Edit", "MultiEdit"):
            sys.exit(0)

        file_path = payload.get("tool_input", {}).get("file_path", "")
        if not BACKLOG_PATTERN.search(file_path):
            sys.exit(0)

        if Path(file_path).name in ("README.md", "_index.base"):
            sys.exit(0)

        # 异步触发(不阻塞 CC)
        subprocess.Popen(
            ["python3", str(MIDDLEWARE), "--backlog", file_path, "--apply"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        sys.exit(0)
    except Exception:
        # 任何异常都不阻塞 CC
        sys.exit(0)

if __name__ == "__main__":
    main()
```

### 3.2 settings.json 挂载

改 `~/Documents/CodingProject/zhixing-game/.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          { "type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/post-backlog-sync.py" }
        ]
      }
    ]
  }
}
```

(如果已有 PostToolUse 数组,append 进去)

### 3.3 DoD

- [ ] hook 脚本可执行权限(`chmod +x`)
- [ ] settings.json 挂上
- [ ] 真实测试:在 zhixing-game CC 会话里 Write 一个 backlog md → 几秒后 vault 出现对应 task md
- [ ] env `BACKLOG_TO_TASK_DISABLE=1` 能关
- [ ] hook 失败不阻塞(故意写错 middleware 路径测试)

---

## Phase 4:历史 170+ 条回填 `scripts/backlog_backfill.py`

**预估**:1.5 h 脚本 + 1 h 跑批 review
**前置**:Phase 0 完成(zhixing-game backlog status 已对齐),Phase 1 中间件可用

### 4.1 三档模式

```bash
# 档 1:report-only(只统计,不动文件)
python3 scripts/backlog_backfill.py --report-only

# 档 2:dry-run(显示每条会做什么,不写文件)
python3 scripts/backlog_backfill.py --dry-run

# 档 3:apply(真改文件)
python3 scripts/backlog_backfill.py --apply
```

### 4.2 主题模糊匹配(避免重建已有 task)

对每条 backlog,在 vault `04 Inbox/task/*.md` 用启发式找潜在重复:
- 标题关键词(去停用词)交集 ≥ 2 个
- tags 交集 ≥ 1 个
- 时间窗(task created 在 backlog created 前后 ±30 天内)

报告输出:
```
[backlog] P1-习惯养成打卡.md
  ✅ 可能已有 task:2026-05-26-【布丁开发】功能：日常习惯打卡.md(标题交集=2,tags 交集=1)
  → 推荐动作:关联(给已有 task 加 backlog_source 字段),跳过新建
  → y/n/skip(交互式问)?

[backlog] P0-小程序付费态从0实现-对齐H5.md
  ⚠️ 未找到匹配 task
  → 推荐动作:新建 task md
  → y/n/skip?
```

### 4.3 关联模式(对已有 task)

- 已有 task md 没 `backlog_source` 字段 → 加上
- 已有 task md 已有 `backlog_source` 但不同 slug → 警告,人工 review

### 4.4 DoD

- [ ] `--report-only` 跑一遍输出对账表(预计 170 行)
- [ ] 用户人工 review 对账表
- [ ] `--dry-run` 跑一遍看具体改动
- [ ] `--apply` 真改前 git status 干净(可回滚)
- [ ] 改完跑一次完整性 check:vault task md 跟 backlog md 1:1 对账

---

## Phase 5:漂移检测 `scripts/backlog_drift_check.py`

**预估**:1.5 h
**前置**:Phase 4 完成(全量基线建好)

### 5.1 检测维度

- **status 漂移**:task md 的 `backlog_status_seen` ≠ 当前 backlog status
- **孤儿 task**:task md 有 `backlog_source` 但对应 backlog 文件已不存在 → 标 `backlog_orphaned: true`
- **孤儿 backlog**:backlog 文件存在但 vault 无对应 task md → 触发中间件补建
- **重复 task**:多个 task md 引用同一 backlog slug → 告警

### 5.2 输出 weekly report

```markdown
# 🔄 布丁需求镜像漂移报告 2026-W23

## 概览
- backlog 总数:172
- task md 总数:148
- 镜像匹配:142
- 漂移项:6

## status 漂移(3 条)
- [P1-视频音频付费试看] backlog=done, task last seen=doing → 建议:更新 task `backlog_status_seen: done` + 提醒用户检查 done_date

## 孤儿 task(2 条)
- [2026-05-26-XXX] backlog_source=[[P1-旧需求]] 但 backlog 已不存在 → 标 backlog_orphaned

## 孤儿 backlog(1 条)
- [P2-新需求-202606] 无对应 task → 自动补建

## 重复 task(0 条)
```

### 5.3 自动触发(可选)

cron 或 launchd 每周日 21:00(对齐 OB 跨项目需求池 spec 的巡检时间)。

### 5.4 DoD

- [ ] 手动 `python3 scripts/backlog_drift_check.py --week 23 --apply` 能跑
- [ ] 报告输出到 `~/.claude/reports/backlog-drift-YYYY-WNN.md`
- [ ] 自动触发(可暂缓)

---

## Phase 6:文档对齐

**预估**:1 h

### 6.1 必改文档

- `README.md` — 顶部 v0.X.Y badge bump + 加「自动镜像」section
- `CHANGELOG.md` — 加版本 entry(预计 v0.8.0 minor bump)
- `docs/ARCHITECTURE.md` — 加镜像架构图(本 plan Phase 0 数据流)
- `docs/VERSION.md` — bump
- `obsidian-assets/userscripts/README.md` — 加新 userscript 说明
- 新建 `docs/tutorial/06-backlog-to-task-mirror.md` — 用户教程(配置 Macro + 测试)

### 6.2 DoD

- [ ] 6 个文档都改了
- [ ] README badge 跟 VERSION 一致
- [ ] CHANGELOG entry 引用本 plan
- [ ] git status 干净后 commit + tag + 等用户 review push

---

## Phase 7:dogfood 1 周观察

**预估**:1 周日历时间
**做事**:正常用 Cmd+P 建 backlog / 在 zhixing-game CC 让它建 backlog,看是否每条都自动出现在 task 看板

### 7.1 验证 checklist

- [ ] OB Cmd+P 建 5 条 backlog,5 条都有对应 task md
- [ ] zhixing-game CC 建 3 条 backlog,3 条都有对应 task md
- [ ] task md 的 `backlog_source` 字段都对
- [ ] 重跑同一 backlog 不重建
- [ ] backlog 改名 → 漂移检测识别孤儿
- [ ] 一周内没漏一条

### 7.2 反馈调整

- 收集用户反馈(命名 / 字段 / 流程不顺)
- 出 patch 版本修

---

## 总览

| Phase | 预估 | 阻塞依赖 | 可并行 |
|-------|------|---------|--------|
| 0 | 30-60 min(对方) | — | ✅(跟 Phase 1 并行) |
| 1 | 2-3 h | — | — |
| 2 | 1.5-2 h | Phase 1 dry-run 通 | — |
| 3 | 1 h | Phase 1 dry-run 通 | ✅(跟 Phase 2 并行) |
| 4 | 2.5 h | Phase 0 + Phase 1 | — |
| 5 | 1.5 h | Phase 4 | — |
| 6 | 1 h | Phase 5 | — |
| 7 | 1 周 | Phase 6 | — |

**MVP 路径**(最小可用):Phase 0 + 1 + 2 ≈ 3-5 h,Cmd+P 建 backlog 自动出 task md
**完整路径**:全 7 Phase ≈ 7-9 h + 1 周观察
