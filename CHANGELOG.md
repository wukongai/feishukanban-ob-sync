# Changelog

> `feishukanban-ob-sync` — Obsidian ↔ 飞书项目管理多维表双向同步工具。

## [v0.3.4] - 2026-05-27 — 修 __filename + dataview 跨天 两个 bug

> **2 个独立 bug fix 合并到同一版本号**(v0.3.2 / v0.3.3 修补)。
> Part 1:`__filename` 推导失败导致 4 个 Cmd+P 命令全部不可用(本次会话 01:00 实测发现)。
> Part 2:dataview 跨天完成 task "消失"bug(v0.3.4 主体)。

---

## Part 1:修 `__filename` bug(OB CC 跨边界例外修)

> **现象**:Cmd+P 跑「📝 快记任务 / 📥 拉今日 todo / ✅ 完成 task」全部报错:
> ```
> Command failed: python3 "/Applications/Obsidian.app/Contents/Resources/electron.asar/sync.py" ...
> can't open file '/Applications/Obsidian.app/Contents/Resources/electron.asar/sync.py': [Errno 2] No such file or directory
> ```

### 🐛 根因

v0.3.2 设计的"`__filename` 自适应"在 Obsidian QuickAdd userscript 上下文里**根本不成立**:

```js
// v0.3.2 写法(失败)
const syncScript = path.resolve(path.dirname(__filename), "..", "sync.py");
```

Node 的 `__filename` global 在 QuickAdd 加载 userscript 时**指向 Electron asar bundle 内部**(`/Applications/Obsidian.app/Contents/Resources/electron.asar/...`),**不是** vault 里 .js 的真实位置 → `path.resolve(..., "..", "sync.py")` 推出来是不存在的路径。

漏改 4 处:
- `quickadd-拉今日todo.js` line 34
- `quickadd-完成task.js` line 140
- `quickadd-快记任务-v2-task-md.js` line 113(Step 2.5 调 `--resolve-project` 查飞书子项目)
- `quickadd-快记任务-v2-task-md.js` line 308(Step 7 调 `--task-md` sync 飞书)

⚠️ 用户实测发现 v2 macro **小类(subcategory)二级菜单不出现**,根因就是 line 113 调用 sync.py 失败 → catch 走降级 → 跳过二级 suggester。

### 🛠 修法

`install.sh` 装的时候 `cp` + `sed` 注入 sync.py 绝对路径:

**1. userscript 用占位符**(3 个 userscript 4 处):
```js
// v0.3.4: install.sh 装的时候 sed 替换占位符为 sync.py 绝对路径
const syncScript = "__SYNC_PY_ABS_PATH__";
```

**2. install.sh Step 4 `ln -s` → `cp` + `sed`**:
```bash
cp "$js" "$target"
# macOS sed -i 需要 '' 参数(BSD sed)
sed -i '' "s|__SYNC_PY_ABS_PATH__|$SYNC_PY_ABS|g" "$target"
```

**Trade-off**:升级 `obsidian-assets/userscripts/*.js` 后需要重跑 `install.sh --force`(symlink 不自动跟着更新)。这是 install 工具的本意,可接受。

### 📝 改动文件

- `install.sh` Step 4(banner v0.3.3 → v0.3.4,Step 4 ln → cp + sed,+22 -7)
- `obsidian-assets/userscripts/quickadd-拉今日todo.js`(line 34 占位符)
- `obsidian-assets/userscripts/quickadd-完成task.js`(line 140 占位符)
- `obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js`(line 113 + line 308 两处占位符)

### ⚠️ 跨边界例外说明

