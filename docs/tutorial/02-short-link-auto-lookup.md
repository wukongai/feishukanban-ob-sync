# Tutorial 02: 短链自动反查 + cache(零手动 manage 链接)

> 🎯 **目标**:理解为什么 sync.py 能让你"从飞书后台复制短链贴 OB,后续 sync 全自动接管"。读完你能解释:短链 vs 长链 / 反查机制 / cache 注释。
>
> ⏱️ **预计阅读**:10 分钟

---

## 场景

你在飞书后台手动新建了一条 task,觉得"等会再到 OB 关联吧"。点 record 右键 → 复制记录链接,拿到的是**短链**:

```
https://<your-tenant>.feishu.cn/record/AbcDefGhi1234567890QwertyUio
```

回到 OB,粘贴到 task 行:

```markdown
- [x] [【布丁】直播功能开发](https://<your-tenant>.feishu.cn/record/AbcDefGhi1234567890QwertyUio) 🔺 ➕ 2026-05-19 ✅ 2026-05-19
```

跑 sync,你期望它能识别这个短链 → 找到对应 record → UPDATE 字段。

---

## 飞书 4 种 URL 格式对照

|格式 | 例子 | 浏览器点击 | sync.py 能直接用吗 |
|----|------|-----------|-------------------|
| **短链**(用户常拿到这个) | `feishu.cn/record/AbcDefGhi...`(27 位 token) | ✅ 直接弹 record 详情面板 | ❌ 不能直接拿 record_id |
| **base 长链**(2026-05-19 起 sync 默认写这个) | `feishu.cn/base/<base_token>?table=<tbl>&record=rec_xxx` | ✅ 稳定弹 record 详情 | ✅ 直接拿 rec_xxx |
| **wiki 长链**(历史兼容) | `feishu.cn/wiki/<wiki_node_token>?...&record=rec_xxx` | ⚠️ 不稳定弹详情(SDK race condition) | ✅ 直接拿 rec_xxx |
| **纯 record_id** | `rec_xxx`(只用于 cli) | — | ✅ |

**关键限制**:**短链 27 位 token 不能从 record_id 反推**(飞书 OpenAPI 没暴露 share token 生成 endpoint),但**点击体验最佳**,所以用户经常用。

---

## sync.py 怎么处理短链

老版本(2026-05-18 Phase 2.1):**看到短链直接跳过**,让你手动改成长链。**用户烦**。

新版本(2026-05-18 Phase 2.3):**自动反查 + cache**:

```
1. 看到 task 行的 URL 是短链(27 位 token)
   ↓
2. 调 feishu-cli 按 task 标题反查飞书表(lazy cache,一次 sync 仅 1 次 cli)
   ↓
3. 反查命中单一 rec_id → 自动走 UPDATE
   ↓
4. apply 成功后,在 task 行末尾**注入 HTML 注释 cache**:
   <!-- rec=rec_xxxxxxxxxxxxxx -->
   ↓
5. 下次 sync:O(1) 读注释,无 cli 调用
```

---

## 实战:第一次跑(触发反查)

`journals/2026-05-19.md` 内容:

```markdown
- [x] [【布丁】直播功能开发](https://<your-tenant>.feishu.cn/record/AbcDefGhi1234567890QwertyUio) 🔺 ➕ 2026-05-19 ✅ 2026-05-19
```

跑:

```bash
python3 ./sync.py "journals/2026-05-19.md" --only-completed
```

dry-run 输出:

```
--- Task 1: 【布丁】直播功能开发
    🔗 URL 是短链(27 位 token: AbcDefGhi...)
    ⏳ 调 cli 拉全表 record 建标题索引(查重 + 短链反查用)... ✅ 共 402 条 record, 387 个独立标题
    🔍 按标题反查:"【布丁】直播功能开发"
    ✅ 命中单一 rec_id: rec_xxxxxxxxxxxxxx
    🚀 走 UPDATE 路径
    💡 apply 成功后会在 task 行尾注入 <!-- rec=rec_xxx... --> cache
    fields payload:
      执行状态: ["Done"]
      完成时间: 1716000000000

📊 完成: 0 [新建] / 1 [更新] / 0 [跳过] / 0 [失败]
```

apply 后,markdown 变成:

```diff
- - [x] [【布丁】直播功能开发](https://<your-tenant>.feishu.cn/record/AbcDefGhi1234567890QwertyUio) 🔺 ➕ 2026-05-19 ✅ 2026-05-19
+ - [x] [【布丁】直播功能开发](https://<your-tenant>.feishu.cn/record/AbcDefGhi1234567890QwertyUio) 🔺 ➕ 2026-05-19 ✅ 2026-05-19 <!-- rec=rec_xxxxxxxxxxxxxx -->
```

