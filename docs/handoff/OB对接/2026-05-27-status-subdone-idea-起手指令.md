---
created: 2026-05-27T20:00:00
type: 起手指令
target_cc: feishukanban-ob-sync(VS Code)
handoff: "[[2026-05-27-status-subdone-idea-handoff]]"
---

# 起手指令 — status 7 态对齐(v0.3.5)

把以下内容**整段复制**给 feishukanban-ob-sync CC:

---

@CC 读 `docs/handoff/OB对接/2026-05-27-status-subdone-idea-handoff.md` 全部章节,然后:

1. 跑 3 项 startup 核对(handoff 末尾「启动指令」section 列了)
2. 从 Phase 1.1 开始按顺序实施,每个 Phase 完成后简短自评
3. Phase 4 测试前等我准备好飞书 app 那边的 SubDone test record
4. Phase 5 commit + tag,**不要 push**,留给我手动跑 `git push all main && git push all v0.3.5`

需求一句话:**飞书侧加了 SubDone 状态,sync.py 4 处映射逻辑缺 subdone/idea 支持。OB 端 dataview + schema + rules 已就位(handoff 接口契约 section 列了),你这边对齐 7 态对应改 sync.py + config.yaml + CHANGELOG + bumb v0.3.5**。

handoff 状态:`handoff-pending`,完成后改 `done` + 写反向回执 `docs/handoff/OB对接/2026-05-27-status-subdone-idea-反向回执.md`。
