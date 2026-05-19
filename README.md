# feishu-ob-sync

> 📋 在 **Obsidian 日志**和**飞书多维表项目管理**之间做双向同步,让你既享受 Obsidian 的 ADHD 友好「子弹笔记式任务流」,又拥有飞书的「项目看板可视化」。

![demo](docs/demo.gif)

> *演示 GIF 录制中——预计 Phase 5 上线*

---

## ✨ 为什么需要这个工具

你也许已经在 Obsidian 用 `Tasks 插件`管理日常任务,飞书侧用「多维表」做项目看板。痛点是:

| 痛点 | 现状 | 这个工具 |
|------|------|---------|
| OB 勾 `[x]` 完成 → 飞书侧字段不会自动联动 | 手动到飞书后台填"执行状态/完成时间/交付物链接" | OB 勾对勾 → sync 自动写入飞书字段 |
| OB 写新 task 没有飞书 record_id → 无法挂看板 | 手动到飞书新建 record + 复制链接贴回 OB | sync 自动 CREATE record + 写回长链到 markdown |
| 飞书侧新创建的 task("是否今日"标记)→ OB 端看不到 | 手动跨平台抄录 | 反向 `--pull` 自动拉到当日 journal |
| task 行 CREATE 时 `🆔/➕/✅/🔁` emoji metadata 丢失 | 老正则只匹配第一个 emoji 前空白 | **inject_url_into_line bug 修复:保留所有 emoji 到行尾** ⭐ |
| wiki 长链不稳定弹 record 详情(SDK race condition) | 用户体感"点击没跳到 record" | **base URL 全自动方案:稳定弹 record,完全程序化** ⭐ |

---

## 🎯 核心功能

```
┌──────────────────────────────────────────────────────┐
│  📤 正向 sync          OB journal task → 飞书 record │
│  🔄 反向 pull         飞书 task("是否今日") → OB    │
│  🔗 短链自动反查      短链 token → record_id O(1) cache │
│  🎨 字段映射定制      yaml 配置驱动,零代码改动     │
└──────────────────────────────────────────────────────┘
```

### 📤 正向 sync(OB → 飞书)

```bash
python3 sync.py "journals/2026-05-19.md" --only-completed --apply
```

扫描 markdown task 行 `- [x] ...`,自动映射到飞书字段:

- `[x]/[ ]/[/]/[-]` → 执行状态(Done/Todo/Doing/Block)
- `✅ YYYY-MM-DD` → 完成时间(datetime)
- `📎 [[xxx.md]]` 或 callout 块 → 交付物字段
- 优先级 `🔺/⏫/🔼/🔽` → 价值优先级(可选)
- 完成日 → ISO 周/月 enum(执行迭代周/月)

### 🔄 反向 pull(飞书 → OB)

```bash
python3 sync.py --pull --apply
```

扫描飞书侧"是否今日"标记的 task,生成对应 OB task 行,自动判断:

- task 已在 vault 历史日志(全 vault grep 标题模糊匹配)→ 提示"已存在"
- task 不在历史 → 写入当日 journal 「🎯 今日计划」/「🐿️ 今日非计划」段

### 🔗 短链自动反查 + cache

新建 task 时用户可能粘的是飞书后台「复制记录链接」拿到的**短链**(`feishu.cn/record/<27 位>`):

```markdown
- [x] 【布丁】调研直播功能 ✅ 2026-05-19 🆔 abc123
```

sync.py 会:
1. 按标题反查飞书表(lazy cache,一次 sync 仅 1 次 cli)
2. 拿到 `rec_id` → 在 task 行末尾注入 `<!-- rec=recXXX -->` 注释 cache
3. 下次 sync:O(1) 读注释,无 cli 调用

**用户体验**:从飞书后台复制短链 → 贴到 OB → sync 自动接管,**零手动 manage 链接格式**。

### 🎨 字段映射定制(yaml 配置驱动)

```yaml
# config.yaml(脱敏版见 config.example.yaml)
field_map:
  status:
    field_name: 执行状态
    field_type: multi_select
    map:
      x: Done
      blank: Todo
      "/": Doing
      "-": Block
  completed_time:
    field_name: 完成时间
    field_type: datetime
  delivery:
    field_name: 交付
    field_type: text
    extract:
      inline_emoji: 📎
      callout_types: [note, info]
      backlink_field: delivery_for
```

加新字段 / 改字段名 → 改 yaml,零代码改动。

---

## 🚀 5 分钟上手

