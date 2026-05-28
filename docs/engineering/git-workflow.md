---
title: Git 工作流规范
type: engineering
status: active
created: 2026-05-28
updated: 2026-05-28
tags: [规范, git, commit, push]
related: ["[[README]]", "[[iron-rules]]", "[[../VERSION]]"]
---

# Git 工作流规范

> commit message 格式 / tag / 双推 / 与 ROADMAP-CHANGELOG-handoff 联动。

---

## 1. 远程仓库结构

| Remote | URL | 用途 |
|---|---|---|
| `all` | `https://github.com/wukongai/feishukanban-ob-sync.git`(fetch + push) | GitHub 主仓 |
| `all` | `https://gitee.com/teacherai/feishukanban-ob-sync.git`(push) | Gitee 镜像 |

**双推机制**:`git push all main` 一条命令同时推 GitHub + Gitee。

**格式约定**:统一 HTTPS(`https://`),**不用 SSH**(Clash Verge 代理 fake-ip 模式会拦截 SSH 流量,导致 git 操作失败)。

---

## 2. Commit message 格式

### 模板

```
<type>(<scope>): <一句话主旨,中文 OK>

<空行>

<body:多段描述具体改动,中文 OK,可含表格 / 代码块>

<空行>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

### type 枚举(参考 conventional commits,简化版)

| type | 用途 | 是否 bump 版本号 |
|---|---|---|
| `feat` | 新功能 / 新字段 / 新命令 | ✅ MINOR bump |
| `fix` | bug 修复 | ✅ PATCH bump |
| `docs` | 仅文档改动(不动代码) | ❌ 不 bump |
| `refactor` | 重构(无功能 / 行为改变) | ❌ 不 bump |
| `chore` | 构建 / 工具链 / 杂项 | ❌ 不 bump |
| `test` | 加测试 | ❌ 不 bump |

### scope 约定

- 含版本号:`feat(v0.3.7): pull-today 反向字段 diff sync`
- 不含版本号(纯杂项):`chore(install.sh): banner 版本号同步`
- 跨工程 handoff:`docs(handoff): v0.3.5 反向回执 status pending → done`

### 真实示例(v0.3.5+ 风格)

```
feat(v0.3.7): pull-today 反向字段 diff sync — 飞书改 status 后 OB 实时同步

背景:用户实测痛点(2026-05-28)
"5月28日AI日报已经是 done,但依然显示的是 todo,改成 subdone 也不行,
 问题在于看板是实时修改状态,需要在修改后拉回新的状态"

v0.3.6 之前 pull-today 设计上只同步 today 字段...

3 个新 helper(DRY):
- _extract_fields_from_feishu_row:抽飞书 row 字段 dict
- _strip_wikilink:OB wikilink → 裸名字
- _diff_frontmatter_with_feishu:读 OB frontmatter + diff + 防误清

用户实测(2026-05-28):5 条 task md 反向同步成功 — status/priority diff 全检出,0 false positive

v0.3.8 候选:parent_project link 字段反向 + iteration_* 多选 list 反向。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## 3. Tag 规范

### 何时打 tag

- ✅ 每个版本号都打 tag(`vX.Y.Z`)
- ❌ 不打 patch hotfix tag(就是 bump PATCH)

### 命令

```bash
# commit 完成后
git tag vX.Y.Z

# 推 tag(双推)
git push all vX.Y.Z
```

### tag 命名

- 严格 `v` 前缀:`v0.3.7`(不是 `0.3.7` 或 `V0.3.7`)
- 不打 `-beta` / `-rc` 后缀(v0.x 期本身就是 pre-release)

---

## 4. 完整流程(一次 bump 走完)

参考 [`../VERSION.md`](../VERSION.md) §4 操作清单。简化版:

```bash
# 1. 改代码 + 测试
# (在真实 vault 跑 sync.py 验证 — 铁律 #6)

# 2. 文档同步(铁律 #5)
# - CHANGELOG.md 加 entry
# - README.md badge + 顶部 vX.Y.Z 上线 section
# - install.sh banner
# - docs/ARCHITECTURE.md(如涉及 schema)
# - docs/releases/vX.Y.Z.md
# - docs/VERSION.md §7 索引补一行

# 3. stage + commit
git add sync.py CHANGELOG.md README.md install.sh docs/...
git commit -m "$(cat <<'EOF'
feat(vX.Y.Z): 一句话主旨

详细 body...

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

# 4. tag
git tag vX.Y.Z

# 5. 给用户 review(铁律 #1!)
git log -1 --stat
# → 用户说 "push" 才下一步

# 6. 双推 main + tag
git push all main
git push all vX.Y.Z

# 7. (可选)如果是跨工程协作:写反向回执
# docs/handoff/OB对接/YYYY-MM-DD-vX.Y.Z-反向回执.md
# 再独立 commit + push
```

---

## 5. 安全红线

### ❌ 永远不做

- `git push --force main`(会污染 commit 历史 + 其他人 pull 报错)
- `git reset --hard HEAD~N` 已推送的 commit(同上)
- `git commit --no-verify`(跳过 pre-commit hook)
- `git commit --amend` 已推送的 commit(改了远端 hash,别人 pull 错)

### ⚠️ 谨慎做(必须用户授权)

- `git stash`(本地改动可能丢)→ 优先 `git diff > patch.diff` 备份
- `git rebase`(可能造成丢 commit)
- 删本地分支前 `git log --all` 看是否有未 push 的

### ✅ 鼓励做

- 频繁 `git commit`(prefer 小 commit + clear message)
- 每次大改动前先 `git status` + `git diff` 看清楚
- 用户 review 时给 `git log -1 --stat`(看 commit message + 文件变更量)

---

## 6. 跨工程协作的 git 边界

仓库 CC ↔ OB Claudian 之间:

| 谁能动什么 | 仓库代码 | OB vault |
|---|---|---|
| 仓库 CC | ✅ 全权 | ❌ 不动(走 handoff) |
| OB Claudian | ⚠️ 跨边界例外允许(详见 OB vault `.claude/rules/cross-project.md`) | ✅ 全权 |

**跨边界例外条件**(3 条):
1. 服务对象唯一是 OB vault
2. 风险可控(本地未 push,可 reset)
3. 用户明确授权

v0.3.4 的 `__filename` 修复就是 OB CC 跨边界例外修的,详见 [`../handoff/OB对接/2026-05-27-v0.3.4-__filename-修复-跨边界例外-反向回执.md`](../handoff/OB对接/2026-05-27-v0.3.4-__filename-修复-跨边界例外-反向回执.md)。

---

## 7. handoff 文档命名(跨工程)

[`../handoff/OB对接/`](../handoff/OB对接/) 命名规则:

```
YYYY-MM-DD-<主题>-handoff.md         # 仓库 → OB
YYYY-MM-DD-<主题>-反向回执.md         # OB → 仓库(完成确认 + Spec 偏离)
YYYY-MM-DD-<主题>-起手指令.md         # 用户给目标 CC 的 1-2 句话提示
```

handoff frontmatter 必含:`status: handoff-pending / done` + `priority` + `estimated_effort`。

---

## 🔗 相关

- 6 条铁律:[`iron-rules.md`](iron-rules.md)
- 版本号规则:[`../VERSION.md`](../VERSION.md)
- 当前路线图:[`../ROADMAP.md`](../ROADMAP.md)
- Bash 命令写法:[`bash-conventions.md`](bash-conventions.md)