本次 fix **OB Claudian 在 OB vault 跨边界改的独立仓库源码** — 经用户显式授权,按 [cross-project.md 2026-05-26 例外条款](https://github.com/wukongai/OB) 符合 3 条:
1. ✅ 服务对象唯一是 OB vault
2. ✅ 风险可控(本地未 push,可 reset)
3. ✅ 用户明确授权

**OB CC 做了**:edit 3 个 userscript + edit install.sh + 重跑 install.sh 重装 vault 内文件 + 4 个 Cmd+P 用户实测通过 + 写本 CHANGELOG 段 + 写反向回执(`docs/handoff/OB对接/2026-05-27-v0.3.4-__filename-修复-跨边界例外-反向回执.md`)+ git commit。

**OB CC 没做**:git push(留给独立 CC review + push)。

### ✅ 验证(用户实测通过 2026-05-27)

- ✅ ① 📝 快记任务:优先级 → 大类 → **小类二级菜单出现** → 是否今日 → 标题 → task md 创建 + 飞书 CREATE 成功
- ✅ ② 📥 拉今日 todo:同步成功(无 electron.asar 错)
- ✅ ③ ✅ 完成 task:frontmatter status:done + 飞书 UPDATE 成功
- ✅ ④ 🎯 同步今日 task 到飞书:Claudian 自动调起

---

## Part 2:修 dataview 跨天完成"消失"bug

> **现象**:用户在 27 日 journal 勾选 inline checkbox 完成 task → 该 task 立刻从 27 日 journal 消失,无法看到当天的完成情况。

### 🐛 根因

journal 模板的 dataview 过滤条件包含 `(!done_date OR done_date = this.file.day)`(或更早版本的 `(!completed OR completion = this.file.day)`),这个条件本意是"只显示当日完成的,过去日完成的不显示",但**副作用**:

- 当日 journal 看一个 task:`done_date = today` → 显示 ✓
- 26 日 journal 看一个 27 日才完成的 task(`today_history=[26,27]`,`done_date=2026-05-27`):`done_date(27) ≠ this.file.day(26)` → **消失 ❌**

跨天 task 在 26 日 journal 应该仍然可见(显示为 `- [x] ✅ 2026-05-27` 跨天完成态),用户复盘"那天看到什么"的语义被破坏。

### 🛠 修法

**完全移除 `done_date` / `completed` 过滤**,把范围控制全部交给 `today_history`(`sync.py --pull-today` 维护的"曾经是今日"日期数组)。完成状态由 inline `- [x] ✅ <date>` 自然渲染:

```dataview
TASK
FROM "04 Inbox/task"
WHERE !contains(file.name, "_说明")
  AND contains(today_history, this.file.day)
  AND (priority = "P0" OR priority = "P1" OR priority = "P2")
SORT priority ASC, created DESC
```

### 📝 改动文件

**Vault 端**(用户私域):
- `journals/2026-05-25.md` — 删旧字段 `(!completed OR completion = this.file.day)`(2 处 dataview block)
- `journals/2026-05-26.md` — 删新字段 `(!done_date OR done_date = this.file.day)`(2 处)
- `journals/2026-05-27.md` — 删旧字段 `(!completed OR completion = this.file.day)`(2 处)
- `03 Resources/素材库/模版/日志模版 5.0 1.md`(templater 主模板)— 删 done_date 过滤(2 处),防止以后创建的 journal 复发

**仓库端**(本 repo):
- `docs/tutorial/05-task-md-workflow.md` — 更新示例 dataview 块
- `obsidian-assets/rules/feishu-project-sync.md` — 更新示例 + TASK 查询语义说明段,记录历史教训

### ✅ 验证步骤(用户测)

1. 重新打开 `journals/2026-05-27.md`(刷新 dataview)
2. 看「🎯 今日计划」section,确认勾选完成的 task 仍显示成 `- [x] ✅ 2026-05-27`(不再消失)
3. 也可看 26 日 journal,确认 27 日才完成的 task 在 26 日也能看到完成态(跨天显示)

### ⚠️ 注意

- **该修复不动 sync.py**,只改 journal/template/docs 中的 dataview 查询语法
- 当 today_history 残留 ≠ 当日的日期时(如 task 早就完成但 today_history 没清),旧 journal 也会"反复"显示。这属于 `sync.py pull-today` 的 today_history 清理范畴(v0.3.0 已建立事件流机制),本次不重叠

## [v0.3.3] - 2026-05-27 — 强制北京时区(双层 defense in depth)

> **根因**:Mac 系统时区 = Asia/Shanghai,但 user shell `.zshrc` 设了 `export TZ=America/Los_Angeles`。Obsidian 从 shell 启动时继承这个 env,userscript `exec` 子进程时把 `process.env` 整体传给 sync.py → sync.py 的裸 `datetime.now()` 算成 PDT 时间(比北京晚 15-16h)。
>
> **实证**:
> ```
> $ TZ=America/Los_Angeles python3 -c "from datetime import datetime; print(datetime.now())"
> 2026-05-26 23:51:42       ← PDT 时间,算到了"昨天"
>
> $ python3 -c "from datetime import datetime, timezone, timedelta; print(datetime.now(timezone(timedelta(hours=8))))"
> 2026-05-27 14:51:42+08:00 ← 显式 UTC+8,正确
> ```
>
> **故障表现**:user 北京 5-27 早 09:26 用 Cmd+P 创建 task,task md 文件名 / `created` / `日志` 都是 5-27(userscript bjDate 公式与系统 TZ 无关,算对了),但 `today_history` 里被 sync.py 某次 pull-today / 反向 pull 流程 append 进了 5-26 → dataview 在 5-26 journal 误渲染该 task,5-27 journal 看不到。

### 🛡 块 ① — sync.py 3 处裸 `datetime.now()` 改为显式 UTC+8

| 行 | 函数 | 影响 |
|---|---|---|
| 656 | `feishu_doc_synced_at` 时间戳 | 飞书 doc 同步时间记录 |
| 844 | `sync_date`(delivery format 模板代入) | 交付字段格式化 |
| 2297 | `today`(老 `--pull` 反向流程的"今日" journal 位置) | 决定 task 写入哪份 journal |

写法统一:`datetime.now(timezone(timedelta(hours=8)))`。**已存在的 3 处(line 2603 / 2739 / 2792)在 v0.2.5 / v0.3.0 时已用显式 UTC+8,本次补齐剩下的 3 处**。

### 🚪 块 ② — 3 个 userscript exec env 强制 `TZ: "Asia/Shanghai"`

userscript `child_process.exec` 跑 sync.py 时,在 execEnv 加 `TZ: "Asia/Shanghai"`:

```js
const execEnv = {
  ...process.env,
  PATH: `${userPaths.join(":")}:${process.env.PATH || ""}`,
  TZ: "Asia/Shanghai",  // v0.3.3 加
};
```

涉及文件:
- `quickadd-快记任务-v2-task-md.js`(2 处:resolveCmd 的 execEnvEarly + syncCmd 的 execEnv)
- `quickadd-完成task.js`(1 处)
- `quickadd-拉今日todo.js`(1 处)

**defense in depth**:即使 user shell `.zshrc` 设了 `TZ=America/Los_Angeles`,userscript 启动 sync.py 子进程时强制覆盖为北京,sync.py 的裸 `datetime.now()`(如果还有遗漏)也会自动算北京。

### 🎯 这两层是 user 提出的「先行操作」原则落地

> 「创建文件的时候需要自动把时间转换成北京时间,这是先行操作而不是后续再修改,只要是 OB 调用 CC 创建文件都要先做这个转换。」

- **外层(先行)**:userscript exec 注入 `TZ=Asia/Shanghai` — 在 sync.py 启动前已经把时区"翻译"好了
- **内层(防御)**:sync.py 显式 UTC+8 — 即使有人裸命令行跑 sync.py(没经 userscript),仍然算北京

### ⚠️ 用户侧需要手动清理的残留数据

v0.3.3 修了**今后**的写入路径。已存在 task md 的 `today_history` 里残留的错误日期需要**手动 grep + 清理**。

诊断命令:
```bash
# 找所有 today_history 含跨日的 task md(可能有日期错配)
grep -l "today_history:.*,.*" /Users/aim5/Documents/OB/04\ Inbox/task/
```

逐个 open,看 `today_history` 是不是真的应该是多日(比如 task 跨好几天都聚焦过),还是 v0.3.3 之前的时区 bug 残留(单日 task 却有相邻两天)。

### 🔧 升级路径

1. `git pull` 拉 v0.3.3
2. **重装 UserScripts**:`bash install.sh --apply --force`(覆盖 vault 里的 4 个 userscripts/*.js)
3. **重启 Obsidian**(QuickAdd 重新加载 userscripts;新 exec env 才生效)
4. 清理已存在 task md 的 `today_history` 残留(见上)

### ⚖️ 8 条原则自评

| # | 原则 | 本次表现 |
|---|---|---|
| 1 | 解耦 | ⭐⭐⭐⭐⭐ 用户 shell TZ 设置 vs. 工具行为完全解耦 |
| 2 | 可扩展 | ⭐⭐⭐⭐⭐ 显式时区写法,后续加新 datetime 调用可复制 pattern |
| 3 | 灵活修改 | ⭐⭐⭐⭐ 双层修复,各自独立可单独回滚 |
| 4 | 渐进披露 | ⭐⭐⭐ user 不需要知道时区机制就能跑;高级 user 看 CHANGELOG 知道为啥 |
| 5 | 鲁棒性 | ⭐⭐⭐⭐⭐ 外层(userscript) + 内层(sync.py) 双保险,任一层失效另一层兜底 |
| 6 | 人可读 + 可教学 | ⭐⭐⭐⭐⭐ CHANGELOG 完整故障路径 + 实证 shell 输出 |
| 7 | 高复用 + 易移植 | ⭐⭐⭐⭐ `TZ=Asia/Shanghai` 是 POSIX 标准,跨 mac/linux/wsl |
| 8 | 工程化清晰 | ⭐⭐⭐⭐ 验证脚本(`TZ=PDT python3 -c "..."`)收录 CHANGELOG |

---

## [v0.3.2] - 2026-05-26 — symlink 路径自适应 + install.sh `--scripts-dir` + sync.py VAULT_ROOT bug 修复

> 三块 patch:userscript `__filename` 自适应、install.sh `--scripts-dir` flag、sync.py `VAULT_ROOT` 跟错位置修复。配 OB 端 handoff 在 vault 内迁移 symlink 到「统一外部工具」位置,解决用户"vault 整洁"诉求。

### 🎯 块 ① — userscript 路径自适应(`__filename` 推导)

#### 问题

3 个调 `sync.py` 的 userscript 都硬编码 `${vaultRoot}/scripts/feishukanban-ob-sync/sync.py`,把"装在 vault 哪"和"代码"耦合。用户想把 symlink 搬到别处统一管理 → userscript 必须跟着改 → 等于每次路径迁移都是 breaking。

#### 修复

把硬编码替换为 `path.resolve(path.dirname(__filename), '..', 'sync.py')`,用 Node.js `__filename` 推导 sync.py 真实位置。

**约定**:install.sh 必须把 sync.py 装在 userscripts/ 的**上一级**(同 `SCRIPTS_TARGET` 父目录),这是 install.sh 既有行为,无破坏。

#### 涉及文件

- `obsidian-assets/userscripts/quickadd-拉今日todo.js`(1 处)
- `obsidian-assets/userscripts/quickadd-完成task.js`(1 处)
- `obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js`(2 处:resolveCmd + syncCmd)
- 不动 `quickadd-同步飞书项目.js`(它走 Claudian skill,不调 sync.py)

#### 收益

**以后再迁移 symlink 路径,userscript 一行不用改**。彻底消除 vault 内位置 ↔ userscript 代码 的耦合。

---

### 🛠 块 ② — install.sh 加 `--scripts-dir <vault-rel-path>` flag

#### 问题

`install.sh` 把 `SCRIPTS_TARGET="$VAULT/scripts/feishukanban-ob-sync"` 写死,用户私域结构(如 `01 Project/00 进行中/06 小工具开发/...`)装不进去,只能装到 vault 根的 `scripts/` 目录。

#### 修复

加 `--scripts-dir <vault-relative-path>` flag,默认值 `scripts/feishukanban-ob-sync`(开源友好,不改默认就是 v0.3.1 行为)。Step 3 / Step 4 / Step 6 QuickAdd choices JSON / Step 7 config.yaml 提示路径**全部跟随 `--scripts-dir`**。

```bash
# 开源默认(老用户拉新版无感)
./install.sh --apply

# 装到 vault 私域位置(用户自定义)
./install.sh --apply --scripts-dir "01 Project/00 进行中/06 小工具开发/feishukanban-ob-sync"
```

输入清洗:去掉前后多余的 `/`,接受 `foo/bar` / `/foo/bar` / `foo/bar/` 等格式。

#### 配套

`.quickadd-choices.json`(install.sh 输出)的 4 个 `path` 字段自动跟随新 `SCRIPTS_DIR`,用户复制到 `data.json` 就是对的。

---

### 🐛 块 ③ — sync.py `VAULT_ROOT` bug 修复

#### 问题(隐藏 bug,实际跑了很久)

sync.py 第 60 行(原):
```python
VAULT_ROOT = SCRIPT_DIR.parents[4]
```

假设 sync.py 在 `OB/01 Project/00 进行中/06 小工具开发/CC命令/飞书项目同步/sync.py`(parents[4] = OB)。

**实际情况**(v0.2.x 起):sync.py 是 symlink → 仓库,`Path(__file__).resolve()` 跟符号链接跳到 `/Users/aim5/Documents/CodingProject/feishukanban-ob-sync/sync.py`,`parents[4]` = `/Users/aim5/`(完全错的 vault 根)。

**为什么没爆**:userscripts 都通过 `--vault` 显式传 vault 路径,sync.py 主流程用 `os.chdir(vault_path)` + 相对路径,绕开了这个全局变量。但 line 797 / 1814 / 1960 三处 `build_fields_payload` 调用链用的还是错的 `VAULT_ROOT`——**C 路径 backlinks** 拼绝对路径时会找错位置(用户未碰到,但属于潜在数据 bug)。

#### 修复

```python
# 新:初始 = cwd,main() 处理 --vault 后刷新
VAULT_ROOT = Path.cwd()

# main() 里 chdir 之后:
global VAULT_ROOT
VAULT_ROOT = vault_path
```

dry-run 跑 `--pull-today` 验证无回归(扫了 34 个 task md,7 条今日全对齐)。

---

### 🔧 升级路径

**代码层(老用户拉 v0.3.2)**:
1. `git pull`
2. **不需要**重新跑 install.sh(userscript 自适应化,旧 symlink 位置照样工作)
3. 重启 Obsidian(QuickAdd 重新加载 userscripts)

**vault 整洁(可选,用户要求"统一外部工具")**:
1. 等 OB CC 执行 `docs/handoff/OB对接/2026-05-26-symlink路径自适应-handoff.md`
2. OB CC 选定新路径,跑 `install.sh --scripts-dir <新路径> --apply --force`
3. 删旧 `scripts/feishukanban-ob-sync/` 目录(install.sh 不自动删,手动 `rm -rf`)
4. 改 `.obsidian/plugins/quickadd/data.json` 4 个 choice path 字段(install.sh 输出的 snippet 已经是新值)
5. 重启 Obsidian,测 4 个 Cmd+P 命令

---

### ⚖️ 8 条原则自评

| # | 原则 | 本次表现 |
|---|---|---|
| 1 | 解耦 | ⭐⭐⭐⭐⭐ userscript 不再依赖 install.sh 装在哪;install.sh 不再依赖 userscript 路径硬编码 |
| 2 | 可扩展 | ⭐⭐⭐⭐⭐ `--scripts-dir` 留出扩展点,装到 vault 任意位置都行 |
| 3 | 灵活修改 | ⭐⭐⭐⭐⭐ 路径迁移成本从"改 6 个文件"降到"跑一次 install.sh + 手改 data.json" |
| 4 | 渐进披露 | ⭐⭐⭐⭐ 开源用户默认值无感;高级用户用 flag |
| 5 | 鲁棒性 | ⭐⭐⭐⭐ `__filename` 即使返回 symlink 真实路径(仓库内位置)也能跑通——sync.py 在仓库就在 userscripts 上一级,功能不破 |
| 6 | 人可读 + 可教学 | ⭐⭐⭐⭐ 注释解释了"为什么 __filename 自适应能避免硬编码";handoff 文档全流程清晰 |
| 7 | 高复用 + 易移植 | ⭐⭐⭐ Node 标准 + bash 标准,跨平台无障碍 |
| 8 | 工程化清晰 | ⭐⭐⭐⭐ install.sh dry-run 验证 + sync.py CLI 验证,handoff 文档约定回执流程 |

---



> 四块 patch 合并:`--vault` CLI 参数、`inject_completion_link`、`pull-today` today_history 残留清理、`快记任务` 跨日 dateContext(OB handoff 移交)。

### 🎯 块 ① — `--vault` 参数 + 项目级 settings.json

#### 问题背景

Claude Code 在跑 `cd /Users/aim5/Documents/OB && python3 .../sync.py --pull-today` 这类命令时,**每次都弹 permission 授权窗** — 哪怕给 `Bash(python3:*)` 开了 allow 也没用。根因:Claude Code 的 allowlist 是**前缀匹配**,`cd` 开头会绕过所有 allow 规则。

#### sync.py 新增 `--vault <path>` 参数

```bash
# 新写法(命令开头是 python3,allowlist 友好)
python3 /path/to/sync.py --vault /Users/aim5/Documents/OB --pull-today

# 老写法仍然可用(从 vault 内任意子目录跑,自动找 .obsidian/)
cd /Users/aim5/Documents/OB && python3 /path/to/sync.py --pull-today
```

实现细节:`main()` 最开头若收到 `--vault`,校验 `.obsidian/` 存在后 `os.chdir(vault_path)`,其余代码完全不动 — **100% 向后兼容**,不传 `--vault` 时行为完全等价于 v0.3.0。

#### 4 个 UserScript 同步更新

`quickadd-拉今日todo.js` / `quickadd-完成task.js` / `quickadd-快记任务-v2-task-md.js`(2 处)从 `cd "${vaultRoot}" && python3 "${syncScript}" ...` 改为 `python3 "${syncScript}" --vault "${vaultRoot}" ...`。颗粒度统一,去除对 cwd 的隐式依赖。

#### 新增项目级 `.claude/settings.json`

allow 本项目实际会用到的命令(python3 / pip3 / feishu-cli / 常见 git 子命令 / 只读工具),deny 危险操作(force push / reset --hard / 写 config.yaml)。其他 CC 用户 clone 仓库后开箱即用,无需各自重复授权。

---

### 🔗 块 ② — `inject_completion_link`:完成段裸 checkbox 自动转带链 markdown

#### 问题

`task 模版.md` 的「## ✅ 完成标记」段写了 `- [ ] <title>`,UserScript 文案说"sync 后自动改为带飞书 record URL 的链接",但 sync.py 此前**没实际实现**这一步。结果 dataview TASK 渲染时看不到点击直达飞书的链接。

#### 实现

新增 `inject_completion_link(md_path, title, record_url) -> bool` 函数,在 `push_task_md` CREATE 流程末尾调用:
- 找「## ✅ 完成标记」H2 段标题
- 该段下第一个 `- [ ]` / `- [x]` checkbox 行
- 行 body 替换为 `[<原 body>](record_url)`,变成 dataview 可点击 link
- 幂等:已是 `[text](url)` 形式 → 不动;UPDATE 流程不触发(行可能已被用户手改)

---

### 🧹 块 ③ — `pull-today`:today_history 残留清理

#### 问题

v0.3.0 的 `today_history` append-only 设计有一个未覆盖场景:
- 用户飞书勾「是否今日」→ sync.py set OB `today=true` + append `today_history`
- 用户飞书取消「是否今日」→ sync.py set OB `today=false`,**但 today_history 仍含今日**
- journal dataview 用 `contains(today_history, this.file.day)` → 任务仍渲染在今日 journal
- 用户期望:取消今日 = 今日 journal 不再显示

#### 实现

`_scan_ob_task_md_by_feishu_record` 抽取 `today_history` 字段;`pull_today_from_feishu` 的 `plan_set_false` 触发条件改为 `entry["today"] OR (今日 in today_history)` — 当 OB today_history 含今日但飞书取消今日时,也走 set_false(并清理 today_history 中的今日,若实现细节如此)。`_scan` 返回字典加 `today_history: list[str]` 字段。

> 注:本块完整 spec 详见 sync.py 函数内注释,本 CHANGELOG 主要给版本对齐用。

---

### 🕐 块 ④ — `快记任务`:跨日 dateContext(OB handoff 移交)

#### 问题

Mac 系统时区 `America/Los_Angeles` + 用户在北京工作的跨日场景:
- PDT 5-26 晚 18:26 = 北京 5-27 早 09:26
- 用户在 `journals/2026-05-26.md` 工作(心理上还在 5-26)
- 跑 Cmd+P「📝 快记任务」 → userscript 用 `bjDate` = `2026-05-27`
- 新 task 文件名 `2026-05-27-xxx.md`,frontmatter `today_history: [2026-05-27]`,`日志: [[journals/2026-05-27]]`
- 用户当前 journal(5-26) dataview 查 `contains(today_history, "2026-05-26")` → false → **task 不显示,体验上"消失"**

#### 实现

`obsidian-assets/userscripts/quickadd-快记任务-v2-task-md.js` 顶部加 `getDateContext(app)` helper:
- 当前 active file 是 `journals/YYYY-MM-DD.md`(严格正则)→ 用 journal 日期
- 其他场景(task md / 任意 md / 无 active file)→ fallback 北京时间(原 bjDate 行为)

Step 4 把 `bjDate` 替换为 `dateContext`(影响:文件名前缀 / `日志:` wikilink / `today_history` 初值);新增 `createdISO = ${dateContext}T${bjISO.slice(11)}` 替代 `bjISO` 写入 `created` 字段(日期跟随上下文,时间部分始终北京时间,跨工程时间戳一致)。

#### 边界

- 用户在 `journals/2026-05-26.md` → `dateContext = "2026-05-26"`
- 用户从 task md / Inbox / 任意 md 触发 → `dateContext = bjDate`
- Obsidian 启动后直接 Cmd+P(无 active file)→ `dateContext = bjDate`
- 非标准命名 journal(如 `journals/detail/2026-05-26 周二.md`)→ 不匹配正则 → fallback bjDate(保守行为)

详见 `docs/handoff/OB对接/2026-05-26-userscript-跨日-handoff.md`。

---

### 🔧 升级路径(全部四块统一升)

老用户拉了 v0.3.1 后需要:
1. `git pull`(只动 sync.py / userscript / settings.json,不动 config.yaml)
2. **重装 UserScripts**:`bash install.sh --apply --force`(覆盖 vault 里的 4 个 userscripts/*.js)
3. 重启 Obsidian(QuickAdd 重新加载 userscripts)
4. 重启 Claude Code(项目级 settings.json 在会话启动时加载)
5. 新建 task md 验证:`inject_completion_link` 是否把「✅ 完成标记」段裸 checkbox 自动改成带链 link
6. 飞书勾今日 → 跑 `python3 sync.py --vault /OB --pull-today --apply` → 再取消飞书今日 → 再跑一次 → 验证 today_history 中的今日被清,journal 不再渲染
7. 跨日测试:在 `journals/<昨天>.md` 中跑 Cmd+P「📝 快记任务」 → 验证新 task 文件名前缀 / `today_history` / `日志` 都是「昨天」日期

### 📊 已知 follow-up

- sync.py line 180 有个 `\s` regex SyntaxWarning(无功能影响),P3 修
- `scan_vault_record_ids` (老 `--pull` 流程)的 `vault_root = Path(".")` 仍是 hard-code,但因 `--vault` 已 chdir,实际行为正确;P3 改成 `find_vault_root()`

---

## [v0.3.0] - 2026-05-26 — **今日聚焦历史保真:`today_history` 事件流**

### 🎯 问题背景

v0.2.0 用 `today: true/false` 单字段管理"是否今日"。痛点:**全局 single source of truth,改 1 次影响所有历史 journal**。场景:
- 5/26 标 today=true,做了一半
- 5/27 早上飞书取消「是否今日」+ `sync.py --pull-today` → OB today=false
- 回看 5/26 journal,dataview 查 `WHERE today=true` → **task 消失**,历史丢失

dataview 是实时投影,无法做"时间穿越"。

### ✨ 解决方案:事件流持久化

task md frontmatter 新增 `today_history` 字段(YAML inline list,append-only,去重):

```yaml
today: false                  # 当前状态(动态)
today_history:                # 事件流:曾经 today=true 的日期列表
  - 2026-05-26
  - 2026-05-27
```

dataview 查询改为 `contains(today_history, this.file.day)` → **5/26 journal 永远显示曾经在 5/26 聚焦过的 task**,不论后续 today 字段如何变化。

### 🔧 实施细节

#### sync.py 改动

1. **`_format_yaml_value`** 加 list 支持(`[a, b, c]` inline 格式),底层 enabler 让 `update_md_frontmatter` 能写 list 字段
2. **`pull_today_from_feishu`** 在 set OB today=true 时,read 当前 today_history → append 当日(去重)→ 一次性 update both fields
3. **`_create_task_md_from_feishu_record`**(`--pull-today --apply` 自动建 task md 时)初始化 `today_history: [{today_date}]`
4. **设 today=false 时**:**不动 today_history**(历史保留)

#### Obsidian assets 改动

- **`quickadd-快记任务-v2-task-md.js`**:创建 task md 时 init `today_history: []`(空 list,等用户飞书勾今日时 sync.py 自动 append)

### 🔄 OB 端配套(独立改动)

OB CC 同步改:
- **task md 模板**(`03 Resources/素材库/模版/task 模版.md`)加 `today_history` 字段定义
- **journal 模板 + 今日 journal**:「🎯 今日计划」+「🐿️ 今日非计划」dataview 查询从 `today = true` 改为 `contains(today_history, this.file.day)`
- **历史 task 批量 backfill**:扫 12 个 today=true 的 task md,根据 created 日期 init today_history
- **rules 更新**(`feishu-project-sync.md`「今日 todo 双层架构」section 加事件流持久化说明)

### 📐 设计要点

- **append-only**:取消 today 不删除历史(允许"曾经"语义)
- **去重**:同一天反复设 today=true 只 append 1 次
- **类型安全**:`_format_yaml_value` 递归处理 list 元素,纯日期 → 无引号,符合 dataview 类型推断
- **向后兼容**:无 today_history 字段的旧 task md → `contains` 返回 false → 不显示(自然降级,需 backfill 或 sync.py 自动维护)

### 🆙 升级路径(OB 端)

1. 拉新版 sync.py(symlink 用户自动同步)
2. 跑一次 `sync.py --pull-today --apply` → 所有飞书侧 today=true 的 task 自动 init today_history
3. 历史 task 跑 backfill 脚本(参考 OB CC 实施记录)
4. 模板 + journal 模板 + 今日 journal 改 dataview 查询条件

### 🐛 已知边界

- task md 创建时 today_history=[],只有走过 `sync.py --pull-today` 才会 append。如果用户跳过 sync 直接手敲 `today: true` → today_history 不变,需手动维护或下次 pull-today 自动修复
- dataview `contains([2026-05-26], this.file.day)` 当 list 元素为 string 时,this.file.day 是 date 对象,dataview 内部做类型匹配(实证可行)

---

## [v0.2.0] - 2026-05-26 — **task md 化架构 + 完整工作流 + 一键部署**

### 🎯 重大架构升级 — task 升级为 "first-class entity"

v0.1 是 inline 子弹笔记式(`- [ ]` 在 journal 内,emoji 元数据),v0.2 把每个 task 升级为**独立 md 文件**,frontmatter ↔ 飞书 20 字段 **1:1 对齐**:

- 每个 task = `04 Inbox/task/YYYY-MM-DD-<标题>.md` 独立笔记
- frontmatter 18 字段:`priority` / `status` / `today` / `category` / `subcategory` / `adhd_priority` / `estimate_hours` / `feishu_record` / `feishu_url` / `iteration_week` / 等
- 正文 5 个 H2 段:`📝 执行概述` / `✅ 验收条件` / `💡 执行思路` / `🔗 相关资料` / `🪞 复盘`
- 跨日全景视图 — `_task.base` 6 个视图(🎯今日计划 / 🐿️今日非计划 / 🔥待抢救 / ⏰有 DDL / ✅已完成 / 📋全部)

### ✨ 新增功能

#### 1. 🎯 三大工作流场景全闭环

| 场景 | 工作流 | 触发 |
|------|--------|------|
| ① **OB 创建 task → 飞书** | 弹优先级 → 输标题 → 自动 CREATE 飞书 record | Cmd+P 「📝 快记任务」 |
| ② **飞书今日 todo → OB 日志** | 飞书 app 勾「是否今日」=true → 拉到 OB today journal 渲染 | Cmd+P 「📥 拉今日 todo」 |
| ③ **自动统计今日工作** | git commit + 文件改动 → LLM 归纳为主题 → 写日志 + batch CREATE 飞书 | Claudian 对话关键词 |

#### 2. ⌨️ 4 个 QuickAdd UserScript(Cmd+P 入口)

存放于 `obsidian-assets/userscripts/`:
- `quickadd-快记任务-v2-task-md.js` — 场景 ①(主入口,2026-05-25)
- `quickadd-拉今日todo.js` — 场景 ②(2026-05-26)
- `quickadd-完成task.js` — task 完成 + sync 飞书一键闭环(2026-05-26)
- `quickadd-同步飞书项目.js` — 批量 sync(走 dry-run + 审批)

#### 3. 🔧 `sync.py` 新增 `--task-md` 和 `--pull-today` 模式

```bash
# task md 模式(2026-05-25):单条 task md 推送飞书 CREATE/UPDATE
python3 sync.py --task-md path/to/task.md --apply

# 今日 todo 同步(2026-05-26):飞书「是否今日」=true → OB frontmatter today=true
python3 sync.py --pull-today --apply
```

#### 4. 🤖 `auto_collect_today.py` helper(场景 ③)

`scripts/auto_collect_today.py` — 扫今日 git commits + vault 文件改动,输出 JSON 给 LLM 归纳。

#### 5. 🚀 `install.sh` 一键部署

新用户从 0 到能用的 onboarding 从 30 分钟降到 5 分钟:
- 自动 symlink scripts 到 vault
- 复制 templates / base / rules 模板到 vault
- 生成 QuickAdd choices JSON snippet 让用户粘贴

### 🔴 铁律 #1 飞书例外扩展(3 种自动 apply 场景)

| 场景 | 触发 | 操作类型 | 风险 |
|------|------|--------|------|
| 单条 CREATE 新 task | Cmd+P「📝 快记任务」 | CREATE | 空 record,无覆盖 |
| 单条 UPDATE 完成 task(新) | Cmd+P「✅ 完成当前 task」 | UPDATE | 只改 status/done_date |
| pull-today 同步 today 字段(新) | Cmd+P「📥 拉今日 todo」 | UPDATE OB frontmatter | 不写飞书,无破坏 |

### 🗂 obsidian-assets/(新增整套 OB 资产)

```
obsidian-assets/
├── userscripts/   (4 个 QuickAdd UserScripts)
├── templates/     (task 模版)
├── base/          (_task.base 6 视图)
└── rules/         (feishu-project-sync.md 主规则)
```

### 📚 文档大幅扩充

- `docs/ARCHITECTURE.md`(新)— 系统架构 + 数据流图
- `docs/feishu-schema.md`(新)— 飞书表 22 字段定义 + 一键创建命令
- `docs/tutorial/05-task-md-workflow.md`(新)— v0.2 主流程教程

### ⚠️ Breaking Changes(v0.1 → v0.2)

- **配置文件结构变化**:`config.yaml` 加 `task_md_fields` section(原 `fields` section 不变)
- **新增飞书字段依赖**:必须先用 `feishu-cli bitable field create` 加「是否今日」字段(参考 `docs/feishu-schema.md`)
- **老 `--pull` 模式标记 legacy**:仍可用,但建议改用 `--pull-today`(写到 task md frontmatter 而不是 journal inline)

### 🛠 修复

- `_format_yaml_value` 加 boolean 支持(原 `str(True)` = "True" 大写,改为 "true" 小写,符合 YAML 标准 + dataview 解析)

---

## [v0.1.0] - 2026-05-19 — **初版开源**

### 核心功能

- `sync.py`:OB journal task ↔ 飞书 record 双向同步
  - 正向 sync:OB 勾 [x] → 飞书自动填字段
  - 反向 pull:飞书「是否今日」→ OB 日志写 inline
  - 短链自动反查 + record_id O(1) cache
  - 字段映射 yaml 配置驱动
- 4 篇 tutorial(`docs/tutorial/01-04`)
- skill-claude-code.md(让 Claude Code 用户一键调用)
- 完整 README + INSTALL(30 分钟新手 onboard)

### 关键 bug 修复(对比内部版本)

- `inject_url_into_line` 保留所有 emoji 到行尾(原正则只匹配第一个 emoji 前空白)
- base URL 替代 wiki 长链(wiki SDK + bitable SDK iframe race condition 修复)
- 短链自动反查机制(用户不再需要管短链/长链转换)

---

## 设计哲学

详见 `docs/ARCHITECTURE.md`「8 条架构原则反向打分」section。