```bash
# 1. 克隆仓库
git clone https://github.com/<YOUR-USER>/feishu-ob-sync.git
cd feishu-ob-sync

# 2. 装 feishu-cli(详见 INSTALL.md)
brew install feishu-cli   # macOS;Linux 用 go install

# 3. OAuth 登录飞书
feishu-cli auth login --scope "base:record:retrieve base:record:update base:record:create"

# 4. cp 配置模板 + 填 7 个用户机密
cp config.example.yaml config.yaml
# 用编辑器打开 config.yaml,把 <your-xxx> 占位符替换成你的真值

# 5. 跑一次 dry-run 看看(无副作用)
python3 sync.py "path/to/your/journal-today.md"
```

详细 9 步安装指引 → **[INSTALL.md](./INSTALL.md)** (新手 30 分钟完成第一次 sync)

---

## 📚 完整文档

| 文档 | 适合 | 阅读时间 |
|------|------|---------|
| [INSTALL.md](./INSTALL.md) | 第一次安装的人 | 30 分钟实操 |
| [docs/tutorial/01-basic-push-sync.md](./docs/tutorial/01-basic-push-sync.md) | 想理解正向 sync 流程 | 10 分钟 |
| [docs/tutorial/02-short-link-auto-lookup.md](./docs/tutorial/02-short-link-auto-lookup.md) | 想理解短链反查 + cache 机制 | 10 分钟 |
| [docs/tutorial/03-reverse-pull.md](./docs/tutorial/03-reverse-pull.md) | 想用反向 pull | 10 分钟 |
| [docs/tutorial/04-field-mapping-customization.md](./docs/tutorial/04-field-mapping-customization.md) | 想定制字段映射 | 10 分钟 |
| [docs/skill-claude-code.md](./docs/skill-claude-code.md) | Claude Code 用户(skill 集成) | 5 分钟 |
| [docs/design/](./docs/design/) | 想深入理解架构 / 已知坑 | 深度阅读 |

---

## ⚠️ 已知限制

| 限制 | 影响 | 缓解 |
|------|------|------|
| 飞书表 > 10000 条时拉全表慢(用于标题查重) | 50 页 × ~2 秒/页 ≈ 100 秒 | Lazy cache,一次 sync 仅 1 次拉全表 |
| 短链 27 位 token 不能从 record_id 反推 | 程序化生成短链不可行 | 改用 base 长链(等同体验,完全程序化) |
| OAuth scope 需手动配置 | 首次跑必须 `auth login` | INSTALL.md 详细指引 |
| 字段名拼写错误会创建后台孤立选项 | 多选/单选字段会产生重复 enum | dry-run 必看,apply 前检查 |
| Tasks 插件 emoji metadata 顺序敏感 | 多字段排序 `sort by priority` 必须在 `sort by created` 之前 | 模板已固化,见已知坑 6 |
| 反向 pull 模糊匹配可能假阳性 | 前缀相似的不同 task 被错误升级 | dry-run 必审,apply 时 `--exclude-record <rec_id>` 跳过 |

完整 11 条已知坑 → [docs/design/known-gotchas.md](./docs/design/known-gotchas.md)

---

## 🤝 贡献 / 反馈

- 🐛 **Bug 报告**:GitHub Issue,附上 sync.py 命令行参数 + dry-run 输出
- 💡 **功能建议**:GitHub Issue,标 `enhancement` label
- 🔧 **PR 欢迎**:fork → branch → 测试通过 → PR(描述里说为什么 + 怎么测的)
- 📚 **教学反馈**:跟做 INSTALL.md 卡在哪一步告诉我,我会改文档

---

## 📄 License

[MIT](./LICENSE) — 你可以自由 fork / 改 / 商用,只要保留 LICENSE 文件即可。

---

## 🙏 致谢

- **Claude Code (Anthropic)** — 整个工具是用 Claude Code 协同开发的,从 brainstorm → spec → plan → 实施 → 自评 → 抽取开源的完整 cycle
- **inject_url_into_line bug 修复** — 2026-05-19 由专门的 Claude Code 会话(短链接修复窗口)发现并修复,作为本仓库的核心改进
- **base URL 全自动方案** — 2026-05-19 同会话发现 wiki node API 的 `obj_token` 即 `base_token`,实现完全程序化稳定 URL
- 致敬所有 Obsidian + 飞书用户的工程化探索精神

---

## 📊 项目状态

| 阶段 | 状态 |
|------|------|
| MVP | ✅ 上线(2026-05-17) |
| Phase 2.1(执行迭代周/月) | ✅ 上线(2026-05-18) |
| Phase 2.2(反向 pull) | ✅ 上线(2026-05-18) |
| Phase 2.3(短链自动反查) | ✅ 上线(2026-05-18) |
| base URL 全自动 + inject bug 修复 | ✅ 上线(2026-05-19) |
| **开源仓库抽取** | ✅ 上线(2026-05-19) |

---

**仓库**:[feishu-ob-sync](https://github.com/) · **作者**:teacherai · **基于**:Claude Code · Obsidian · 飞书多维表
