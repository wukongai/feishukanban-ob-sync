# Tutorial 04: 字段映射定制(改 yaml 加新字段)

> 🎯 **目标**:理解 config.yaml 的字段映射 schema,学会加新字段映射(零代码改动)。读完你能解释:enum 怎么映射 / datetime 怎么处理 / derive_template 怎么用。
>
> ⏱️ **预计阅读**:10 分钟

---

## 场景

你的飞书表加了一个新字段「客户标签」(单选,选项:VIP / 普通 / 内部),想让 sync.py 自动从 OB task 行的 `#vip` 或 `#内部` tag 映射过去。

或者你想:
- 加一个「估时」字段映射 OB 的 `⏳ 30m`
- 加一个「项目代号」字段映射 task 标题里的 `【布丁】`/`【ACME】`
- 改个字段名(飞书表叫"完成时间",你想叫"结束时间"?)

所有这些都通过改 `config.yaml` 完成,**不用动 sync.py 一行代码**。

---

## config.yaml 结构总览

```yaml
feishu:
  tenant_subdomain: <your-tenant>
  base_token: <your-base-token>
  table_id: <your-table-id>

field_map:
  status:             # OB 信号 → 飞书字段(每个映射 1 个 key)
    field_id: <fld-xxx>
    field_name: 执行状态
    field_type: multi_select
    map:
      x: Done
      blank: Todo
      "/": Doing
      "-": Block

  completed_time:
    field_id: <fld-xxx>
    field_name: 完成时间
    field_type: datetime

  iteration_week:
    field_id: <fld-xxx>
    field_name: 执行迭代周
    field_type: single_select
    derive_template: "{YY}W{NN:02d}"   # 从 ✅ 完成日推导

  iteration_month:
    field_id: <fld-xxx>
    field_name: 执行迭代月
    field_type: single_select
    derive_template: "{YY} 年 {M} 月"

  delivery:
    field_id: <fld-xxx>
    field_name: 交付
    field_type: text
    extract:
      inline_emoji: "📎"
      callout_types: [note, info]
      backlink_field: delivery_for

behavior:
  auto_create_enum: false   # 飞书表 enum 不存在时:false=静默跳过 / true=未来增强
```

---

## 字段类型支持

| field_type | 飞书侧 | sync.py 处理 | 例子 |
|------------|--------|------------|------|
| `text` | 单行文本 | 直接 string | 任务标题 |
| `multi_select` | 多选 | wrap 成 list | 状态 ["Done"] |
| `single_select` | 单选 | string + enum 匹配 | 优先级 "P1" |
| `datetime` | 日期 + 时间 | ms 时间戳 | 完成时间 1716000000000 |
| `date` | 仅日期 | ms 时间戳(零点) | 截止日期 |
| `number` | 数字 | int / float | 估时 30 |
| `url` | 链接 | plain string | 关联文档 URL |

---

## 实战 1:加新字段(估时映射)

### Step 1: 在飞书表加字段

飞书后台 → 你的多维表 → 加新字段「估时」类型选「数字」。

### Step 2: 拿 field_id

```bash
feishu-cli bitable field list --base-token <base_token> --table-id <table_id> | grep 估时
# 输出:
# field_id: fld_xxx_estimate, field_name: 估时, type: number
```

### Step 3: 改 sync.py 解析逻辑(可选)

如果 OB task 行用 `⏳ 30m` 表示 30 分钟估时,你需要在 sync.py `parse_task_line()` 加正则。

**但是**:如果只是简单映射(从某 frontmatter 字段或 emoji 抓数),可以**靠现有解析**,直接配 config.yaml:

```yaml
field_map:
  estimate:
    field_id: fld_xxx_estimate
    field_name: 估时
    field_type: number
    # source: parse_task 已抽出的 estimate 字段(假设 sync.py 已支持)
```

> ⚠️ **真要加全新解析逻辑**(如 ⏳ emoji)需要改 sync.py。但**改 yaml 配映射** vs **改代码加新数据源** 是两件事。yaml 配映射 = 0 代码改动。

### Step 4: 跑 dry-run 验证

```bash
python3 ./sync.py "journals/2026-05-19.md"
```

```
fields payload:
  任务标题: "xxx"
  执行状态: ["Done"]
  估时: 30                ← 新字段已映射
```

---

## 实战 2:derive_template(自动推导字段)

「执行迭代周」字段不来自 OB task 直接信号,而是**从 ✅ 完成日推导**:

```yaml
iteration_week:
  field_id: <fld-xxx>
  field_name: 执行迭代周
  field_type: single_select
  derive_template: "{YY}W{NN:02d}"   # {YY}=2 位年 {NN}=ISO 周
```

完成日 `2026-05-19` → ISO calendar 显示 2026 第 21 周 → 模板渲染 `26W21` → 飞书 enum 选项匹配。

**支持的模板变量**:

| 变量 | 含义 | 例子 |
|------|------|------|
| `{YYYY}` | 4 位年 | 2026 |
| `{YY}` | 2 位年 | 26 |
| `{M}` | 月(1-12) | 5 |
| `{MM}` | 2 位月 | 05 |
| `{D}` | 日(1-31) | 19 |
| `{DD}` | 2 位日 | 19 |
| `{NN}` | ISO 周(1-53) | 21 |
| `{NN:02d}` | 2 位 ISO 周 | 21 |
| `{Q}` | 季度(1-4) | 2 |

### enum 匹配过程

