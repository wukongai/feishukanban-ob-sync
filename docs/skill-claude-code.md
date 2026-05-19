---
name: 飞书项目同步
description: 双向同步 Obsidian 日志 task ↔ 飞书项目管理多维表。在日志里勾选 [x] 完成 → 一键回填飞书字段;在日志写新 task → 一键自动创建飞书 record 并写回链接到 markdown。当用户说"同步飞书项目"、"同步飞书"、"把日志推到飞书"、"飞书项目同步"时使用。
---

# 飞书项目同步 skill(给 Claude Code 用户)

> **使用场景**:如果你在用 Claude Code,可以把这个 skill 加到你的 vault `.claude/skills/` 目录,让 Claude 自然语言触发同步流程,自动走 5 步 SOP + 强制 TodoWrite。
>
> **不用 Claude Code 也没关系**:直接 `python3 sync.py ...` 跑命令也完全可用,本 skill 只是 AI 协同加成。

---

## 安装 skill

```bash
# 在你的 vault 根目录下
mkdir -p .claude/skills/feishu-project-sync
cp /path/to/feishu-ob-sync/docs/skill-claude-code.md .claude/skills/feishu-project-sync/SKILL.md
```

重启 Claude Code 后,你说"同步飞书"或"飞书项目同步",skill 自动触发。

---

## 核心定位

> **设计哲学**:把"日志当指挥中心,飞书当看板"的工作流自动化。

| 方向 | 命令 | 行为 |
|------|------|------|
| **OB → 飞书** | `sync.py <journal>.md --apply` | 勾 `[x]` → 飞书字段自动填 / 新 task → 自动建 record + 写回链接 |
| **飞书 → OB** | `sync.py --pull --apply` | 飞书侧"是否今日"=true → 拉到 today journal(查重 + 升级老链 + fallback) |

---

## 使用方式

### 基础命令(在当前 journal 上跑)

```bash
# 1. dry-run 预览(默认,不写飞书)
python3 ./sync.py "journals/2026-05-19.md"

# 2. 只看已完成 task(更安全,推荐做演示)
python3 ./sync.py "journals/2026-05-19.md" --only-completed

# 3. dry-run 通过后,真正写入飞书
python3 ./sync.py "journals/2026-05-19.md" --only-completed --apply
```

### 反向同步:飞书 → OB

把飞书侧「是否今日」=true 的 task 拉到 today journal。

```bash
# dry-run 预览(必跑,看影响范围 + 假阳性人工审)
python3 ./sync.py --pull

# 真写入(等用户审批准词)
python3 ./sync.py --pull --apply
```

**行为**:
1. cli 拉飞书全表 record(client-side filter "是否今日"=true)
2. 对每条候选 task 按**标题前缀 10 字** grep 全 vault journal 查重
3. **已在今日 journal** → 跳过(避免重复)
4. **命中其他历史日志(老短链)** → 升级老短链为 base 长链(让老 task 进入可 sync 范围)
5. **未命中** → 新写到 today journal 对应段(按价值优先级 P0/P1/P2 → 「🎯 今日计划」;P3/无 → 「🐿️ 今日非计划」)
6. **fallback**:飞书 Done 但完成日空 → OB 写 `[ ]` 未完成 + dry-run 警告

**已知限制**:
- **简单版**:无 cli flag override(`--pull` 始终用默认 filter)
- **标题前缀 10 字模糊匹配可能假阳性** → **dry-run 必审,人工裁决**
- **短链 token 不可自动生成** → 反向同步统一用 base 长链格式(稳定弹 record 详情)

---

## Skill 调用方式(给 Claude Code 用)

Claude 触发本 skill 时,**必须走 5 步 SOP**:

```
Step 1: 确认目标 journal 文件路径(默认当前 current_note,若不是日志要 ask)
Step 2: dry-run 把所有 task 解析 + 字段映射 payload 给用户看
Step 3: 给用户审 dry-run 输出 + 等明确批准词("通过/apply/同意/sync")
Step 4: --apply 真实写入飞书 + 自动写回 record_id 链接到 markdown
Step 5: 验证写入(reads back 飞书 record + 显示笔记 diff)
```

