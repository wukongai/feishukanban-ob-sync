# Tutorial 03: 反向 pull(飞书 → OB)

> 🎯 **目标**:理解从飞书侧把 task 拉到 OB 当日 journal 的流程。读完你能解释:为什么要查重 / 怎么避免假阳性 / fallback 怎么用。
>
> ⏱️ **预计阅读**:10 分钟

---

## 场景

你的领导在飞书项目看板里点了几个 task 的「是否今日」字段勾上,意思"今天希望你处理这些"。你回到 OB 日志,想一键把这些 task 拉过来加到今日的「🎯 今日计划」段。

---

## 基础命令

```bash
# dry-run(必跑)
python3 ./sync.py --pull

# 真写入(等用户审 dry-run 后)
python3 ./sync.py --pull --apply
```

注意:`--pull` 不需要 journal 参数 — sync.py 自动找 vault root + 今日 journal(命名格式 `journals/YYYY-MM-DD.md`)。

---

## 工作流程

```
1. cli 拉飞书全表 record
2. client-side filter "是否今日" = true
3. 对每条候选 task,grep 全 vault journal/ 查重(标题前缀 10 字模糊匹配)
4. 分类处理:
   ├─ 已在今日 journal           → 跳过
   ├─ 命中其他历史日志(老短链) → 升级老短链为 base 长链
   └─ 未命中                       → 新写到今日 journal
5. 按优先级写入对应段:
   ├─ P0/P1/P2  → 「🎯 今日计划」段
   └─ P3/无优先级 → 「🐿️ 今日非计划」段
6. fallback:
   └─ 飞书 Done 但完成日空 → OB 写 [ ] 未完成 + dry-run 警告
```

---

## dry-run 输出示例

假设飞书有 4 条「是否今日」=true 的 task:

```bash
python3 ./sync.py --pull
```

```
=== 反向 pull:扫描飞书侧"是否今日"=true 的 task ===
⏳ 调 cli 拉全表 record ... ✅ 共 402 条 record
🔍 client-side filter "是否今日"=true → 4 条候选

--- Task 1: rec_aaa "回复客户邮件"
    🆕 全 vault journal 未命中
    ✏️  将新写到 journals/2026-05-19.md 「🎯 今日计划」(P1=⏫)
    生成 markdown:
      - [ ] [回复客户邮件](https://.../base/.../?record=rec_aaa) ⏫ ➕ 2026-05-19

--- Task 2: rec_bbb "评审 PRD v2"
    🔄 命中历史日志: journals/2026-05-14.md line 32
       老 URL: feishu.cn/record/XyzUvwTsr...(短链)
    💡 将升级为 base 长链 + 注入 <!-- rec=rec_bbb --> cache
    📍 不会复制到今日 journal(老 task 已存在)

--- Task 3: rec_ccc "调研 OAuth 集成方案"
    ⚠️  命中今日 journal: journals/2026-05-19.md line 47
    ⏭️  跳过(已在今日,避免重复)

--- Task 4: rec_ddd "撰写月度复盘"
    ⚠️  飞书"执行状态"=Done 但"完成时间"为空
    ⏭️  fallback:OB 写 [ ] 未完成 + dry-run 警告
    生成 markdown:
      - [ ] [撰写月度复盘](https://.../base/.../?record=rec_ddd) 🔼 ➕ 2026-05-19

📊 dry-run 完成:1 新写 / 1 升级 / 1 跳过 / 1 fallback
💡 apply 前你可选:
   - 接受所有: --apply
   - 跳过假阳性: --exclude-record rec_bbb,rec_ddd --apply
```

---

## 查重逻辑详解(防重复)

**为什么必须查重**:
- 老 task 用了**短链**(`record/AbcDefGhi...`),反向 pull 时拿到的是 **base 长链**(`base/.../?record=rec_xxx`)
- 字符级 grep `record_id` 完全不命中(两边字符串完全不同)
- 但实际飞书侧是**同一条 record**
- → 必须按**任务标题**查重

**查重算法**:
1. 提取 record 任务标题前 10 字(防过度精确匹配)
2. `grep -rl "<前10字>" journals/` 找所有命中文件
3. 解析命中行的 task 状态 + URL,做归类

**为什么前 10 字而不是完整标题**:
- 完整标题字符级匹配,容易漏(标题改过 / 中英文标点 / 全半角)
- 前 10 字模糊匹配,容忍小改动
- **代价**:可能有假阳性(2 个不同 task 共享前 10 字)→ **dry-run 必审**

---

## 防假阳性:dry-run + 人工裁决

**真实假阳性案例**:

```
飞书 task:【布丁开发】直播功能开发(rec_new)
OB 历史 task:【布丁开发】直播功能选型调研与设计(rec_old,5-16 日志)

前 10 字"【布丁开发】直播功能"完全相同 → 假阳性
```

这两个是**不同语义**(选型调研 = 调研工作 / 开发 = 实际编码),不应该升级。

**正确处理**:dry-run 看到这种命中,**用 `--exclude-record rec_new` 跳过它**,让 sync 走"新写"路径而不是"升级":

```bash
python3 ./sync.py --pull --exclude-record rec_new --apply
```

**门禁**:`--pull --apply` 前**必须 dry-run + 人工审升级列表**,不能盲信脚本的 best match。

---

## fallback 机制(Done 但完成日空)

飞书侧可能存在数据残缺的 record:

| 执行状态 | 完成时间 |
|---------|---------|
| Done | (空) |

正常情况 OB 写:`- [x] xxx ✅ <完成日>`,但完成日空怎么处理?

**fallback**:
- OB 写 `- [ ] xxx`(未完成,因为没完成日不算真正完成)
- dry-run 警告用户飞书数据残缺
- 不阻断其他 task 处理

**用户决策**:
- 接受:OB 写 `[ ]`,等飞书补完成日后再 sync 一次更新
- 修飞书:去后台手动补完成日,重跑 `--pull`

---

## 实战:apply 后效果

`journals/2026-05-19.md` 之前:

```markdown
## 🎯 今日计划

- [/] 写 PRD v2 草稿 🔺 ➕ 2026-05-19

## 🐿️ 今日非计划

(空)
```

apply 后:

```markdown
## 🎯 今日计划

- [/] 写 PRD v2 草稿 🔺 ➕ 2026-05-19
- [ ] [回复客户邮件](https://.../base/.../?record=rec_aaa) ⏫ ➕ 2026-05-19

## 🐿️ 今日非计划

- [ ] [撰写月度复盘](https://.../base/.../?record=rec_ddd) 🔼 ➕ 2026-05-19
```

`journals/2026-05-14.md` line 32 的老 task:

```diff
- - [ ] [评审 PRD v2](https://<tenant>.feishu.cn/record/XyzUvwTsr0987654321MlkjIhgFe) 🔼 ➕ 2026-05-14
+ - [ ] [评审 PRD v2](https://<tenant>.feishu.cn/record/XyzUvwTsr0987654321MlkjIhgFe) 🔼 ➕ 2026-05-14 <!-- rec=rec_bbb -->
```

注意:**老短链原样保留**(点击体验不变),只在行末加 `<!-- rec=... -->` cache 注释 → 后续正向 sync 能识别它。

---

## 常见疑问

### Q1: `--pull` 会不会重复拉相同 task?

不会。查重机制确保:
- 同 record_id 在历史日志 → 跳过/升级
- 同标题前缀在今日 journal → 跳过

### Q2: 我能筛选只拉某个项目的 task 吗?

当前 MVP **只支持** "是否今日"=true 这一个 filter。未来可能加 `--filter "project=xxx"` flag。

短期 workaround:在 config.yaml 加 `pull_filter` 字段(改代码不大,可作为开源仓库贡献机会)。

### Q3: 我手动改了今日 journal 的某条 task,反向 pull 会覆盖吗?

**不会** — 反向 pull 用查重机制识别"已经在今日 journal",跳过。它只会**新增**未命中的 task,不会**修改**已存在的。

### Q4: vault root 找不到怎么办?

报错:`vault root not found`。说明你跑 sync.py 时 cwd 不在 vault 内(没找到 `.obsidian/` 目录)。

**修复**:
```bash
cd /path/to/your/vault
python3 /path/to/feishu-ob-sync/sync.py --pull
```

或者把 sync.py copy 到 vault 内的某个工具目录跑。

---

## 流程总结

```
飞书侧勾"是否今日" = true
    ↓
跑 --pull dry-run
    ↓
查 4 类情况:已在今日 / 升级老链 / 新写 / fallback
    ↓
[假阳性] --exclude-record rec_xxx 跳过
    ↓
--apply 真写入 vault
    ↓
结果:今日 journal 含新 task / 老 journal 老链升级
```

---

## 下一步

- 📖 [Tutorial 01: 基础正向 sync](./01-basic-push-sync.md) — 反向跑完后,后续正向 sync 字段更新
- 📖 [Tutorial 02: 短链自动反查](./02-short-link-auto-lookup.md) — 老短链升级机制
- 📖 [Tutorial 04: 字段映射定制](./04-field-mapping-customization.md)
