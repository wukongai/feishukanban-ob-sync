# 回执:`sync.py --create-task` 非交互接口(给 zhixing-game 扫尾 SOP 用)

> **方向**:feishukanban-ob-sync → zhixing-game
> **日期**:2026-05-31(北京时间)
> **版本**:v0.7.0(待 commit / bump)
> **场景**:外部项目(zhixing-game 等)在「任务扫尾」时,**一条命令**把一个任务同时写入飞书项目看板 + Obsidian vault,不需要外部碰任何字段 schema 或 task md 模板。

---

## 1. 这是什么

新增一个**非交互 CLI 子命令** `--create-task`。

- **外部只传业务参数**(title / category / status / …),**字段映射、task md 模板、飞书 payload 全部由 sync.py 内部掌握**,外部不碰。
- 工具内部自动完成:
  1. 业务参数 → 规范 OB task md(frontmatter + H2 段,字段顺序对齐飞书看板视图)
  2. 飞书多维表 **CREATE 新 record**
  3. 回填 `feishu_record` / `feishu_url` 到 task md frontmatter
  4. 把「## ✅ 完成标记」行改成带飞书链接的 markdown link
- **时区走 config**(默认 `Asia/Shanghai`),`created` 与文件名日期都是北京时间。
- **默认 dry-run**,`--apply` 才真写(落 vault + 飞书 CREATE)。dry-run **不写 vault**(用临时文件解析,跑完即删),零污染。

实现复用了现成能力(没另起炉灶):`push_task_md`(OB md→飞书 CREATE+回填)+ `_create_task_md_from_feishu_record` 的模板骨架(数据源从飞书 row 换成外部传参)。

---

## 2. 完整 CLI 调用示例

### 2.1 dry-run(默认,先看 diff)

```bash
python3 /Users/aim5/Documents/CodingProject/feishukanban-ob-sync/sync.py \
  --create-task \
  --vault /Users/aim5/Documents/OB \
  --title "知行游戏-某任务标题" \
  --category "产品项目" \
  --status done \
  --today-source unplanned \
  --priority P2 \
  --estimate-hours 1 \
  --actual-hours 1.5 \
  --done-date 2026-05-31 \
  --description "这个任务做了什么(→ 飞书「执行概述」)" \
  --delivery "产出/文件/链接/部署位置(→ 飞书「交付」)" \
  --log-link "https://……/工作日志链接(→ 飞书「相关资料」)"
```

> 逐条解释关键参数:
> - `--create-task`:进入非交互建任务模式(不加这个不会触发)。
> - `--vault /Users/aim5/Documents/OB`:指定 OB vault 根目录。**外部项目必须传**——否则 sync.py 用 cwd 推 vault,从 zhixing-game 目录跑会找不到。传了就内部 `chdir`,无需 `cd /OB && …`(避免 Claude Code 权限风暴)。
> - 其余 `--xxx`:纯业务参数,见第 3 节清单。
> - **不加 `--apply`** = dry-run:打印「生成的 task md 全文」+「飞书 payload」给你看,**不落盘、不建 record**。

### 2.2 apply(确认无误后真写)

把上面命令**末尾加 `--apply`** 即可:

```bash
python3 …/sync.py --create-task --vault /Users/aim5/Documents/OB \
  --title "…" --category "…" --status done … \
  --apply
```

真写后会:落 `04 Inbox/task/YYYY-MM-DD-<标题>.md` + 飞书 CREATE + 回填 record_id/url。

### 2.3 `--json`(给扫尾 SOP 捕获机器可读结果)

加 `--json`,末尾会多打**一行 JSON**,其余人读输出照常打:

```bash
python3 …/sync.py --create-task --vault /OB --title "…" … --apply --json
```

apply 成功输出(最后一行):

```json
{"success": true, "action": "CREATE", "record_id": "recXXXXXXXX", "url": "https://……?record=recXXXXXXXX", "task_md": "/Users/aim5/Documents/OB/04 Inbox/task/2026-05-31-….md", "error": null}
```

dry-run + `--json` 输出:

```json
{"success": true, "dry_run": true, "action": "CREATE", "task_md": "/…/04 Inbox/task/2026-05-31-….md"}
```

失败(如 title 缺失 / 目标文件已存在 / 飞书 CREATE 失败):

```json
{"success": false, "error": "……", "task_md": "/…"}
```

> **扫尾 SOP 取值建议**:apply + `--json`,取最后一行 `jq` 解析,`success==true` 则记下 `record_id` / `url` 写回 zhixing-game 自己的归档;`success==false` 则把 `error` 抛给人工。退出码:成功 `0`,失败 `1`(可直接 `if`/`||` 判断)。