⚠️ **铁律**:apply 前必须先 dry-run 给用户审 + 等明确批准词。指令性语言("做完它/搞定")不算授权。

⚠️ **L2 强制 TodoWrite**:5 步 SOP 对应 5 个 todo,显式 mark `in_progress` / `completed`,让用户能中途打断纠错。

---

## task 行格式约定

skill 识别的 task 行格式(完全兼容 Obsidian Tasks 插件 emoji 元数据):

```markdown
- [x] [任务标题](https://<your-tenant>.feishu.cn/base/<base_token>?table=<tbl>&view=<view>&record=rec_xxx) 🔼 ➕ 2026-05-19 ✅ 2026-05-19
  ^^^                                                                                                       ^^^                       ^^^
  状态                                                                                                       优先级 emoji              完成日
```

| 标记 | 含义 | 写入习惯 |
|------|------|------------|
| `[ ]` | 未完成 | 默认 |
| `[x]` | 已完成 | 点击 / Cmd+L |
| `[/]` | 进行中 | 手动 |
| `[-]` | 放弃 | Tasks 自动加 ❌ |
| 🔺 | P0 | 用 emoji 优先级 |
| ⏫ | P1 | |
| 🔼 | P2 | |
| 🔽 | low | |
| ➕ 日期 | 创建日 | Tasks 自动 |
| ✅ 日期 | 完成日 | Tasks 自动 |
| ❌ 日期 | 放弃日 | Tasks 自动 |
| 🆔 短ID | 任务唯一 ID | Tasks 命令 |
| 🔁 every Sunday | 周期性任务 | Tasks 自动 |

⚠️ **inject_url_into_line bug 修复(2026-05-19)**:老正则 `\s+[emoji]` 只匹配第一个 emoji 前空白,会丢失后续 metadata。**新正则 `\s*[emoji].*` 保留所有 emoji 到行尾**,emoji 集合也加了 🔁。

---

## 字段映射规则

| OB 信号 | 飞书字段 | 映射 |
|---------|---------|------|
| task 文字(去掉 emoji) | 任务标题 | 1:1 |
| `[x]` 状态 | 执行状态 | Done |
| `[ ]` 状态 | 执行状态 | Todo |
| `[/]` 状态 | 执行状态 | Doing |
| `[-]` 状态 | 执行状态 | Block |
| `✅ 日期` | 完成时间 | ISO → 毫秒时间戳 |
| **3 路扫产物**(A/B/C) | **交付** | A/B/C 合并 union → 可点击链接 |
| 🔺/⏫/🔼/🔽 | (当前不映射,避免覆盖飞书侧"价值优先级"自主评估) | — |
| ✅ 完成日 → ISO 周 | 执行迭代周 | 26W20 / 25W53 等 |
| ✅ 完成日 → 年月 | 执行迭代月 | 26 年 5 月 |

完整映射在 `config.yaml`,改字段名或加映射改 yaml 即可,不用动脚本。

---

## 交付物同步(3 路扫产物 union)

**核心价值**:你在飞书项目看板能直接看到任务的具体交付物(教程、脚本、文档),点击链接自动跳回笔记或飞书云文档。

**3 种写法**(任选,可组合):

### A 同行 📎 wikilink(最轻,1-3 个产物)

```markdown
- [x] [task](飞书链接) ✅ 2026-05-16 📎 [[xxx.md]] [[yyy.py]]
```

### B callout 块(中,带备注)

```markdown
- [x] [task](飞书链接) ✅ 2026-05-16
  > [!note]- 📎 交付物
  > - [[xxx.md]] 教程文档
  > - [[yyy.py]] 同步脚本
```

### C 笔记 frontmatter 反向链接(重,epic 任务)

任意笔记加 frontmatter:

```yaml
---
title: <文档标题>
delivery_for:
  - <飞书 record_id>
---
```

