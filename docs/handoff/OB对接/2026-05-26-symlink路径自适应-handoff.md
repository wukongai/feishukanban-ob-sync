---
created: 2026-05-26T20:45:00
status: handoff-pending
from_project: feishukanban-ob-sync(Claude Code in VS Code)
to_project: OB(Claudian)
to_repo: /Users/aim5/Documents/OB/
priority: P1
estimated_effort: 0.5 小时
tags:
  - handoff
  - symlink
  - 路径自适应
  - vault整洁
---

# Handoff:把 vault 内 symlink 搬到"统一外部工具"位置(v0.3.2 配套)

## 一句话需求

独立仓库已完成 v0.3.2 自适应改造(userscript 用 `__filename` 推导 sync.py 路径,install.sh 加 `--scripts-dir` flag)。**请 OB CC 选定新路径,在 vault 内删旧 symlink + 跑新 install.sh + 更新 QuickAdd data.json**,让"外部 symlink 统一管理"诉求落地。

## 背景

用户原话:
> "如果是软连接那就需要整理一下这个链接的文字,所有外部的这种软连接都是放在 ob 的小工具下的,统一管理,保证 ob 文件夹的整洁。"

当前状态(v0.3.1):
- vault 内 `/Users/aim5/Documents/OB/scripts/feishukanban-ob-sync/` 下:
  - `sync.py` → symlink → 仓库
  - `auto_collect_today.py` → symlink → 仓库
  - `userscripts/quickadd-{完成task,快记任务-v2-task-md,拉今日todo,同步飞书项目}.js` → symlink → 仓库
  - `__pycache__/`(真目录,Python 缓存)
- vault 根多了 `scripts/` 顶层目录,"开发用"性质明显,跟用户的 PARA 私域结构(`01 Project/...`)风格不一致

v0.3.2 独立仓库已完成的改造:
- 4 个 userscript 不再硬编码 `${vaultRoot}/scripts/feishukanban-ob-sync/sync.py`,改用 `path.resolve(path.dirname(__filename), '..', 'sync.py')` 自适应
- install.sh 加 `--scripts-dir <vault-relative-path>` flag,可装到 vault 任意位置
- sync.py:60 顺手修了 `VAULT_ROOT = SCRIPT_DIR.parents[4]` 这个 dead-code bug(symlink resolve 后路径错)

## 目标 / 非目标

### ✅ 目标

- OB CC **选定一个新路径**(用户给的指导是"放在 ob 的小工具下统一管理",具体在哪由你判断)
- 在 vault 内**删旧 symlink**(`/Users/aim5/Documents/OB/scripts/feishukanban-ob-sync/`)+ `__pycache__/`
- **跑 install.sh** 用 `--scripts-dir <新相对路径>` 把 sync.py / auto_collect_today.py / 4 个 userscripts 装到新位置(都是 symlink)
- **更新 QuickAdd data.json** 的 4 个 choice 的 `path` 字段(install.sh 会把新 path 写到 `$REPO_DIR/.quickadd-choices.json` snippet,手动 merge 进 `.obsidian/plugins/quickadd/data.json`)
- **重启 Obsidian + 测 4 个 Cmd+P 命令**全部跑通
- 写**反向回执**到本 `docs/handoff/OB对接/2026-05-26-symlink路径自适应-反向回执.md`,告诉独立 CC vault 端落地情况
- **顺手更新 `.claude/CLAUDE.md` line 178-184 那段过时的"vault 内 sync.py 路径"描述**(写实际新位置)

### ❌ 非目标

- 不要改独立仓库代码(独立 CC 已完成,直接用)
- 不要改飞书 schema(完全不动)
- 不要改 task md 模板(完全不动)
- 不要回滚 v0.3.0/v0.3.1 已有功能

## 接口契约

### 输入(独立仓库给你的)

| 资源 | 用途 |
|---|---|
| `install.sh --scripts-dir <path>` flag | 自定义装到 vault 哪个相对位置 |
| `install.sh --apply --force --scripts-dir <path>` | 覆盖现有 symlink(强制重装) |
| `install.sh --vault-path /Users/aim5/Documents/OB` | 显式 vault 路径(避免交互式询问) |
| `$REPO_DIR/.quickadd-choices.json` | install.sh 自动生成的 QuickAdd choices snippet,path 跟 `--scripts-dir` 走 |

### 输出(你要交付的)

- vault 内新位置有 6 个文件(2 个 .py symlink + 4 个 .js symlink)
- vault 内旧位置 `/Users/aim5/Documents/OB/scripts/feishukanban-ob-sync/` 整个删除(含 `__pycache__/`)
- `.obsidian/plugins/quickadd/data.json` 的 4 个 choice path 字段已更新(指向新位置)
- 4 个 Cmd+P 命令在 Obsidian 真实测试跑通(每个至少跑一次)

