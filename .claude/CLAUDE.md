# feishukanban-ob-sync 项目指令

> 用户在独立 VS Code 窗口打开此项目目录(`~/Documents/CodingProject/feishukanban-ob-sync/`)启动 Claude Code 时,这份文档是你的入口。

---

## 📋 项目身份

**这是什么**:开源工具,Obsidian ↔ 飞书项目管理多维表双向同步,让用户在 OB 和飞书两端做同一份 task 管理。

**当前版本**:v0.2.2(2026-05-26)— task md 化架构 + 4 个 Cmd+P 完整工作流 + 一键 install.sh + 项目归类

**项目核心定位**:
- 不是 SaaS,不是订阅服务
- 开源工具,MIT 协议
- 服务对象 = Obsidian + 飞书双重用户(目标群:个人项目管理 / ADHD / 知识工作者)

**远端仓库**(双推):
- GitHub `wukongai/feishukanban-ob-sync`
- Gitee `teacherai/feishukanban-ob-sync`

---

## 🏗 系统架构(快速复习)

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
│  ☁️ 飞书项目管理多维表(22+ 字段)                    │
│     周看板 / 今日 todo / 已完成 / 按项目分组...      │
└──────────────────────────────────────────────────────┘
                      ↑
┌─────────────────────┴────────────────────────────────┐
│  📝 Obsidian Vault(用户私域)                        │
│  ├─ 04 Inbox/task/YYYY-MM-DD-<标题>.md (task md)    │
│  ├─ _task.base(6 视图全景)                        │
│  └─ journals/YYYY-MM-DD.md (dataview TASK 渲染)     │
└──────────────────────────────────────────────────────┘
```

完整架构见 `docs/ARCHITECTURE.md`。

---

## 📁 目录结构

```
feishukanban-ob-sync/
├─ sync.py                       # 主代码,~2300 行
├─ scripts/auto_collect_today.py # 场景 ③ 数据采集
├─ obsidian-assets/              # 给用户 vault 安装的资产
│  ├─ userscripts/(4 个 QuickAdd UserScripts)
│  ├─ templates/task-template.md
│  ├─ base/_task.base
│  └─ rules/feishu-project-sync.md
├─ install.sh                    # 一键部署到 vault
├─ docs/
│  ├─ ARCHITECTURE.md
│  ├─ feishu-schema.md           # 22+ 字段定义
│  └─ tutorial/01-05
├─ README.md / INSTALL.md / CHANGELOG.md / LICENSE
├─ config.example.yaml           # 配置模板
├─ config.yaml                   # 用户私域(.gitignore 屏蔽)
└─ .claude/                      # CC 配置(本文件 + rules/)
```

---

## 🔴 开发铁律(必须遵守)

### 铁律 #1:任何修改 push 远端前必须给用户 review

- ❌ 禁止 `git push` 时跳过用户确认
- ✅ commit 完成 → 给用户看 `git log -1 --stat` → 用户说"push" 才推
- 唯一例外:用户在同一对话明确说"做完直接 push"

### 铁律 #2:不要污染 vault(用户私域数据)

- ❌ 禁止 sync.py 写 vault 内不该写的位置(只能写 task md frontmatter / today journal「📊 今日自动统计」section)
- ❌ 禁止 install.sh 默认覆盖已存在文件(必须 `--force` flag)
- ❌ 禁止把含 user 私域 base_token 的 config.yaml 上 git(.gitignore 屏蔽)

### 铁律 #3:跨平台兼容性(macOS 主 / Linux 兼容 / Windows WSL2)

- install.sh 写 bash 兼容语法,不依赖 macOS 专属(避免 BSD `sed -i ''` 之类)
  - 实际 v0.2.x 用了 macOS `sed -i ''`,Linux 用户需 `sed -i`(P2 follow-up:抽出 helper)
- sync.py 用 Python 标准库,无外部依赖(easy install)
- 路径处理用 `pathlib` 而非 hard-code `/`

### 铁律 #4:版本号语义(SemVer)

- `v0.X.Y`:0.x = 早期开发,API 可能 breaking
- `v0.X.0` = minor 新功能 / 架构升级 / breaking changes
- `v0.X.Y` = patch bug 修复 / 小优化(向后兼容)
- 每次 commit 决定要不要 bump version
- bump = 改 README 顶部 badge + tag + CHANGELOG.md 加 section + push

### 铁律 #5:文档同步更新

- 改 sync.py 行为 → 改 docs/ARCHITECTURE.md
- 加飞书字段 → 改 docs/feishu-schema.md + config.example.yaml
- 加 Cmd+P 命令 → 改 README + INSTALL + tutorial/05
- 任何 user-facing 改动 → 加 CHANGELOG.md
- ❌ 禁止只改代码不改文档(开源项目最大灾难)

### 铁律 #6:测试用真实 vault

- bug 修复 / 新功能必须在**真实 OB vault** 上跑一次(不只在 mock 数据)
- 用户 vault 路径:`/Users/aim5/Documents/OB/`
- 测试 task 创建 → 看飞书有没有 record → 看 OB frontmatter 有没有回写

---

## 🛠 常见开发任务

### 任务 1:加新字段映射(OB ↔ 飞书)

1. 飞书后台加字段(或用 cli `feishu-cli bitable field create`)
2. 看新字段的 field_id + type
3. config.example.yaml + config.yaml 加映射(`task_md_fields.<key>.field_name`)
4. sync.py `parse_task_md` 抽 frontmatter 字段
5. 如需特殊处理(如 wikilink 抽名字 / multi-select list 包裹)→ `build_fields_payload` 加 case
6. task 模板 frontmatter 加字段(`obsidian-assets/templates/task-template.md` + vault 的 `task 模版.md`)
7. UserScript(如 quickadd-快记任务)是否要互动输入 → 加 `quickAddApi.suggester/inputPrompt`
8. 真实 vault 测一次 dry-run → apply
9. 更新 docs/feishu-schema.md / ARCHITECTURE.md / CHANGELOG.md
10. commit + tag(patch / minor 看大小)+ push

### 任务 2:加新 Cmd+P 命令

1. 在 `obsidian-assets/userscripts/` 加新 `quickadd-XXX.js`
2. 沿用现有模式(`exec sync.py` / `read frontmatter` / `Notice 报告`)
3. install.sh Step 6 输出的 `.quickadd-choices.json` 加新 choice
4. 真实 vault 测(让用户在 OB 端手加 choice 到 QuickAdd data.json,Cmd+Q 重启,Cmd+P 触发)
5. 更新 README + INSTALL + tutorial/05 + CHANGELOG
6. commit + tag + push

### 任务 3:修 bug

1. 用户报 bug → 复现 → 定位
2. 修 sync.py / userscript / 等
3. 真实 vault 测验证
4. patch bump(v0.2.X+1)
5. 更新 CHANGELOG「修复」section
6. commit + tag + push

---

## 🤝 跨工程协作(铁律 #2 OB vault 配合)

### 何时需要 OB CC 配合

- sync.py 改了 frontmatter 字段名 → 用户老 task md 需 migration
- 新 UserScript 要测,但用户 vault 的 QuickAdd choices 是旧版 → 需要改 vault data.json
- 改 install.sh 后,需要在用户 vault 跑 `--apply --force` 重新安装

### Handoff 流程(走铁律 #2 标准)

**独立 CC 完成代码后**,**不要直接改用户 vault**,改用:
1. 在独立仓库 `docs/handoff/OB对接/` 写 handoff 文档(描述:做了什么 / OB 端要做什么 / 测试步骤)
2. 给用户 1 句话总结 + handoff 文档链接
3. 用户切到 OB CC,read handoff 文档,执行 vault 端配套
4. OB CC 完成后写"反向回执"

详细 SOP 见 OB vault `.claude/rules/cross-project.md`(类似流程)。

---

## 🎯 用户开发场景(独立 CC 实例的"我"该如何工作)

### 场景 A:你打开仓库目录启动 CC,问"如何加新字段"

→ 走「常见开发任务 1:加新字段映射」流程

### 场景 B:你看 issues 想修 bug

→ 复现 → 修 → patch 版本 → push

### 场景 C:你想加新 Cmd+P 命令

→ 走「常见开发任务 2:加新 Cmd+P 命令」

### 场景 D:你想做大改动(如反向 status 同步 / 多 profile config)

→ 这是 minor bump(v0.3.0)
→ 先看 README.md 的「Roadmap」section,确认这是用户计划内的
→ 在 docs/ 加 spec 文档(可选)
→ 实施 + 测 + 文档同步 + push

### 场景 E:你 dogfood 时发现自己的 bug

→ 直接修 + patch bump,因为你既是 dev 又是 user

---

## 📌 v0.2.x 历史(供今后参考)

| 版本 | 上线日期 | 重大变化 |
|------|---------|--------|
| v0.1.0 | 2026-05-19 | 初版开源,journal-inline 模式 |
| v0.2.0 | 2026-05-26 凌晨 | **task md 化大架构升级** + 4 个 Cmd+P + install.sh + obsidian-assets/ + 完整文档 |
| v0.2.1 | 2026-05-26 凌晨 | patch:UserScripts sync.py 路径硬编码修复(install.sh 新路径) |
| v0.2.2 | 2026-05-26 凌晨 | feat:创建 task 时弹大项目选择,自动归类到飞书「项目」字段 |

v0.2.x 是凌晨 4 小时一次性"产品化重构"的产物(OB CC 跨边界做的,一次性例外,详见 OB vault `.claude/rules/cross-project.md`)。**v0.3+ 起改回独立 CC 开发**。

---

## 🌟 关键文档(开发参考)

- `README.md` — 用户视角主入口
- `INSTALL.md` — 详细安装步骤
- `CHANGELOG.md` — 版本变更
- `docs/ARCHITECTURE.md` — 系统架构 + 8 条原则
- `docs/feishu-schema.md` — 飞书表字段定义
- `docs/tutorial/05-task-md-workflow.md` — v0.2 主流程教程
- `config.example.yaml` — 字段映射定义

---

## 🔗 用户的 OB vault 路径(开发测试时用)

- vault root:`/Users/aim5/Documents/OB/`
- vault 内 sync.py(symlink → 仓库):`01 Project/00 进行中/06 小工具开发/feishukanban-ob-sync/sync.py`
- vault 内 auto_collect_today.py(symlink → 仓库):同上目录
- vault 内 config.yaml(symlink → 仓库 config.yaml):同上目录
- vault 内 4 个 userscripts(symlink → 仓库 obsidian-assets/userscripts/):`01 Project/00 进行中/06 小工具开发/feishukanban-ob-sync/userscripts/`
- vault 内 QuickAdd choices:`.obsidian/plugins/quickadd/data.json`(4 个 choices 的 `path` 字段指向上方 userscripts 路径)
- vault 内 task md 目录:`04 Inbox/task/`
- vault 内 journal 模板:`03 Resources/素材库/模版/日志模版 5.0 1.md`

> ⚠️ **路径历史**:v0.1.x 临时放在 `06 小工具开发/CC命令/飞书项目同步/`;v0.2.x 用 `_OB工程/scripts/` 然后 `scripts/feishukanban-ob-sync/`(vault 根多顶层目录,用户嫌乱);v0.3.2 起 userscripts 用 `__filename` 推 sync.py 路径,install.sh 加 `--scripts-dir` flag,装哪都行 → 2026-05-27 用户拍板"外部 symlink 统一放 06 小工具开发 下,跟 macmini-nas / OB 插件平级",落地至上述位置。改 vault 路径建议:用户自己 `install.sh --scripts-dir <新路径> --apply --force` 即可,代码无需任何修改。

---

## ✅ 启动 checklist(用户启动独立 CC 时,你做这件事)

1. 读这份 CLAUDE.md(已读)
2. `git log -5 --oneline` 看最近 commits
3. `git status` 看是否有未 commit 改动
4. `cat CHANGELOG.md | head -30` 看最近版本变化
5. 问用户:"想做什么?加字段 / 修 bug / 加命令 / 大改动 / dogfood 反馈?"
6. 按对应「常见开发任务」流程执行