sync 时全 vault 扫此字段,自动反向关联。**优点**:笔记天然按 PARA 落位,不依赖 task 行格式约定。

### 飞书侧渲染效果

```
交付物:
- [文档名](https://feishu.cn/docx/<doc_token>)  ← 蓝色超链接(原生渲染)
- [另一个文档](https://feishu.cn/docx/<doc_token>)

原话备注: <你已有的手工内容,自动保留>

——自动同步 2026-05-19——
```

**点击效果**:点链接 → **直接打开飞书云文档**(Mac/Windows/手机的飞书 App 全部可用)。

### 工作原理

sync 时自动把 .md 推到飞书云文档,doc_token 写回笔记 frontmatter:

```yaml
---
title: 文档标题
delivery_for: [rec_xxx]
feishu_doc_token: <doc_token>            # 自动写入
feishu_doc_synced_at: 2026-05-19T19:38:18  # 自动写入
---
```

下次 sync 检测到已有 token → 直接复用,不再重复推送(0 cli 调用)。

### ⚠️ 首次跑前提

需要先给 cli 加 docx scope(一次性):

```bash
feishu-cli auth login --scope "docx:document docx:document:create"
```

跟着提示去浏览器完成 OAuth 授权。

---

## CREATE 查重

**自动查重**:CREATE 新 record 前,sync 自动调一次 cli 拉全表 → 查同名 → dry-run 警告:

```
🆕 无飞书链接 → 将创建新 record
⚠️  警告:飞书已有 N 条同名 record
   - rec_xxx  (打开:...)
💡 apply 前你可选:
   ① 取消 sync → 复制 record 长链贴 task 行 → 重跑(走 UPDATE)
   ② 接受 CREATE(飞书将出现 N+1 条同名 record)
```

**注意**:同名仍会 CREATE — 警告只是让你**意识到** + 自主决定。不自动合并(避免误判)。

---

## 已知行为

1. **--only-completed flag**:只同步 `[x]` 和 `[-]`,跳过 `[ ]` 和 `[/]`。**推荐做日终复盘批量同步用**
2. **无 --only-completed 时**:所有 task 都同步,未完成的会以 Todo 状态建 record
3. **已有 record 链接的 task**:走 UPDATE 路径(不会重复建)
4. **无链接的 task**:走 CREATE 路径,新建后**自动 Edit markdown 写回链接**(无需手动)
5. **私事 task**:目前没有"跳过"机制,如要排除某条,**手动删 ✅ 日期或改 [/] 进行中** 即可避免 --only-completed 同步它

---

## 字段不存在的优雅降级

如果 config 里写了某字段(如「优先级」)但飞书表不存在,**脚本不会报错**,只是 cli 返回错误。**最佳实践**:在 dry-run 时看 payload 字段名 → 去飞书后台对照是否存在,不存在的就在 config.yaml 注释掉 `enabled: true` 行(留映射但禁用)。

---

## 跨周/月 enum 字段处理

「执行迭代周」「执行迭代月」字段是单选,**飞书表预定义 enum 选项**。如果当前选项里没有目标周/月(如 26W21 还没建),写入会失败。

**处理方案**:
- ✅ 推荐:在飞书后台预建 enum 选项(全年的 W01-W52 + 12 个月)
- ✅ 兜底:脚本静默跳过这两个字段(不阻断其他字段写入)
- ⚠️ 未来增强:加 `feishu-cli bitable field update` 自动补 enum 选项

---

## 相关文档

- 安装与配置:[INSTALL.md](../INSTALL.md)
- 基础正向 sync:[docs/tutorial/01-basic-push-sync.md](./tutorial/01-basic-push-sync.md)
- 短链自动反查 + cache:[docs/tutorial/02-short-link-auto-lookup.md](./tutorial/02-short-link-auto-lookup.md)
- 反向 pull:[docs/tutorial/03-reverse-pull.md](./tutorial/03-reverse-pull.md)
- 字段映射定制:[docs/tutorial/04-field-mapping-customization.md](./tutorial/04-field-mapping-customization.md)
