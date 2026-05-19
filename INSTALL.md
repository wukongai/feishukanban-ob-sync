# 安装指南

> 🎯 **目标**:新手 30 分钟从 0 跑通第一次 sync。
> 跟做完这个文档,你能完成:OB 日志里勾对勾 → 跑 sync → 飞书后台看到字段被自动更新。

---

## 系统要求

| 项 | 要求 | 验证命令 |
|---|------|---------|
| OS | macOS / Linux(Windows 用 WSL2) | `uname -a` |
| Python | ≥ 3.9 | `python3 --version` |
| Git | ≥ 2.x | `git --version` |
| 网络 | 能访问 feishu.cn(企业版改对应域名) | `curl -sI https://feishu.cn` |
| 飞书账号 | 已加入企业 + 多维表读写权限 | 浏览器打开飞书后台试试 |

---

## Step 1: 装 feishu-cli

> 这是飞书官方的 CLI 工具,本仓库的 sync.py 通过 feishu-cli 调用飞书 API(不直接调,避免 SDK 维护成本)。

### macOS

```bash
brew install feishu-cli
```

### Linux / 其他

```bash
# 用 Go 安装(需要 Go ≥ 1.21)
go install github.com/larksuite/feishu-cli@latest

# 或下载 release binary
curl -sL https://github.com/larksuite/feishu-cli/releases/latest/download/feishu-cli-linux-amd64 -o /usr/local/bin/feishu-cli
chmod +x /usr/local/bin/feishu-cli
```

### 验证

```bash
feishu-cli --version
# 期望输出:feishu-cli v1.22.0+ (本仓库依赖 v3 API,v1.22.0 是最低版本)
```

⚠️ **如果你的版本 < v1.22.0**:请升级,旧版有 v1→v3 breaking changes 会导致 sync 静默失败。详见 [docs/design/known-gotchas.md](./docs/design/known-gotchas.md)。

---

## Step 2: 装 Python 依赖

本仓库**只用 Python 标准库 + PyYAML**,依赖极简:

```bash
# 检查 pyyaml 是否已装(macOS 系统自带)
python3 -c "import yaml; print(yaml.__version__)"
# 期望输出:5.4.x 或更高

# 如未装
pip3 install pyyaml
```

---

## Step 3: OAuth 登录飞书

> sync.py 用 **User Access Token**(不是 Bot Token),走 OAuth Device Flow,无需配置回调 URL。

```bash
feishu-cli auth login --scope "base:record:retrieve base:record:update base:record:create base:record:delete base:field:search"
```

执行后:
1. 终端会显示一个 8 位 device code + 一个浏览器 URL
2. 浏览器打开 URL → 登录飞书账号 → 输入 device code → 确认授权
3. 终端显示 `✅ Login successful`,token 已保存到 `~/.feishu-cli/token.json`

**Token 有效期**:通常 1 年+,过期会自动 refresh,不用频繁登录。

---

## Step 4: 克隆本仓库

```bash
git clone https://github.com/wukongai/feishukanban-ob-sync.git
cd feishukanban-ob-sync
```

文件结构(关键文件):

```
feishukanban-ob-sync/
├── sync.py                 主脚本
├── config.example.yaml     脱敏配置模板 ← 你要复制成 config.yaml
├── .gitignore              已排除 config.yaml(真 token 不会被 commit)
├── README.md
├── INSTALL.md              ← 你正在读
└── docs/                   完整文档 + tutorial
```

---

## Step 5: cp 配置模板

```bash
cp config.example.yaml config.yaml
```

打开 `config.yaml`,把所有 `<your-xxx>` 占位符替换成你的真值。**有 7 个机密字段**(下一步详解)。

---

## Step 6: 填 7 个机密字段(关键步骤)

> 这一步是最容易卡住的,每个字段都说清楚去哪拿。

### 6.1 `tenant_subdomain` —— 你的飞书企业子域名

```yaml
feishu:
  tenant_subdomain: <your-tenant>    # → 改成 abc123 之类的
```

**拿值方法**:浏览器打开飞书 → 看 URL `https://xxxxx.feishu.cn/...` → `xxxxx` 就是你的 tenant_subdomain。

> 个人版飞书 = `f.feishu.cn` 或 `feishu.cn`(没子域);企业版有自己的子域。

### 6.2 `base_token` —— 你要 sync 的多维表 base_token

```yaml
feishu:
  base_token: <your-base-token>    # → 改成 27 位左右的字符
```

**拿值方法**:浏览器打开你的多维表 → URL 长这样:

```
https://xxx.feishu.cn/base/Vy8ub...?table=tbl...&view=vew...
                       ^^^^^^^^^^^^
                       这部分就是 base_token
```

或者你的多维表挂在「知识空间(wiki)」下,URL 是 `wiki/xxx?table=...`,那个 xxx 是 wiki_node_token,需要再用 cli 转一下:

```bash
feishu-cli wiki node get --token <wiki_node_token>
# 输出里 obj_token 字段就是 base_token
```

### 6.3 `table_id` —— 表 id(tbl 开头)

```yaml
feishu:
  table_id: <your-table-id>    # → 改成 tblXXXXXXXXXX
```

**拿值方法**:同一个 URL,`table=tblXXXXX` 那段就是。

### 6.4-6.7 `field_id` 系列 —— 字段 id(fld 开头)