**注意**:
- ✅ 短链保留(点击体验最佳)
- ✅ rec_id 注释 cache 写进行末(`<!-- ... -->` Obsidian 渲染时不可见)
- ✅ 后续 sync 不再触发反查

---

## 实战:第二次跑(O(1) cache 命中)

同一个 task,你又勾对勾改个优先级:

```markdown
- [x] [【布丁】直播功能开发](https://<your-tenant>.feishu.cn/record/AbcDefGhi...) 🔼 ➕ 2026-05-19 ✅ 2026-05-19 <!-- rec=rec_xxx... -->
```

跑 sync:

```
--- Task 1: 【布丁】直播功能开发
    🔗 URL 是短链,但发现行末 cache: <!-- rec=rec_xxx... -->
    ⚡ O(1) cache 命中,无 cli 调用
    🚀 走 UPDATE 路径
    fields payload:
      执行状态: ["Done"]
      ...
```

**性能差距**:第一次反查 ~3 秒(取决于飞书表大小),后续 < 10ms。

---

## 反查失败 / 歧义处理

### 场景 1: 飞书表里**没有**这个标题

```
🔍 按标题反查:"【布丁】直播功能开发"
❌ 飞书表里没有这个标题
⏭️  静默跳过本 task + 警告
```

**原因**:可能你删错了 record,或者标题改过。**处理**:去飞书后台确认 record 还在不在,改 OB task 标题对齐。

### 场景 2: 同名 record 多条(歧义)

```
🔍 按标题反查:"【布丁】直播功能开发"
⚠️  歧义:飞书有 3 条同名 record
  - rec_aaa
  - rec_bbb
  - rec_ccc
⏭️  跳过本 task + 警告:人工裁决(改标题让其唯一,或直接贴长链强制)
```

**处理**:
- 改 OB task 标题让其唯一(如加上日期 / 项目代号)
- 或直接到飞书复制其中一条的长链,贴到 OB task 行(强制指定 record)

---

## 为什么不用短链 token 直接 cli?

```bash
feishu-cli bitable record get --record-id AbcDefGhi1234567890QwertyUio
```

❌ **失败** — cli 需要 rec 开头的 record_id,27 位短链 token 不被 cli 接受。这是飞书 OpenAPI 的设计限制(短链是分享态的 UI 标识,不是数据层 ID)。

---

## 流程总结

```
飞书后台手建 record → 复制短链(用户最自然的姿势)
    ↓
贴到 OB task 行
    ↓
首次 sync:cli 拉全表 → 标题反查 → 拿 rec_id → 注入 cache 注释
    ↓
后续 sync:O(1) cache 命中,无 cli 调用
    ↓
用户体感:"我从飞书复制了链接,sync 就跑通了"
```

**核心设计哲学**:**不要让用户 manage 链接格式**。用户用最自然的姿势(复制短链),工具适配用户行为。

---

## 常见疑问

### Q1: 我手动删了 `<!-- rec=... -->` 注释会怎样?

下次 sync 重新走反查路径(~3 秒 cli 调用),命中后又会写回 cache 注释。无副作用,只是浪费一次 cli 调用。

### Q2: 我同时改了 task 标题和 rec_id 不一致怎么办?

`<!-- rec=... -->` 优先 — sync 信 cache,不再按新标题反查。如果你**故意要改标题对应到不同 record**,需要先手动删 `<!-- rec=... -->` 注释,然后改标题,sync 会重新反查。

### Q3: 反查命中 0 条会自动 CREATE 吗?

**不会** — 跳过 + 警告。CREATE 路径只在 task 完全没 URL(无短链 / 长链 / cache)时触发。这是为了避免**用户复制错短链 → sync 找不到 → 自作主张建新 record**。

### Q4: cli 拉全表很慢怎么办?

402 条 record 大约 4 秒。> 1000 条会变慢。**优化**:
- 当前实现是 lazy cache(全 sync 只调 1 次 cli)
- 未来考虑增量(`feishu-cli bitable record search` API,但有限流 800004135)

---

## 下一步

- 📖 [Tutorial 01: 基础正向 sync](./01-basic-push-sync.md) — 复习正向流程
- 📖 [Tutorial 03: 反向 pull](./03-reverse-pull.md) — 飞书 → OB 方向
- 📖 [Tutorial 04: 字段映射定制](./04-field-mapping-customization.md) — 改 config 加新字段
