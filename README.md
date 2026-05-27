# feishukanban-ob-sync

> 📋 **Obsidian ↔ 飞书项目管理多维表 全闭环同步工具**。让你既享受 Obsidian 的 ADHD 友好「子弹笔记式任务流」,又拥有飞书的「项目看板可视化」,**两端永远一致**。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-v0.3.3-blue.svg)](CHANGELOG.md)

---

## 🚀 v0.3.3 上线 — 强制北京时区(双层 defense)(2026-05-27)

修两层时区源头,解决 Mac 系统是北京时间但 shell `TZ=PDT` 导致 sync.py 的 `datetime.now()` 算成"昨天"、task `today_history` 进错日期的 bug:

- **userscript 层(先行)**:3 个 userscript `child_process.exec` 时在 `execEnv` 显式注入 `TZ: "Asia/Shanghai"`,sync.py 子进程一启动就在北京时区。
- **sync.py 层(防御)**:3 处裸 `datetime.now()` 改为 `datetime.now(timezone(timedelta(hours=8)))`,即使命令行直接跑也是北京日期。

实证:`TZ=America/Los_Angeles python3 -c "from datetime import datetime; print(datetime.now())"` 算出 `2026-05-26 23:51`(错);显式 UTC+8 算出 `2026-05-27 14:51`(对)。100% 向后兼容。详见 [CHANGELOG.md](CHANGELOG.md#v033---2026-05-27)。

## 🚀 v0.3.2 上线 — symlink 路径自适应 + install.sh `--scripts-dir` flag(2026-05-26)

- **userscript 路径自适应**:4 个 UserScript 改用 `path.resolve(path.dirname(__filename), '..', 'sync.py')` 推导 sync.py 路径,**不管 install.sh 装在 vault 哪里都能找到**——以后路径再迁移,userscript 不用动一行。
- **install.sh 加 `--scripts-dir <vault-rel-path>` flag**:开源用户用默认 `scripts/feishukanban-ob-sync/`;高级用户可装到 vault 任意位置(如 `01 Project/.../工具/`),保 vault 文件树整洁。QuickAdd choices snippet 的 path 字段自动跟随。
- **顺手修 sync.py `VAULT_ROOT` bug**:旧版 `SCRIPT_DIR.parents[4]` 假设固定 vault 子目录深度,因 sync.py 是 symlink 而 `.resolve()` 跳到仓库真实位置,parents[4] 算到了 `/Users/<u>/`。改成 `Path.cwd()` 初始 + `main()` 处理 `--vault` 后刷新。修复 C 路径 backlinks 潜在错位。

100% 向后兼容。详见 [CHANGELOG.md](CHANGELOG.md#v032---2026-05-26)。

## 🚀 v0.3.1 上线 — `--vault` 参数 + 跨日 dateContext + 完成段链 + today_history 清理(2026-05-26)

四块 patch 合并:
- **`--vault <path>` 参数**:命令开头是 `python3` 而非 `cd ... && python3 ...`,**Claude Code allowlist 前缀匹配可命中**,不再每次弹 permission 窗。4 个 UserScript 同步更新,新增项目级 `.claude/settings.json`。
- **`inject_completion_link`**:CREATE 时把「✅ 完成标记」段裸 checkbox 自动改为带飞书 record URL 的 markdown link,dataview 渲染可点击直达飞书。
- **`pull-today` today_history 残留清理**:取消飞书今日时清理 OB `today_history`,journal 不再误渲染。
- **`快记任务` 跨日 dateContext**:在 `journals/YYYY-MM-DD.md` 触发时用 journal 日期(而非北京时间)作为新 task 的文件名前缀 / `today_history` / `日志`,解决 Mac 非北京时区跨日 task "消失"问题。

100% 向后兼容。详见 [CHANGELOG.md](CHANGELOG.md#v031---2026-05-26)。

## 🚀 v0.3.0 上线 — 历史保真:`today_history` 事件流(2026-05-26)

dataview 是实时投影,无法做"时间穿越"。v0.2.0 用 `today: true/false` 单字段管理"今日",取消后历史 journal **消失**。v0.3.0 加 `today_history` append-only list 字段,**5/26 journal 永远显示曾经在 5/26 聚焦的 task**。详见 [CHANGELOG.md](CHANGELOG.md#v030---2026-05-26)。

## 🚀 v0.2.0 上线 — task md 化架构 + 完整工作流

**从 inline 子弹笔记升级为 "first-class entity"**:每个 task = 独立 md 文件 + frontmatter 与飞书 22 字段 1:1 对齐,4 个 Cmd+P 命令覆盖创建 / 拉今日 / 完成 / 自动统计的**完整工作流**。

📖 完整变更见 [CHANGELOG.md](CHANGELOG.md) / 系统架构见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## ✨ 痛点解决

| 痛点 | 现状 | 这个工具 |
|------|------|---------|
| OB 勾 `[x]` 完成 → 飞书侧字段不会自动联动 | 手动到飞书后台填字段 | **Cmd+P「✅ 完成当前 task」一键 sync** |
| OB 写新 task → 没飞书 record_id → 无法挂看板 | 手动复制粘贴 | **Cmd+P「📝 快记任务」5 秒自动 CREATE** |
| 飞书 app 挑了今日 todo → OB 端看不到 | 手动跨平台抄录 | **Cmd+P「📥 拉今日 todo」一键同步** |
| 没事先计划直接干活 → 日终复盘要回忆做了什么 | 翻 git log + 文件 | **Claudian 对话"统计今天工作"自动归纳 + 写日志 + 飞书** |
| 跨日浏览找未完成 task | 翻 30 份 journal | **`_task.base` 6 视图全景** |
| ADHD 看板被未完成 task 充斥分心 | 每天看堆积如山 | **`today=true` 字段过滤,today journal 只见今天聚焦的** |

---

## 🎯 4 个 Cmd+P 命令 = 完整工作流

```
☀️ 早上 7:00(2 分钟仪式):
   ① 飞书 app 周看板 → 长按 task 勾「是否今日」=true(挑 3-5 条)
   ② Obsidian Cmd+P 「📥 拉今日 todo」
   → OB today journal「🎯 今日计划」段自动渲染 3-5 条 checkbox ✅

🏃 白天工作:
   ① 想新加临时 task → Cmd+P「📝 快记任务」
   → 弹优先级 → 输标题 → 5 秒后 task md + 飞书 record 全部建好 ✅

   ② 做完一条 → 打开 task md → Cmd+P「✅ 完成当前 task」
   → inline ☑ + frontmatter done + 飞书 UPDATE Done(一键全闭环)✅

🌙 晚上 22:00(3 分钟):
   ③ 跟 Claudian 说"统计今天工作"
   → 扫 git + 文件改动 → LLM 归纳 → 写日志「📊 今日自动统计」+ batch CREATE 飞书 Done record ✅
```

---

## 📦 核心组件

```
┌──────────────────────────────────────────────────────┐
│  🎯 Cmd+P 入口(4 个 QuickAdd UserScripts)          │
│     📝 快记任务 / 📥 拉今日 todo / ✅ 完成 task /     │
│     🎯 同步今日 task 到飞书                          │
└─────────────────────┬────────────────────────────────┘
                      ↓
┌─────────────────────┴────────────────────────────────┐
│  🐍 Python 桥接层(sync.py + auto_collect_today.py)  │
│     CREATE / UPDATE / pull-today / batch CREATE     │
└─────────────────────┬────────────────────────────────┘
                      ↓
┌─────────────────────┴────────────────────────────────┐
│  ☁️ 飞书项目管理多维表(22 字段)                      │
│     周看板 / 今日 todo / 已完成 / ADHD 待抢救...      │
└──────────────────────────────────────────────────────┘
                      ↑
┌─────────────────────┴────────────────────────────────┐
│  📝 Obsidian Vault                                   │
│  ├─ 04 Inbox/task/YYYY-MM-DD-<标题>.md (task md)    │
│  ├─ _task.base(6 视图全景)                        │
│  └─ journals/YYYY-MM-DD.md (dataview TASK 渲染)     │
└──────────────────────────────────────────────────────┘
```

---

## 🚀 快速开始(5 分钟)

### Step 1: clone + install

```bash
git clone https://github.com/wukongai/feishukanban-ob-sync.git
cd feishukanban-ob-sync
./install.sh                                # dry-run 看会改什么
./install.sh --apply                        # 真执行
```

→ 自动:
- symlink scripts 到你的 vault
- symlink 4 个 QuickAdd UserScripts
- 复制 task 模板 + base 视图 + rules 文档(如不存在)
- 输出 QuickAdd choices JSON 让你手动粘贴

### Step 2: 创建飞书表 + 22 字段

参考 [docs/feishu-schema.md](docs/feishu-schema.md) 的 feishu-cli 一键命令,或去飞书后台手动建。

### Step 3: 配置

```bash
cp config.example.yaml ~/Documents/Obsidian/scripts/feishukanban-ob-sync/config.yaml
# 编辑 config.yaml,填 base_token / table_id / tenant_domain
```

### Step 4: 重启 Obsidian + 测试

`Cmd+Q` 重启 Obsidian → `Cmd+P` 搜「📝 快记任务」→ 弹优先级 → 输标题 → 看 5 秒后飞书有没有新 record。

---

## 📚 文档

| 文档 | 用途 |
|------|------|
| [INSTALL.md](INSTALL.md) | 详细安装步骤 + 排障 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系统架构 + 数据流图 + 8 条原则自评 |
| [docs/feishu-schema.md](docs/feishu-schema.md) | 飞书表 22 字段定义 + feishu-cli 一键创建命令 |
| [docs/tutorial/05-task-md-workflow.md](docs/tutorial/05-task-md-workflow.md) | v0.2 主流程教程 |
| [docs/tutorial/01-basic-push-sync.md](docs/tutorial/01-basic-push-sync.md) | 基础正向同步(v0.1 legacy) |
| [docs/tutorial/02-short-link-auto-lookup.md](docs/tutorial/02-short-link-auto-lookup.md) | 短链自动反查 |
| [docs/tutorial/03-reverse-pull.md](docs/tutorial/03-reverse-pull.md) | 反向同步(v0.1 老 `--pull`,v0.2 推荐 `--pull-today`) |
| [docs/tutorial/04-field-mapping-customization.md](docs/tutorial/04-field-mapping-customization.md) | 字段映射定制 |
| [docs/skill-claude-code.md](docs/skill-claude-code.md) | Claude Code 用户专用入门 |
| [CHANGELOG.md](CHANGELOG.md) | 版本变更日志 |

---

## 🎓 适合的人

- **个人项目管理 / ADHD** — 4 个 Cmd+P 命令降低操作成本到极限,看板视图全景管多项目
- **Obsidian + 飞书重度用户** — 解决两端数据孤岛
- **Claude Code 用户** — Claudian 主导的场景 ③ 自动统计是 LLM × workflow 的好范例
- **想做"Obsidian + AI"专题内容的博主 / 训练营讲师** — v0.2 完整工作流是高质量演示素材

---

## ⚙️ 技术栈

- **Python 3.8+**(`sync.py` ~2300 行,无外部依赖,只用标准库 + 系统 `feishu-cli`)
- **feishu-cli**(飞书官方 cli,负责 OAuth + API 调用)
- **Obsidian + QuickAdd + Templater + Tasks + Dataview** 插件
- **shell**(`install.sh` 部署脚本)

---

## 🛣 Roadmap

### v0.2.0(2026-05-26 当前)
- ✅ task md 化架构
- ✅ 4 个 Cmd+P 命令(创建 / 拉今日 / 完成 / 同步)
- ✅ 自动统计今日工作场景 ③
- ✅ install.sh 一键部署

### v0.3(规划)
- [ ] 反向 status 同步(飞书改 Done → OB 跟着)
- [ ] 多 profile config(支持多张飞书表 / 多 vault)
- [ ] Cmd+P「↩️ 撤销 task 完成」+「💤 task 冬眠」+「🔺 改优先级」补全
- [ ] Demo GIF + 视频教程

### v0.4(社区驱动)
- [ ] 支持其他笔记软件(Logseq / Notion local)
- [ ] 支持其他云表(Notion DB / Airtable)
- [ ] 自动统计场景 ③ 加 Time Block Pomodoro 数据源

---

## 📄 License

MIT — 详见 [LICENSE](LICENSE)

---

## 🙏 致谢

- [feishu-cli](https://github.com/feishu-cli/feishu-cli) — 提供飞书 API 桥接
- Obsidian 社区插件:[QuickAdd](https://github.com/chhoumann/quickadd) / [Templater](https://github.com/SilentVoid13/Templater) / [Tasks](https://github.com/obsidian-tasks-group/obsidian-tasks) / [Dataview](https://github.com/blacksmithgu/obsidian-dataview)
- **Claude Code(Anthropic)** — 整个工具的 AI 协同开发主力

---

## 🐙 仓库

- GitHub: [`wukongai/feishukanban-ob-sync`](https://github.com/wukongai/feishukanban-ob-sync)
- Gitee 镜像: [`teacherai/feishukanban-ob-sync`](https://gitee.com/teacherai/feishukanban-ob-sync)
- Issues / PRs welcome 🎉