---

## 3. 参数清单

| 参数 | 必填 | 类型/取值 | 落到哪(飞书字段 / OB) | 说明 |
|------|:---:|------|------|------|
| `--create-task` | ✅ | flag | — | 触发本模式 |
| `--vault` | ✅(外部) | 路径 | — | OB vault 根目录,内部 chdir |
| `--title` | ✅ | 文本 | 飞书「任务标题」+ OB 文件名/H1 | 文件名非法字符 `/ \ * ? : " < > \|` 自动替换为 `_` |
| `--category` | 可选 | 文本(单选) | 飞书「大类」 | 如 `产品项目` / `杂务` / `技能工具` / `领域学习` |
| `--status` | 可选 | enum | 飞书「执行状态」 | `todo`/`doing`/`subdone`/`done`/`block`/`cancel`/`idea`;**整个 task 状态,由人/项目决定**。扫尾通常 `doing`,整体 `done` 用户自己定。默认 `todo` |
| `--today-source` | 可选 | `planned`/`unplanned` | OB `today_source`(**不推飞书**) | 非空 → task md `today: true` → 飞书「是否今日」=true;空 → `today: false` |
| `--priority` | 可选 | `P0`/`P1`/`P2`/`P3` | 飞书「价值优先级」 | 纯价值维度,不含时间含义 |
| `--estimate-hours` | 可选 | 数字 | 飞书「估时」(number) | 整个 task 估时 |
| `--actual-hours` | 可选 | 数字 | 飞书「用时」(number) | 整个 task 累计用时(通常整体完成才填) |
| `--done-date` | 可选 | `YYYY-MM-DD` | 飞书「完成时间」+ 自动 derive「执行迭代周/月」 | **整个 task 完成才传** |
| `--description` | 可选 | 文本 | 飞书「执行概述」 | 写进 `## 📝 执行概述` 段。简要说明,人易读 |
| `--delivery` | 可选 | 文本 | 飞书「交付」⭐ | 写进 `## 📦 交付` 段。**重点放交付文档链接** |
| `--log-link` | 可选 | 文本/URL | 飞书「相关资料」 | 写进 `## 🔗 相关资料` 段,放工作日志链接 |
| `--detail`(可重复) | 可选 | 明细行 | 飞书「执行明细」**子表** + OB `## 📈 执行明细` 段 | `YYYY-MM-DD \| 状态 \| 计划=… / 估时=… / 用时=… / 完成度=… / 复盘=…`,见 §4.7 |
| `--user-story` | 可选 | 文本 | 飞书「用户故事」+ OB `## 👥 用户故事` | "作为 X,我希望 Y,以便 Z" |
| `--acceptance` | 可选 | 文本 | 飞书「验收条件」+ OB `## ✅ 验收条件` | 什么样算完成 |
| `--thinking` | 可选 | 文本 | 飞书「执行思路」+ OB `## 💡 执行思路` | 打算怎么做 |
| `--retrospective` | 可选 | 文本 | 飞书「复盘」+ OB `## 🪞 复盘` | 完成/扫尾后的反思 |
| `--apply` | 可选 | flag | — | 不加 = dry-run;加 = 真写 |
| `--json` | 可选 | flag | — | 末尾输出机器可读 JSON |

> **未支持的字段**(`subcategory` / `project_minor` / `parent_project` / `parent_task` / `iteration_*` / `efficiency` / `quality` 等)在生成的 task md 里**留空**,不推飞书。外部「扫尾」场景用不到;如将来要补,在 sync.py 加对应 `--xxx` 即可(不影响现有调用)。
>
> **正文 H2 段**:9 个标准段(用户故事/验收条件/执行思路/执行概述/执行明细/交付/相关资料/复盘/完成标记)**全部保留骨架**,对齐飞书看板字段顺序;传了对应参数的段填值,没传的段标题独占一行干净留空(待人后补)。

---

## 4. 行为说明 / 注意事项

