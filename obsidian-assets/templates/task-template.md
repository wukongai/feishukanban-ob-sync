---
# === 必填字段 ===
priority: P3                       # P0/P1/P2/P3 — 任务价值/紧急度(不再表达"计划/非计划",见 today_source)
status: todo                       # todo / doing / subdone / done / block / cancel / idea(v0.3.5 7 态)
today: false                       # 是否今日 todo(对应飞书「是否今日」字段)
                                   # 早上 sync.py --pull-today 时根据飞书侧勾选自动同步
# v0.3.6: today_source 区分"计划/非计划"(ADHD 自觉察)
# - planned:早晨 pull-today 拉来的(前一晚 / 早晨已规划)
# - unplanned:当天 Cmd+P 快记任务 + today=true 临时插入
# - 空:不在今日 / 历史 task / 手改 today=true(dataview 默认归"计划"段)
today_source:                      # planned / unplanned / 空
created: 2026-05-26T17:44:52       # ISO 8601,北京时间,无引号

# === 时间字段 ===
done_date:                         # YYYY-MM-DD,完成时回填(对应 Tasks ✅)
due:                               # YYYY-MM-DD,截止日期(对应 Tasks 📅)

# === 飞书分类(可选,有就同步)===
category:                          # 产品项目 / 杂务 / 技能工具 / 领域学习
                                   # v0.4.1 起 Cmd+P「📝 快记任务」Step 3 必选(ADHD 看板分流)
subcategory:                       # YAML list,飞书「小类」字段
                                   # v0.4.1 起:非产品项目分支(杂务/技能工具/领域学习)的二级分类,手输
                                   # 产品项目分支用 project_minor 替代(三级精细分类)
# v0.3.8 加:项目小类 — task 表 multi-select,任务内容细分类型(三级分类的最细一层)
# 例:布丁内容(子级) → 干货 / 训练营 / 课程产品 (project_minor)
#     装备配置(子级) → Codex / claudecode / 软硬件 (project_minor)
# Cmd+P 快记任务 Step 4.5 弹最近 5 条 distinct 用过
project_minor:                     # YAML list,如 [干货, 训练营]
adhd_priority:                     # 待抢救 / 有 DDL / 自由待办

# === 估时与效率 ===
estimate_hours:                    # 数字,如 0.5 / 1 / 2
actual_hours:                      # 数字,完成后回填(对应飞书「用时」number,v0.4.0 加)
efficiency:                        # 高 / 中 / 低(完成后回填)
quality:                           # 高 / 中 / 低(完成后回填,对应飞书「完成质量」select,v0.4.0 加)

# === 关联 ===
parent_project:                    # "[[<最终归属项目>]]" — 选了小类用小类名,否则用大类名
                                   # 飞书「产品项目」link 字段(只有 1 个,指向最精细 record 才能按二级看板筛选)
                                   # v0.2.2 加 / v0.3.5 澄清语义:从「大项目」改为「最终归属」
parent_subproject:                 # "[[<小类名>]]"(OB 侧 metadata,sync 不推飞书;v0.3.5 起 Cmd+P 自动填)
parent_task:                       # "[[<父 task 文件名>]]"(对应飞书「相关任务」link 双向,v0.4.0 加)
parent_inspiration:                # "[[<灵感>]]"(从灵感孵化时填)
日志: "[[journals/2026-05-26]]"

# === 同步自动回填(sync 时写入,人不手动改)===
feishu_record:                     # CREATE 后回填 recXXX
feishu_url:                        # CREATE 后回填 base 长链
# v0.3.5: iteration_week / iteration_month 改为多选 list(飞书侧字段也升级为多选)
# Cmd+P「📝 快记任务」时主动选(默认 = created 当周/当月);跨季 task 可选多个
# 旧 task 单值仍兼容(单值 = 单元素 list)
iteration_week:                    # YAML inline list,如 [26W22(5月25日-5月31日), 26W23(6月1日-6月7日)]
iteration_month:                   # YAML inline list,如 [26 年 5 月, 26 年 6 月]
completion_month:                  # 完成时根据 done_date 自动算

tags:
  - task
---

# task-template

<!-- v0.4.0(2026-05-28)H2 段顺序对齐飞书看板视图字段顺序 -->

## 👥 用户故事
<!-- 同步到飞书「用户故事」字段。"作为 X,我希望 Y,以便 Z"句式。可选,产品类 task 用 -->


## ✅ 验收条件
<!-- 同步到飞书「验收条件」字段。什么样算完成?可选 -->


## 💡 执行思路
<!-- 同步到飞书「执行思路」字段。打算怎么做?可选 -->


## 📝 执行概述
<!-- 这一段同步到飞书「执行概述」字段。简单 task 可只写一句;复杂 task 展开 -->


## 📈 执行明细
<!-- v0.6.0 加 — 同步到飞书「执行明细」子表(daily execution log)。每行 1 条 daily 记录:
     - YYYY-MM-DD | 状态 | plan=... / review=... / est=... / act=... / done=...
     · 状态(v0.6.1 起用 emoji + 大写显示,对齐 journal dataview):
         ⬜ Todo / 🔄 Doing / 🟧 SubDone / ✅ Done / 🚧 Block / ❌ cancel / 💡 Idea
       (手写小写 enum 如 `doing` 也兼容,pull-today 会自动升级到显示形式)
     · key 全可选(不写不推);同一天写多行 → 后者覆盖前者
     · 完成度(done=):最小完成 / 标准完成 / 超额完成 / 阻碍 / 未启动 -->


## 📦 交付
<!-- ⭐ 最重要字段。同步到飞书「交付」字段。完成后填:做出来什么?产出 / 文件 / 链接 / 截图 / 部署位置 等 -->


## 🔗 相关资料
<!-- 同步到飞书「相关资料」字段。链接 / 参考。可选 -->


## 🪞 复盘
<!-- 同步到飞书「复盘」字段。完成后填。可选 -->


## ✅ 完成标记
<!-- 2026-05-25 升级:dataview TASK 查询读这一行渲染 checkbox + 点击可勾选 -->
<!-- sync 后 OB CC 会顺手把 inline 替换为 `- [ ] [title](feishu_url)` 让点击跳飞书 -->
- [ ] task-template