## 实施步骤

### Step 1:决定新路径

> 这是你的判断题。用户没指定具体位置,只说"放在 ob 的小工具下统一管理"。

参考候选(任选,或你有更好的):
- `01 Project/00 进行中/06 小工具开发/外部symlink/feishukanban-ob-sync/`(语义化分类清晰,但层级较深)
- `01 Project/00 进行中/06 小工具开发/feishukanban-ob-sync/`(简短)
- `02 Area/工具集/feishukanban-ob-sync/`(归到 Area,长期工具)
- 你判断的别的位置

**决策标准**(参考):
- 路径里别含空格(install.sh 测过含空格的路径能工作,但加点容错总是好的)—— 不过用户 PARA 结构原本就有空格(`00 进行中`),所以这条可放宽
- 跟 vault 现有"外部 symlink"统一(如果用户其他 vault 项目有类似 symlink,放一起)
- 简短易记(用户后续要在 Cmd+P 命令出错时翻日志找 sync.py 路径)

### Step 2:备份(铁律 #2 不污染 vault)

```bash
# 备份旧目录(以防 install.sh 出意外)
mv /Users/aim5/Documents/OB/scripts/feishukanban-ob-sync \
   /Users/aim5/Documents/OB/scripts/feishukanban-ob-sync.backup-$(date +%Y%m%d-%H%M%S)
```

### Step 3:跑新 install.sh

```bash
# 替换 <你选的新相对路径>
/Users/aim5/Documents/CodingProject/feishukanban-ob-sync/install.sh \
  --vault-path /Users/aim5/Documents/OB \
  --scripts-dir "01 Project/00 进行中/06 小工具开发/feishukanban-ob-sync" \
  --apply
```

预期输出包含:
- `📂 装到 vault 相对路径: <你的路径>(用 --scripts-dir 改)`
- Step 3: symlink sync.py + auto_collect_today.py 到 `$VAULT/<scripts-dir>/`
- Step 4: symlink 4 个 userscripts 到 `$VAULT/<scripts-dir>/userscripts/`
- Step 6: `.quickadd-choices.json` 写到 `$REPO_DIR/.quickadd-choices.json`
- Step 7: 提示后续手动步骤

### Step 4:把 config.yaml symlink 也搬过去

