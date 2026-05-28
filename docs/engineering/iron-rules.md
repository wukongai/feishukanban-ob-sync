---
title: 6 条铁律
type: engineering
status: active
created: 2026-05-28
updated: 2026-05-28
tags: [规范, 铁律, 红线]
related: ["[[README]]", "[[git-workflow]]", "[[../../.claude/CLAUDE.md]]"]
---

# 6 条铁律(必须遵守)

> 来源:`.claude/CLAUDE.md` 项目入口。本文是规范化展开版,跨会话维护方便引用。

---

## 铁律 #1:任何修改 push 远端前必须给用户 review

- ❌ 禁止 `git push` 时跳过用户确认
- ✅ commit 完成 → 给用户看 `git log -1 --stat` → 用户说 "push" 才推
- **唯一例外**:用户在同一对话明确说"做完直接 push" / "全自动 push" / "完成自动 push 后回报" 这类授权
- **会话外不延续**:这类授权只对**当前对话**有效,新会话默认回到 review 流程

**为什么这条最严**:push 是不可逆操作,推上去后再 revert 会污染 commit 历史 / 触发别人 pull;开源项目更糟,会被第三方 fork。

---

## 铁律 #2:不要污染 vault(用户私域数据)

- ❌ 禁止 sync.py 写 vault 内不该写的位置(只能写 task md frontmatter / today journal「📊 今日自动统计」section)
- ❌ 禁止 install.sh 默认覆盖已存在文件(必须 `--force` flag)
- ❌ 禁止把含 user 私域 base_token 的 config.yaml 上 git(`.gitignore` 屏蔽)
- ❌ 禁止仓库 CC 直接改 OB vault — 跨工程协作走 [`../handoff/`](../handoff/) 流程

**为什么**:用户 vault 是私域数据,有完整的笔记体系 + 长期价值。代码 bug 改坏 vault 是不可逆的。

---

## 铁律 #3:跨平台兼容性(macOS 主 / Linux 兼容 / Windows WSL2)

- install.sh 写 bash 兼容语法,不依赖 macOS 专属
  - ⚠️ 当前实际:v0.2.x 用了 macOS `sed -i ''`,Linux 用户需 `sed -i`(P2 follow-up:抽 helper)
- sync.py 用 Python 标准库,无外部依赖(easy install)
- 路径处理用 `pathlib` 而非 hardcode `/`

**为什么**:开源项目目标用户多样,不能只为 maintainer 自己的 mac 优化。

---

## 铁律 #4:版本号语义(SemVer)

- `v0.X.Y`:0.x = 早期开发,API 可能 breaking
- `v0.X.0` = MINOR 新功能 / 架构升级 / breaking changes(v0.x 期允许)
- `v0.X.Y` = PATCH bug 修复 / 小优化(向后兼容)
- 每次 commit 决定要不要 bump version
- bump = 改 README badge + 顶部 vX.Y.Z 上线 section + tag + CHANGELOG entry + push

详见 [`../VERSION.md`](../VERSION.md) §3 触发条件 + §4 操作清单。

---

## 铁律 #5:文档同步更新

代码改完后必须同步改对应文档,不可只 commit 代码不改文档。

| 改了什么 | 必须同步改 |
|---|---|
| `sync.py` 行为 | `docs/ARCHITECTURE.md`(如涉及架构 / schema) |
| 飞书字段 | `docs/feishu-schema.md` + `config.example.yaml` |
| Cmd+P 命令 | `README.md` + `INSTALL.md` + tutorial/05 |
| 任何 user-facing 改动 | `CHANGELOG.md` 新 entry |
| 版本 bump | `docs/releases/vX.Y.Z.md`(用户向)+ `docs/VERSION.md` §7 索引 |

**禁止只改代码不改文档** — 开源项目最大灾难是「代码跑得动但文档落后,用户照文档操作发现不 work」。

---

## 铁律 #6:测试用真实 vault

- bug 修复 / 新功能必须在**真实 OB vault** 上跑一次(不只在 mock 数据)
- 用户 vault 路径:`/Users/aim5/Documents/OB/`
- 测试 task 创建 → 看飞书有没有 record → 看 OB frontmatter 有没有回写

**为什么**:mock 数据测过≠真实工作。真实 vault 有 14 万+ 文件,有 dataview / templater / Tasks 插件相互作用,只有真实环境才能发现交互 bug。

---

## 🔗 相关

- 跨工程协作约束 → [`../handoff/`](../handoff/) 流程文档
- git 操作具体规范 → [`git-workflow.md`](git-workflow.md)
- 架构原则 → [`8-principles.md`](8-principles.md)
- 开发任务 SOP → [`dev-sop.md`](dev-sop.md)
