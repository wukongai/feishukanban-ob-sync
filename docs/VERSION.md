---
title: 版本管理规范
type: engineering
status: active
created: 2026-05-28
updated: 2026-05-28
tags: [规范, 版本管理]
related: ["[[ROADMAP]]", "[[../CHANGELOG]]", "[[engineering/git-workflow]]"]
---

# 版本管理规范

> 定义 `feishukanban-ob-sync` 的版本号分配规则、bump 触发条件、与 ROADMAP / CHANGELOG / handoff 的关系。

---

## 1. 版本号格式(SemVer)

`vMAJOR.MINOR.PATCH`,语义化版本。

| 段 | 触发条件 | 示例 |
|---|---|---|
| **MAJOR**(0→1, 1→2) | 不兼容的 API 改动 / 架构级重写 | `v0.x` → `v1.0`(MVP 期 → 正式版) |
| **MINOR**(0.X→0.Y) | 新功能 / 架构升级 / 含 breaking changes(v0.x 期允许) | `v0.2.0`(task md 化大架构升级) |
| **PATCH**(0.X.Y→0.X.Y+1) | bug fix / 小优化 / 100% 向后兼容 | `v0.3.3`(强制北京时区双层 defense) |

---

## 2. 当前阶段:v0.x 早期开发

- ✅ API 可能有 breaking changes(在 minor bump 时披露)
- ✅ 高频迭代节奏(2026-05-26 至 2026-05-28 共发 v0.2.0 → v0.3.7 共 9 个版本)
- ❌ 不保证长期 LTS 支持
- 目标 `v1.0.0`:核心 4 个 Cmd+P 命令稳定 + 反向 sync 完整 + 用户文档完备 + 跨平台兼容(macOS/Linux/WSL2 测过)

---

## 3. bump 触发条件(具体)

### 必须 PATCH bump

- 修一个 bug → `+1 PATCH`
- 优化一个现有逻辑(无新 API)→ `+1 PATCH`
- 文档同步性勘误 → 不 bump(可直接 commit `docs: ...`)

### 必须 MINOR bump

- 加一个新 frontmatter 字段(如 `today_source`)→ `+1 MINOR`
- 加一个新 Cmd+P 命令 → `+1 MINOR`
- 加一个新 sync.py CLI flag → `+1 MINOR`
- 反向 sync 范围扩展(如 v0.3.7 字段 diff sync)→ `+1 MINOR`
- 架构升级(如 task md 化 v0.2.0)→ `+1 MINOR`

### 双块 patch 合并允许

参考 v0.3.4 / v0.3.5 模式:同会话内做了 2 块独立改动 → 合并为 1 个 commit + 1 个版本号,CHANGELOG 用 `Part 1 / Part 2` 双段描述。

**触发条件**:
- 2 块改动都已实测通过
- CHANGELOG 顶部 "**N 块 patch 合并**" 显式说明
- commit message 标 `feat(vX.Y.Z): Part 1 主旨 + Part 2 主旨`

---

## 4. bump 操作清单(每次 bump 必做)

按顺序:

1. ☐ 改 `README.md` badge `version-vX.Y.Z-blue.svg`
2. ☐ 加 `README.md` 顶部 v0.X.Y 上线 section(1-2 段简介 + 详见 CHANGELOG link)
3. ☐ 改 `install.sh` banner `📦 feishukanban-ob-sync vX.Y.Z install`
4. ☐ 改 `install.sh` 完成消息 `feishukanban-ob-sync vX.Y.Z 部署完成`
5. ☐ 写 `CHANGELOG.md` 新 entry(顶部插入,模板见 §6)
6. ☐ 写 `docs/releases/vX.Y.Z.md` 用户向 release notes(轻量级)
7. ☐ 改 `docs/ARCHITECTURE.md`(如有 schema 新字段)
8. ☐ 文档同步检查(`docs/feishu-schema.md` / tutorial)
9. ☐ git commit + tag + 双推(详见 `engineering/git-workflow.md`)
10. ☐ 关闭对应 ROADMAP 条目(从「下一版本」移到「已发版」)

---

## 5. ROADMAP / CHANGELOG / handoff / releases 分工

| 文档 | 时间窗 | 受众 | 长度 |
|------|--------|------|------|
| **`docs/ROADMAP.md`** | 未来 1-2 版本 | 维护者 / 贡献者 | 短(只列条目 + 状态) |
| **`docs/releases/vX.Y.Z.md`** | 单一已发版 | 终端用户 | 轻量(影响用户的内容) |
| **`CHANGELOG.md`** | 全部已发版 | 维护者 + 用户 | 详尽(技术细节 + commit hash + 8 原则自评) |
| **`docs/logs/daily/`** | 单日开发会话 | 维护者(自己回顾) | 中等(决策记录 + token / 时长 + 教训) |
| **`docs/handoff/`** | 跨工程协作(OB ↔ 仓库) | 协作 CC | 详尽(spec + 接口契约 + 验收) |

---

## 6. CHANGELOG 单版本 entry 模板

```markdown
## [vX.Y.Z] - YYYY-MM-DD — 一句话主旨

> **背景**:用户痛点 / 触发事件
> **决策**:核心方向
> **影响**:用户感知 / 不变范围

### 🆕 / 🛠 / 🐛 / 🔗 章节(选用)

| 表格描述改动 |

### 📝 改动文件

- `sync.py`(具体改动点 + line 号)
- `config.example.yaml`
- ...

### ⚠️ 注意 / 用户侧需要做的事

- 必做 ① / 必做 ② / 可选

### ⚖️ 8 条原则自评(MINOR+ 必填)

| # | 原则 | 评分 ⭐ | 备注 |
|---|---|---|---|

### 🔮 下一步候选(可选)
```

---

## 7. 已发版历史(快速索引)

完整 changelog 见 [`CHANGELOG.md`](../CHANGELOG.md)。release notes 见 [`releases/`](releases/)。

| 版本 | 日期 | 主题 | release notes |
|---|---|---|---|
| v0.3.8 | 2026-05-28 | Cmd+P 项目小类三级分类 | [releases/v0.3.8.md](releases/v0.3.8.md)(待写) |
| v0.3.7 | 2026-05-28 | pull-today 反向字段 diff sync | [releases/v0.3.7.md](releases/v0.3.7.md) |
| v0.3.6 | 2026-05-28 | today_source 字段 | [releases/v0.3.6.md](releases/v0.3.6.md) |
| v0.3.5 | 2026-05-27 | status 7 态对齐 + Cmd+P 9 步 | [releases/v0.3.5.md](releases/v0.3.5.md) |
| v0.3.4 | 2026-05-27 | __filename + dataview 跨天 bug 修复 | [releases/v0.3.4.md](releases/v0.3.4.md) |
| v0.3.3 | 2026-05-27 | 强制北京时区双层 defense | [releases/v0.3.3.md](releases/v0.3.3.md) |
| v0.3.2 | 2026-05-26 | symlink 路径自适应 + `--scripts-dir` | [releases/v0.3.2.md](releases/v0.3.2.md) |
| v0.3.1 | 2026-05-26 | `--vault` 参数 + 4 块 patch | [releases/v0.3.1.md](releases/v0.3.1.md) |
| v0.3.0 | 2026-05-26 | today_history 事件流 | [releases/v0.3.0.md](releases/v0.3.0.md) |
| v0.2.0 | 2026-05-26 | task md 化大架构升级 | (未写) |
| v0.1.0 | 2026-05-19 | 初版开源 | (未写) |