1. **目标路径**:`<vault>/04 Inbox/task/YYYY-MM-DD-<安全标题>.md`,日期为**北京时间今天**(非 done_date)。
2. **防覆盖(铁律 #2)**:目标文件已存在 → **直接报错退出(exit 1)**,不覆盖。提示用 `--task-md <path> --apply` 更新已有 task。避免外部重复 CREATE 造成飞书重复 record。
3. **时区**:`created` 时间戳 + 文件名日期走 `config.behavior.timezone`(默认 `Asia/Shanghai`)。所以**北京时间过 0 点后,文件名日期会是新一天**(已和用户确认:此行为正确,跟其他命令一致)。
4. **dry-run 零污染**:dry-run 用系统临时文件解析跑 payload diff,跑完即删,**不在 vault 留任何东西**。
5. **apply 失败兜底**:若文件已落盘但飞书 CREATE 失败 → task md 仍是合法文件,可事后 `--task-md "<path>" --apply` 重推(stderr 会提示路径)。
6. **delivery 不受 status 限制**:task md 模式下 `交付` 字段无论 status 是否完成都会同步(走 `task_md_fields.delivery` 配置),跟 journal inline 模式的 D 混合是两套独立逻辑。
7. **执行明细 `--detail`(为 OB Dataview)**:
   - 每天扫尾**补一条** `--detail`(可重复),格式 `YYYY-MM-DD | 状态 | 计划=… / 估时=… / 用时=… / 完成度=… / 复盘=…`。
   - 状态:`Todo/Doing/SubDone/Done/Block/Cancel/Idea`;完成度:`最小完成/标准完成/超额完成/阻碍/未启动`。
   - key 大小写 / emoji / 英文 key(plan/est/act/done/review)都兼容,sync.py 自动规范化为中文 key + 状态首字母大写,写进 OB `## 📈 执行明细` 段(Dataview 数据源)。
   - **`--apply` 时**:先 CREATE 主 record 拿到 record_id,再推执行明细子表(一次完成)。
   - **dry-run 时**:只能确认明细被正确**解析**(打印 `📈 执行明细(N 条)`),看不到子表 diff(主 record 还没建)——这是 `push_task_md` 固有逻辑,非 bug。
8. **状态解耦(重要)**:主 task `--status` = 整个 task 状态(由人/项目决定,扫尾通常 `doing`);执行明细行的状态 = 当天那段的状态(当天做完 = `Done`)。**两者独立**——当天 `Done` 不代表整个 task `done`,整体 `done` 用户自己决定。
9. **task md 简约(v0.7.0 用户拍板)**:正文**保留全部 9 个标准 H2 段骨架**(对齐飞书看板字段顺序),**简约 = 去掉啰嗦的 HTML 注释,像人手写日志**;传了参数的段填值,没传的段标题独占一行干净留空(不塞占位文字)。交付段放文档链接为重点。frontmatter 仍保留 task 标准全字段(OB base/dataview schema 依赖)。

---

## 5. 给 zhixing-game 扫尾 SOP 的集成模板(伪代码)

```bash
# 在 zhixing-game 任务扫尾时调一次(扫尾 = 当天做了一段,整体未必完成):
SYNC=/Users/aim5/Documents/CodingProject/feishukanban-ob-sync/sync.py
VAULT=/Users/aim5/Documents/OB
TODAY=$(date +%F)

# 执行明细行:当天那段做完 → 状态 done(独立于整体 task status)
DETAIL="$TODAY | done | 计划=$PLAN / 估时=$EST / 用时=$ACT / 完成度=$COMPLETION / 复盘=$REVIEW"

# Step 1:先 dry-run 给人/日志看 diff(可选,自动化可跳)
python3 "$SYNC" --create-task --vault "$VAULT" \
  --title "$TITLE" --category "$CATEGORY" --status doing \
  --priority "$PRIORITY" --estimate-hours "$TASK_EST" \
  --description "$DESC" --delivery "$DELIVERY" --log-link "$LOG_URL" \
  --detail "$DETAIL"

# Step 2:确认后真写 + 取结果(同一条命令末尾加 --apply --json,读完整 stdout 最后一行)
RESULT=$(python3 "$SYNC" --create-task --vault "$VAULT" \
  --title "$TITLE" --category "$CATEGORY" --status doing \
  --priority "$PRIORITY" --estimate-hours "$TASK_EST" \
  --description "$DESC" --delivery "$DELIVERY" --log-link "$LOG_URL" \
  --detail "$DETAIL" \
  --apply --json | tail -1)

# Step 3:解析 record_id / url 写回 zhixing-game 归档
echo "$RESULT" | jq -r 'if .success then "✅ \(.record_id) \(.url)" else "❌ \(.error)" end'

# 注:整个 task 真完成那次,改 --status done 并加 --done-date "$TODAY" --actual-hours "$TOTAL"
```

---

## 6. 反向回执(zhixing-game CC 回填)

> zhixing-game 侧接入完成后,在此追加:接入位置 / 实际调用形态 / 遇到的坑 / 是否需要补字段。

- [ ] 已接入扫尾 SOP 的位置:____
- [ ] 实测调用是否成功(record_id 示例):____
- [ ] 需要 sync.py 补的字段:____