```yaml
field_map:
  status:
    field_id: <your-fld-id>     # 执行状态字段
  iteration_week:
    field_id: <your-fld-id>     # 执行迭代周字段
  iteration_month:
    field_id: <your-fld-id>     # 执行迭代月字段
  priority:
    field_id: <your-fld-id>     # 价值优先级字段(可选)
```

**拿值方法**:跑 cli 列出所有字段:

```bash
feishu-cli bitable field list --base-token <base_token> --table-id <table_id>
```

输出会列出所有字段的 `field_id` + `field_name`,对照 `field_name` 找对应 id 填进去。

---

## Step 7: 验证安装

```bash
python3 sync.py --help
```

期望看到 sync.py 的命令行帮助。如果报 `ModuleNotFoundError: No module named 'yaml'`,回到 Step 2 装 pyyaml。

---

## Step 8: 第一次跑(dry-run + apply)

### 8.1 准备一个测试 task

在你的 Obsidian vault 找一个 journal 文件(或新建一个),加一行 task:

```markdown
- [x] 【测试】feishukanban-ob-sync 首次 sync 验证 🔺 ➕ 2026-05-19 ✅ 2026-05-19
```

> 重点:`[x]` 已完成 + 有 `✅ YYYY-MM-DD` 完成日,这样 sync 会触发 CREATE 一个新 record(没飞书链接 = CREATE,有链接 = UPDATE)。

### 8.2 dry-run(无副作用,看会做什么)

```bash
python3 sync.py "/path/to/your/journal.md" --only-completed
```

期望输出类似:

```
--- Task 1: 【测试】feishukanban-ob-sync 首次 sync 验证
    🆕 无飞书链接 → 将创建新 record
⏳ 调 cli 拉全表 record 建标题索引(查重用)... ✅ 共 N 条 record, M 个独立标题
    ✅ 标题不重复,准备创建
    fields payload:
      执行状态: ["Done"]
      完成时间: 1716000000000
      ...

📊 完成: 1 [新建] / 0 [更新] / 0 [跳过] / 0 [失败]
```

⚠️ **检查重点**:
- `fields payload` 里的字段名和你的飞书表字段名**完全一致**(空格 / 大小写)
- `tags`、`enum 选项` 等如果有的话,看是否能匹配
- 任何 ❌ 错误必须先修(改 config 或改 task 行)

### 8.3 apply(真实写入飞书)

```bash
python3 sync.py "/path/to/your/journal.md" --only-completed --apply
```

执行后:
1. cli 写入 1 条新 record
2. sync.py 自动 Edit markdown 在 task 行插入 base URL:
   ```markdown
   - [x] [【测试】feishukanban-ob-sync 首次 sync 验证](https://xxx.feishu.cn/base/<base_token>?table=<tbl>&view=<view>&record=recXXX) 🔺 ➕ 2026-05-19 ✅ 2026-05-19
   ```

### 8.4 飞书后台验证

打开飞书多维表 → 找到刚才创建的那条 record → 检查:
- 任务标题 ✅
- 执行状态 = Done ✅
- 完成时间 = 2026-05-19 ✅

---

## Step 9: 删除测试数据 + 收尾

```bash
# 删测试 record(从 Step 8.3 拿 recXXX)
feishu-cli bitable record delete --base-token <base_token> --table-id <table_id> --record-id recXXX
```

恭喜!你完成了第一次 sync 🎉。

---

## 常见问题

### Q1: `feishu-cli auth login` scope 错误

```
code=99991672: 应用未获取所需的用户授权
```

**修复**:你的 scope 不全。重新登录加 scope:

```bash
feishu-cli auth login --scope "base:record:retrieve base:record:update base:record:create base:record:delete base:field:search"
```

### Q2: `code=800010701: Cell value does not match any supported shape`

**原因**:字段值格式不对。最常见:
- URL 字段传了 `{text, link}` 包装对象(v1 API 格式),v3 必须 plain string
- 单选/多选字段传了 enum 之外的值

**修复**:看 sync.py dry-run 输出的 fields payload,对照飞书后台字段定义,确认格式。

### Q3: dry-run 显示 "执行迭代周" enum 未命中

**原因**:`config.yaml` 里 `iteration_week.derive_template` 生成的字符串(如 `26W20`)在飞书表的"执行迭代周"单选字段里没有这个 enum 选项。

**修复**:去飞书后台手动添加 enum 选项,或者改 derive_template 模板对齐你后台已有的写法。

### Q4: 反向 `--pull` 模糊匹配把不同 task 错误升级

**修复**:dry-run 必审升级列表,如有假阳性,加 `--exclude-record <rec_id1>,<rec_id2>` 跳过这几条。

### Q5: 跑 sync 报 `git: not a git repository`

**原因**:sync.py 不依赖 git,但如果你的 vault 不在 git 仓库下,某些 vault root 检测逻辑会 fallback。

**修复**:确认你跑 sync.py 时 cwd 在你的 vault root(含 `.obsidian/` 目录),或者把 vault 路径作为参数显式传。

---

## 下一步

- 📖 阅读 [docs/tutorial/01-basic-push-sync.md](./docs/tutorial/01-basic-push-sync.md) 理解正向 sync 完整流程
- 🔄 试试反向 pull → [docs/tutorial/03-reverse-pull.md](./docs/tutorial/03-reverse-pull.md)
- 🎨 定制字段映射 → [docs/tutorial/04-field-mapping-customization.md](./docs/tutorial/04-field-mapping-customization.md)
- 🤖 Claude Code 用户 → [docs/skill-claude-code.md](./docs/skill-claude-code.md) 集成成 skill
