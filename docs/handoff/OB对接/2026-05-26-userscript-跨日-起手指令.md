---
created: 2026-05-26T19:00:00
type: 起手指令
related_handoff: "[[2026-05-26-userscript-跨日-handoff.md]]"
---

# 起手指令 — userscript 跨日支持

> 用户从 OB Claudian 移交过来。打开 `/Users/aim5/Documents/CodingProject/feishukanban-ob-sync/` 启动 CC,粘贴下方代码块作为第一句指令。

```
@feishukanban-ob-sync CC

OB Claudian 移交一个任务给你:

把 docs/handoff/OB对接/2026-05-26-userscript-跨日-handoff.md 读完,
按「实施任务」6 步顺序执行:

1. 加 getDateContext() 函数到 obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js
2. 替换 Step 4 的 dateContext 计算(bjDate → dateContext + createdISO)
3. 更新 frontmatter 字段引用(today_history + created)
4. 更新 JSDoc 注释
5. CHANGELOG.md 加 v0.2.5 条目
6. commit + tag v0.2.5,不 push(等用户 review)

完成后:
- 在 handoff 文件「完成记录」section 填写实际花费 + commit hash + 偏离点
- 改 frontmatter status: handoff-pending → done
- 通知用户实测 4 个验收场景(handoff「单元测试场景」表)

注意:
- 不要 push 远端
- 不要主动改 OB vault 内文件(rules / journal / task md 都不动,那是 OB CC 的活)
- 如有疑问/异议,写到「Spec 偏离」section,带回 OB CC 决策
```
