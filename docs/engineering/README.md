---
title: 工程规范索引
type: engineering
status: active
created: 2026-05-28
updated: 2026-05-28
tags: [规范, 索引]
related: ["[[../VERSION]]", "[[../ROADMAP]]", "[[../../.claude/CLAUDE.md]]"]
---

# 工程规范索引

> `feishukanban-ob-sync` 的工程规范单点入口。所有规范文档下沉到本目录,用 wikilink 关系网连接。

---

## 📚 规范文档清单

| 文档 | 主旨 | 强制度 |
|---|---|---|
| [`iron-rules.md`](iron-rules.md) | 6 条铁律(任何修改前必读) | 🔴 强制 |
| [`8-principles.md`](8-principles.md) | 8 条架构设计原则(每次架构改动前/后自评) | 🔴 强制 |
| [`git-workflow.md`](git-workflow.md) | git commit / tag / 双推规范 | 🔴 强制 |
| [`bash-conventions.md`](bash-conventions.md) | Bash 命令写法约定(减少 permission 噪音) | 🟡 建议 |
| [`dev-sop.md`](dev-sop.md) | 4 个常见开发任务 SOP(加字段 / 加命令 / 修 bug / 大改动) | 🟡 建议 |

---

## 🎯 怎么用这些规范

### 新会话启动时

1. 读 [`../../.claude/CLAUDE.md`](../../.claude/CLAUDE.md) 项目入口
2. 读 [`iron-rules.md`](iron-rules.md) 确认底线(6 条)
3. 看 [`../ROADMAP.md`](../ROADMAP.md) 知道当前在做什么版本
4. 看 [`../../CHANGELOG.md`](../../CHANGELOG.md) 顶部确认最近变化

### 做架构改动时

1. **改前**:对照 [`8-principles.md`](8-principles.md) 做「反向打分」
2. **改后**:再对一遍写「自评报告」附在交付里
3. **任何违反** → 显式记录「本次违反 X 原则,原因 ____,未来修复路径 ____」

### 准备 commit 时

1. 对照 [`git-workflow.md`](git-workflow.md) 检查 commit message 格式
2. 多个改动:决定是合并 commit 还是拆分
3. 涉及版本 bump:走 [`../VERSION.md`](../VERSION.md) §4 操作清单

### 跑 Bash 命令时

1. 查 [`bash-conventions.md`](bash-conventions.md) 避免触发 permission 弹窗
2. 复合命令(`cd && ` / 管道 `|`)用替代写法

### 做开发任务时

1. 查 [`dev-sop.md`](dev-sop.md) 找对应任务类型(加字段 / 加命令 / 修 bug / 大改动)
2. 按 SOP 顺序走,不跳步

---

## 🔗 相关索引

| 内容 | 位置 |
|---|---|
| 版本号规则 | [`../VERSION.md`](../VERSION.md) |
| 路线图 | [`../ROADMAP.md`](../ROADMAP.md) |
| 完整变更日志 | [`../../CHANGELOG.md`](../../CHANGELOG.md) |
| 系统架构 | [`../ARCHITECTURE.md`](../ARCHITECTURE.md) |
| 飞书字段定义 | [`../feishu-schema.md`](../feishu-schema.md) |
| 用户向 release notes | [`../releases/`](../releases/) |
| 开发日志(按日) | [`../logs/daily/`](../logs/daily/) |
| OB 对接 handoff | [`../handoff/OB对接/`](../handoff/OB对接/) |
| 项目 CC 入口 | [`../../.claude/CLAUDE.md`](../../.claude/CLAUDE.md) |