1. sync.py 用 `derive_template` 渲染候选词(如 `26W21`)
2. 调 `feishu-cli bitable field search-options --field-id <fld> --query 26W21`
3. cli 返回 fuzzy match 的多个 options
4. sync.py 遍历找第一个 `query in option.name` 的(子串校验防误匹)
5. 找不到 → **静默跳过**这个字段(不阻断其他字段)

### ⚠️ ISO 周陷阱

**必须用 `datetime.isocalendar().year` 而非 `dt.year`** — 2026-01-01 落在 ISO 2025 第 53 周,候选词应为 `25W53`(非 `26W53`)。sync.py 已处理,但写新 derive 模板时要意识到这点。

---

## 实战 3:status enum 自定义(改飞书侧选项名)

飞书表的「执行状态」选项你想用中文:`完成` / `待办` / `进行中` / `阻塞`。

改 config:

```yaml
status:
  field_id: <fld-xxx>
  field_name: 执行状态
  field_type: multi_select
  map:
    x: 完成
    blank: 待办
    "/": 进行中
    "-": 阻塞
```

⚠️ **前提**:飞书后台的「执行状态」字段 enum 选项**必须先建好**:`完成` / `待办` / `进行中` / `阻塞`。否则 sync 报 `code=800010701`。

---

## 实战 4:reverse map(反向 pull 用)

反向 pull(`--pull`)需要**反向**映射:飞书字段值 → OB 状态字符。

config:

```yaml
status:
  field_id: <fld-xxx>
  field_name: 执行状态
  field_type: multi_select
  map:        # 正向
    x: Done
    blank: Todo
    "/": Doing
    "-": Block
  reverse_map:  # 反向(可选,sync.py 默认从 map 自动推导)
    Done: x
    Todo: blank
    Doing: "/"
    Block: "-"
    Cancel: "-"   # 飞书特有的"Cancel"状态 → OB 用 [-]
    Idea: blank   # 飞书"Idea"状态 → OB 用 [ ]
```

**自动推导**:大多数场景不用写 `reverse_map`,sync.py 会从 `map` 反向构造。**仅当**飞书侧有 OB 没有的额外 enum(如 Cancel / Idea)需要落到现有 OB 字符时,才显式写 `reverse_map`。

---

## 实战 5:禁用某个字段(临时关掉)

不删配置,只想临时关:

```yaml
status:
  enabled: false   # ← 加这行
  field_id: <fld-xxx>
  field_name: 执行状态
  ...
```

dry-run 输出会显示 `执行状态: SKIPPED (enabled: false)`,字段不参与 sync。

---

## extract 模块:复杂解析配置

`delivery` 字段的 extract 配置:

```yaml
delivery:
  field_id: <fld-xxx>
  field_name: 交付
  field_type: text
  extract:
    inline_emoji: "📎"             # A 路径:task 行内 📎 后的 wikilink
    callout_types: [note, info]     # B 路径:task 紧跟下一行的 callout
    backlink_field: delivery_for    # C 路径:任意笔记 frontmatter 反向链接
```

完整 A/B/C 三路扫描详见 [docs/skill-claude-code.md](../skill-claude-code.md) 「交付物同步」段。

---

## 全局 behavior 配置

```yaml
behavior:
  auto_create_enum: false       # enum 不存在时静默跳过(未来增强:自动建)
  todo_write_required: true     # AI skill 模式下强制 TodoWrite
  apply_requires_approval: true # 任何 --apply 前必须用户审 dry-run

  # 反向 pull
  pull_filter_field: 是否今日   # 默认 filter 飞书字段名
  pull_filter_value: true       # 默认 filter 值
  pull_title_match_chars: 10    # 标题查重前缀字符数

  # 交付物
  delivery_doc_sync_enabled: true  # 启用飞书云文档同步
  delivery_append_mode: true       # 保留原话备注
```

---

## 常见疑问

### Q1: 改完 config.yaml 需要重启 sync 吗?

不用。sync.py 每次启动时读 config.yaml,改完直接跑就生效。

### Q2: config.yaml 我能放在哪?

默认 sync.py 同目录。也可以 `--config /path/to/my-config.yaml` 显式指定。

### Q3: 多个项目共用一个 vault,要不要多个 config?

可以:
- `config-projects.yaml` 对应"项目管理"表
- `config-personal.yaml` 对应"个人事务"表
- 跑时 `--config config-projects.yaml`

每个 config 对应不同 base_token / table_id / field_map。

### Q4: enum 选项很多,我能自动列出所有可能值吗?

```bash
feishu-cli bitable field get --base-token <base_token> --table-id <table_id> --field-id <fld-xxx>
```

输出含 `property.options[]` 完整 enum 列表。把这些写到 config 注释里方便对照。

### Q5: field_id 永久不变吗?

是的。**即使字段重命名,field_id 永久保留**。所以 config 写 field_id 比写 field_name 更稳。

---

## 流程总结

```
飞书表加新字段
    ↓
feishu-cli bitable field list 拿 field_id
    ↓
config.yaml 加映射
    ↓
dry-run 验证 payload 正确
    ↓
apply 真实写入
    ↓
[无需改 sync.py 代码]
```

---

## 下一步

- 📖 [Tutorial 01: 基础正向 sync](./01-basic-push-sync.md)
- 📖 [Tutorial 02: 短链自动反查](./02-short-link-auto-lookup.md)
- 📖 [Tutorial 03: 反向 pull](./03-reverse-pull.md)
- 📖 [docs/skill-claude-code.md](../skill-claude-code.md) — Claude Code skill 集成
