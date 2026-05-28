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
subcategory:                       # YAML list,如 [内容/课程产品, 自媒体]
adhd_priority:                     # 待抢救 / 有 DDL / 自由待办

# === 估时与效率 ===
estimate_hours:                    # 数字,如 0.5 / 1 / 2
efficiency:                        # 高 / 中 / 低(完成后回填)

# === 关联 ===
parent_project:                    # "[[<最终归属项目>]]" — 选了小类用小类名,否则用大类名
                                   # 飞书「产品项目」link 字段(只有 1 个,指向最精细 record 才能按二级看板筛选)
                                   # v0.2.2 加 / v0.3.5 澄清语义:从「大项目」改为「最终归属」
parent_subproject:                 # "[[<小类名>]]"(OB 侧 metadata,sync 不推飞书;v0.3.5 起 Cmd+P 自动填)
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

## 📝 执行概述
<!-- 这一段同步到飞书「执行概述」字段。简单 task 可只写一句;复杂 task 展开 -->


## ✅ 验收条件
<!-- 同步到飞书「验收条件」字段。什么样算完成?可选 -->


## 💡 执行思路
<!-- 同步到飞书「执行思路」字段。打算怎么做?可选 -->


## 🔗 相关资料
<!-- 同步到飞书「相关资料」字段。链接 / 参考。可选 -->


## 🪞 复盘
<!-- 同步到飞书「复盘」字段。完成后填。可选 -->


## ✅ 完成标记
<!-- 2026-05-25 升级:dataview TASK 查询读这一行渲染 checkbox + 点击可勾选 -->
<!-- sync 后 OB CC 会顺手把 inline 替换为 `- [ ] [title](feishu_url)` 让点击跳飞书 -->
- [ ] task-template