> ⚠️ install.sh 不管 config.yaml(铁律 #2 禁止覆盖 vault 内 config)。手动 ln:

```bash
ln -s /Users/aim5/Documents/CodingProject/feishukanban-ob-sync/config.yaml \
      "/Users/aim5/Documents/OB/<你的scripts-dir>/config.yaml"
```

### Step 5:更新 QuickAdd data.json

打开 `/Users/aim5/Documents/OB/.obsidian/plugins/quickadd/data.json`,找到 4 个 choice(`quick-task-v2-choice` / `pull-today-choice` / `complete-task-choice` / `feishu-task-sync-quickadd-choice`),把每个 choice → macro → commands[0] 的 `path` 字段改成新路径。

参考 `$REPO_DIR/.quickadd-choices.json`(install.sh 生成),里面的 path 已经是新值,可以直接复制。

或者用 jq 一行命令(更稳):
```bash
NEW_DIR="01 Project/00 进行中/06 小工具开发/feishukanban-ob-sync"  # 你选的
jq --arg dir "$NEW_DIR" '
  .choices |= map(
    if .macro.commands[0].path | test("scripts/feishukanban-ob-sync/userscripts/")
    then .macro.commands[0].path |= sub("scripts/feishukanban-ob-sync/userscripts/"; $dir + "/userscripts/")
    else . end
  )
' /Users/aim5/Documents/OB/.obsidian/plugins/quickadd/data.json > /tmp/data.json.new \
  && mv /tmp/data.json.new /Users/aim5/Documents/OB/.obsidian/plugins/quickadd/data.json
```

### Step 6:Cmd+Q 重启 Obsidian

QuickAdd 启动时读 `data.json`,改完必须重启才生效。

### Step 7:真实测试 4 个命令

在 Obsidian 里依次跑(铁律 #6 真实 vault 测):

| 命令 | 期望行为 |
|---|---|
| Cmd+P → 📝 快记任务 | 弹项目选择 → 弹标题输入 → 弹 today=true/false → 创建 task md → 自动 sync 飞书 CREATE → 「## ✅ 完成标记」段下 checkbox 变 markdown link |
| Cmd+P → 📥 拉今日 todo | Notice 显示 set true/false/skip 数 → 今日 journal 自动刷新 |
| Cmd+P → ✅ 完成 task(在某 task md 内) | frontmatter status: done + done_date 更新 → 自动 sync 飞书 UPDATE |
| Cmd+P → 🎯 同步今日 task 到飞书 | 调起 Claudian + 填入 `/飞书项目同步 @journals/today.md --only-completed` |

任何一条失败 → 看 Cmd+Opt+I Console,如果是 `sync.py` 路径找不到,大概率是 `__filename` 没解析对——立即在反向回执里写明具体报错。

### Step 8:更新独立仓库 .claude/CLAUDE.md(铁律 #5 文档同步)

`/Users/aim5/Documents/CodingProject/feishukanban-ob-sync/.claude/CLAUDE.md` line 178-184 那段「vault 内 sync.py 路径」描述是 v0.2.x 时代的过时信息,需要改成你新选的位置。

> ⚠️ 注意:OB CC 改独立仓库 .claude/CLAUDE.md 这一动作本身**违反铁律 #7**(OB CC 不得直接 commit 独立仓库代码)。本次允许的例外是:
> - 仅改文档(`.claude/CLAUDE.md`)且**不要 commit**——留着 working tree 改动,让独立 CC 自己 commit
> - 反向回执里写明"vault 路径段更新已留在 working tree,独立 CC 请 review + commit"

### Step 9:写反向回执

新建 `/Users/aim5/Documents/CodingProject/feishukanban-ob-sync/docs/handoff/OB对接/2026-05-26-symlink路径自适应-反向回执.md`,模板参考 `2026-05-26-v0.3.1-反向回执-OB端落地.md`。

内容应包含:
- 你选的最终路径
- 实际 install.sh 命令
- 4 个 Cmd+P 测试结果(全过 ✅ / 哪一条失败 ❌)
- 偏离点(如果有任何步骤跟本 handoff 不一致)
- vault 路径段 .claude/CLAUDE.md 改动留在 working tree(等独立 CC commit)

## 测试用例(完整 4 条)

| # | 场景 | 触发 | 预期 |
|---|---|---|---|
| 1 | 快记任务跨日 | 在 journal 内 Cmd+P → 快记任务 | task 文件名/created/today_history 都用 journal 日期(v0.3.1 块 ④) |
| 2 | pull-today 残留清理 | 飞书取消某 task 「是否今日」 → Cmd+P → 拉今日 todo | 该 task 在今日 journal 消失(v0.3.1 块 ③) |
| 3 | 完成 task 自动 sync | task md 内 Cmd+P → ✅ 完成 task | status: done + 飞书侧状态变 done(v0.2.x 已有) |
| 4 | CREATE 自动加 link | 新建 task → 看「## ✅ 完成标记」段 | 裸 `- [ ] title` 变 `- [ ] [title](飞书url)`(v0.3.1 块 ②) |

## 风险 / 注意点

- **风险 1**:install.sh `--force` 会覆盖旧 symlink,但**不会**删整个旧目录(`scripts/feishukanban-ob-sync/`),需要你手动删。所以本 handoff Step 2 让你先备份+移走旧目录,新位置完全干净。
- **风险 2**:userscript 的 `__filename` 在 Obsidian Electron 环境**未经实测**,只测过 Node CLI 标准行为。如果 `__filename` 解析异常(如返回 symlink 真实路径 = 仓库内位置),syncScript 会指向 `仓库/sync.py`——这其实也能跑(因为 sync.py 就在仓库里),但 `--vault` 参数仍然传 vaultRoot,sync.py 写的还是 vault,所以**最坏情况也不破坏功能**。
- **风险 3**:QuickAdd data.json 是 JSON 文件,jq 改写要小心 macOS 自带的 jq 老版本可能 `test()` regex 行为不一致。如果 jq 命令报错,用 VS Code/Obsidian 直接打开 data.json 手动改 4 处 path 即可。
- **风险 4**:本 handoff Step 8 让 OB CC 改独立仓库的 `.claude/CLAUDE.md`,理论上违反铁律 #7。本次例外的原因是这个改动是回执依赖项(你定了路径,独立 CC 才能在文档里写对路径)。如果你严守铁律 #7,可以**只写反向回执里说明"vault 路径已变为 X,请独立 CC 自己改 CLAUDE.md line 178-184"**,不动手改,把球踢回来。

## 完成记录(OB CC 填)

- 完成时间:
- 实际花费:
- 选定的 --scripts-dir 值:
- 4 个 Cmd+P 测试结果:
- 偏离点:
- 反向回执文件:
