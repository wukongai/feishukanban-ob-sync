# 起手指令(给 feishukanban-ob-sync CC)

把下面整个代码块原样复制到 VS Code 内打开的 feishukanban-ob-sync CC 会话:

```
@feishukanban-ob-sync CC 请读
docs/handoff/OB对接/2026-06-02-sync-py-select字段校验增强-handoff.md
按 6 步启动指令执行。

核心需求一句话:sync.py 现状只对 iteration_week/month 走 best_match_enum 校验,
其他 select 字段(category/subcategory/project_minor/adhd_priority 等)直接传 frontmatter 原值,
飞书白名单外值会触发 code=800010401 invalid_request 宽泛报错。
要求:dry-run 阶段主动拉 field schema 校验所有 select 字段 + 失败时给清晰建议 +
新增 --strict-select flag 让 skill 路径默认启用,与 --strict-soft-sections 平行。

事故复现用例:project_minor: [CC 工程化, 数据分析] + apply
→ 期望看到清晰报错 + 修复建议,而不是飞书的 invalid_request 宽泛错误。

参考实现:sync.py:1502-1552 已有的 best_match_enum + _ENUM_MATCH_CACHE 模式(2026-05-18 你做的)。
新加 _FIELD_OPTIONS_CACHE 整张 schema 一次拉、所有字段共用即可。

不包括的工作(OB CC 自己做):改 SKILL.md「apply 前自检清单」加 select 校验条目,
等你的反向回执来后再改(看你 --strict-select 是否默认启用决定怎么改)。

完成后写反向回执 2026-06-02-sync-py-select字段校验增强-完成回执.md
带:版本号 + commit hash + 实际耗时 + 反测 4 个用例的结果 + OB 端待办(如有)。
```

复制完整代码块 → 粘贴给 feishukanban-ob-sync CC → 完。
