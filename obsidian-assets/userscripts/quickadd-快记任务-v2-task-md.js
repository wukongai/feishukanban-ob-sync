/**
 * QuickAdd UserScript: 📝 快记任务 v2(task md 化版)
 *
 * 触发方式: Cmd+P → 搜「快记任务」 → 回车
 *
 * 行为(v0.3.5 - 2026-05-27 飞书看板筛选友好升级):
 * 0. Step 0:batch 调 sync.py --quickadd-options 拿活跃项目 / 最近 5 月 / 最近 5 周(一次性,~1s)
 * 1. 优先级(🔺 P0 / ⏫ P1 / 🔼 P2 / 🔽 P3)
 * 2. ADHD 优先级(🚨 待抢救 / ⏰ 有 DDL / 🌱 自由待办 / ❌ 跳过)
 * 3. 大类(飞书产品项目表「活跃=true 且 父产品=空」)
 * 4. 小类(飞书产品项目表「活跃=true 且 父产品=选中大类」)
 * 5. 截止日期 DDL(preset:今天/明天/本周末/下周末/本月底/手输/跳过)
 * 6. 执行月(飞书最近 5 个 enum,多选循环 / 默认=created 当月)
 * 7. 执行周(飞书最近 5 个 enum,多选循环 / 默认=created 当周)
 * 8. 是否今日(📥 需求池 / ⭐ 今日)
 * 9. 标题输入
 * 10. 创建 task md + 调 sync.py --task-md --apply 同步飞书
 *
 * 日期上下文(v0.3.1 跨日支持):
 *    - 当前打开 journal(`journals/YYYY-MM-DD.md`)→ 用 journal 日期作为文件名前缀 / today_history / 日志字段
 *    - 其他场景 → fallback 北京时间(原行为)
 *
 * ⚠️ 重要:task 默认 today: false → 不显示在今日 journal「🎯 今日计划」段
 *    想"今天就做这条" → 飞书 app 勾「是否今日」=true + Mac 跑 `sync.py --pull-today --apply`
 *
 * ⚠️ 铁律 #1 例外:
 *    单条 CREATE 自动跑 sync.py --apply(跳过 dry-run + 用户审批)。
 *    UPDATE / 批量同步仍走 Cmd+P → 「🎯 同步今日 task 到飞书」5 步 SOP。
 *
 * 关联文件:
 *  - sync.py task md 模式:userscripts/ 上一级的 sync.py(v0.3.4 起 install.sh sed 注入绝对路径)
 *  - task 模板:03 Resources/素材库/模版/task 模版.md
 *  - base 视图:04 Inbox/task/_task.base
 */

// 算 dateContext:优先用当前打开 journal 日期(跨日工作友好),fallback 北京时间
function getDateContext(app) {
  const active = app.workspace.getActiveFile();
  if (active && active.path.startsWith("journals/")
      && /^\d{4}-\d{2}-\d{2}\.md$/.test(active.name)) {
    return active.name.slice(0, 10);
  }
  return new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10);
}

// ISO 8601 周编号(与 Python isocalendar 一致)
function isoWeek(date) {
  const d = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  const dayNum = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const weekNum = Math.ceil(((d - yearStart) / 86400000 + 1) / 7);
  return { year: d.getUTCFullYear(), week: weekNum };
}

// 多选循环 helper(执行月/周复用)
// recentList 空 → 直接返回 [defaultValue](不弹窗)
// 用户选「⏭ 用默认」→ 返回 [defaultValue]
// 用户选具体值后弹「✓ 完成 / 加更多」→ 返回 [...selected]
// 用户 Esc → 返回 null(调用方处理)
async function selectMultiOrDefault(quickAddApi, recentList, defaultValue, label, emoji) {
  if (!recentList || recentList.length === 0) {
    return [defaultValue];
  }
  let selected = [];
  while (true) {
    const remaining = recentList.filter(x => !selected.includes(x));
    if (remaining.length === 0) break;
    const firstOption = selected.length === 0
      ? `⏭ 用默认(${defaultValue})`
      : `✓ 完成,已选 [${selected.join(", ")}]`;
    const firstValue = selected.length === 0 ? "__DEFAULT__" : "__DONE__";
    const options = [firstOption, ...remaining.map(x => `${emoji} ${x}`)];
    const values = [firstValue, ...remaining];
    const pick = await quickAddApi.suggester(options, values);
    if (pick === undefined) return null;
    if (pick === "__DEFAULT__") return [defaultValue];
    if (pick === "__DONE__") break;
    selected.push(pick);
  }
  return selected.length > 0 ? selected : [defaultValue];
}

module.exports = async function (params) {
  const { app, obsidian, quickAddApi } = params;
  const { Notice } = obsidian;

  try {
    // ============ Step 0: batch 拉飞书选项 ============
    // v0.3.5: 一次 sync.py --quickadd-options 拿 大类 / 小类 / 月 / 周 4 类
    // 失败降级:菜单仍能跑,但相关步骤显示「⚠️ 飞书查询失败」+ 跳过
    const { exec } = require("child_process");
    const util = require("util");
    const execAsync = util.promisify(exec);

    const vaultRoot = app.vault.adapter.basePath || app.vault.adapter.getBasePath();
    // v0.3.4: install.sh 装的时候 sed 替换占位符为 sync.py 绝对路径
    const syncScript = "__SYNC_PY_ABS_PATH__";
    const userPaths = [
      `${process.env.HOME}/.local/bin`,
      "/usr/local/bin",
      "/opt/homebrew/bin",
    ];
    const execEnv = {
      ...process.env,
      PATH: `${userPaths.join(":")}:${process.env.PATH || ""}`,
      // v0.3.3: 强制北京时区,sync.py 的 datetime.now() 不再受 shell TZ=PDT 影响
      TZ: "Asia/Shanghai",
    };

    let qopts = {
      active_top_level: [],
      subprojects_by_parent: {},
      recent_months: [],
      recent_weeks: [],
    };
    try {
      const optsCmd = `python3 "${syncScript.replace(/"/g, '\\"')}" --vault "${vaultRoot.replace(/"/g, '\\"')}" --quickadd-options`;
      console.log("[快记任务 v2] optsCmd:", optsCmd);
      const { stdout: optsStdout } = await execAsync(optsCmd, { timeout: 15000, env: execEnv });
      const lines = optsStdout.trim().split("\n").filter(Boolean);
      const jsonLine = lines.reverse().find(l => l.trim().startsWith("{"));
      if (jsonLine) qopts = JSON.parse(jsonLine);
      console.log("[快记任务 v2] qopts:", {
        top_n: qopts.active_top_level?.length || 0,
        sub_parents: Object.keys(qopts.subprojects_by_parent || {}).length,
        months: qopts.recent_months,
        weeks: qopts.recent_weeks,
      });
    } catch (e) {
      console.warn("[快记任务 v2] quickadd-options 失败,降级:", e);
      new Notice(
        "⚠️ 飞书选项拉取失败,大类/小类/月/周菜单将跳过(降级运行)\n详情看 Console",
        4000
      );
    }

    // ============ Step 1: 优先级 ============
    const priorityChoice = await quickAddApi.suggester(
      ["🔺 P0  紧急重要", "⏫ P1  本周必做", "🔼 P2  有空就做", "🔽 P3  非计划"],
      ["P0", "P1", "P2", "P3"]
    );
    if (!priorityChoice) {
      new Notice("❌ 已取消", 3000);
      return;
    }

    // ============ Step 2: ADHD 优先级 ============
    const adhdChoice = await quickAddApi.suggester(
      ["🚨 待抢救", "⏰ 有 DDL", "🌱 自由待办", "❌ 跳过 / 不填"],
      ["待抢救", "有 DDL", "自由待办", null]
    );
    if (adhdChoice === undefined) {
      new Notice("❌ 已取消", 3000);
      return;
    }
    console.log("[快记任务 v2] adhd:", adhdChoice);

    // ============ Step 3: 大类(parent_project)============
    // 数据源:飞书产品项目表 where 活跃=true AND 父产品=空(v0.3.5)
    // 数据空 → 跳过此步,不弹窗
    let chosenParentName = null;
    let chosenParentRecordId = null;
    let titlePrefix = "";

    if (qopts.active_top_level && qopts.active_top_level.length > 0) {
      const topNames = qopts.active_top_level.map(p => p.name);
      const topOptions = [
        "❌ 跳过 / 不归类(临时小事)",
        ...topNames.map(n => `📁 ${n}`),
      ];
      const topValues = ["__SKIP__", ...topNames];
      const topPick = await quickAddApi.suggester(topOptions, topValues);
      if (topPick === undefined) {
        new Notice("❌ 已取消", 3000);
        return;
      }
      if (topPick !== "__SKIP__") {
        chosenParentName = topPick;
        const found = qopts.active_top_level.find(p => p.name === topPick);
        chosenParentRecordId = found?.record_id || null;
      }
      console.log("[快记任务 v2] parent:", chosenParentName, "(", chosenParentRecordId, ")");
    } else {
      console.log("[快记任务 v2] active_top_level 空,跳过大类菜单");
    }

    // ============ Step 4: 小类(parent_subproject)============
    // 数据源:qopts.subprojects_by_parent[选中大类 record_id]
    // 大类没选 / 该大类无活跃小类 → 跳过此步
    let chosenSubName = null;
    if (chosenParentRecordId && qopts.subprojects_by_parent) {
      const subs = qopts.subprojects_by_parent[chosenParentRecordId] || [];
      if (subs.length > 0) {
        const subNames = subs.map(s => s.name);
        const subOptions = [
          `❌ 跳过(只填大类「${chosenParentName}」)`,
          ...subNames.map(n => `📂 ${n}`),
        ];
        const subValues = ["__SKIP__", ...subNames];
        const subPick = await quickAddApi.suggester(subOptions, subValues);
        if (subPick === undefined) {
          new Notice("❌ 已取消", 3000);
          return;
        }
        if (subPick !== "__SKIP__") {
          chosenSubName = subPick;
          titlePrefix = `【${subPick}】`;
        } else {
          titlePrefix = `【${chosenParentName}】`;
        }
      } else {
        titlePrefix = `【${chosenParentName}】`;
      }
    } else if (chosenParentName) {
      titlePrefix = `【${chosenParentName}】`;
    }
    console.log("[快记任务 v2] subproject:", chosenSubName, "/ titlePrefix:", titlePrefix);

    // ============ Step 5: 截止日期 DDL ============
    // preset:今天/明天/本周末/下周末/本月底/手输 + 跳过
    const nowBJ = new Date(Date.now() + 8 * 3600 * 1000);
    const toISODate = d => d.toISOString().slice(0, 10);
    const addDays = (d, n) => {
      const r = new Date(d);
      r.setUTCDate(r.getUTCDate() + n);
      return r;
    };
    const dayOfWeek = nowBJ.getUTCDay(); // 0=Sun 6=Sat
    // 本周末:本周日(若今天周日,daysToSun=0 → 今天就是)
    const daysToThisSun = (7 - dayOfWeek) % 7;
    const thisWeekend = daysToThisSun === 0 ? nowBJ : addDays(nowBJ, daysToThisSun);
    const nextWeekend = addDays(thisWeekend, 7);
    const lastDayOfMonth = new Date(Date.UTC(nowBJ.getUTCFullYear(), nowBJ.getUTCMonth() + 1, 0));

    const dueOptions = [
      "❌ 跳过 / 无 DDL",
      `⏰ 今天(${toISODate(nowBJ)})`,
      `📅 明天(${toISODate(addDays(nowBJ, 1))})`,
      `🌅 本周末(${toISODate(thisWeekend)})`,
      `🗓 下周末(${toISODate(nextWeekend)})`,
      `🌙 本月底(${toISODate(lastDayOfMonth)})`,
      "📝 手输 YYYY-MM-DD",
    ];
    const dueValues = [
      "__SKIP__",
      toISODate(nowBJ),
      toISODate(addDays(nowBJ, 1)),
      toISODate(thisWeekend),
      toISODate(nextWeekend),
      toISODate(lastDayOfMonth),
      "__INPUT__",
    ];
    const duePick = await quickAddApi.suggester(dueOptions, dueValues);
    if (duePick === undefined) {
      new Notice("❌ 已取消", 3000);
      return;
    }
    let dueDate = null;
    if (duePick === "__INPUT__") {
      const manual = await quickAddApi.inputPrompt("截止日期 (YYYY-MM-DD)", "", toISODate(nowBJ));
      if (manual && /^\d{4}-\d{2}-\d{2}$/.test(manual.trim())) {
        dueDate = manual.trim();
      } else if (manual) {
        new Notice("⚠️ 格式不对(需 YYYY-MM-DD),DDL 跳过", 4000);
      }
    } else if (duePick !== "__SKIP__") {
      dueDate = duePick;
    }
    // ADHD="有 DDL" 但 DDL 没填 → 警告但继续
    if (adhdChoice === "有 DDL" && !dueDate) {
      new Notice("⚠️ 选了「有 DDL」却没设截止日期,继续创建", 4000);
    }
    console.log("[快记任务 v2] due:", dueDate);

    // ============ Step 6: 执行月 ============
    const defaultMonth = `${nowBJ.getUTCFullYear() % 100} 年 ${nowBJ.getUTCMonth() + 1} 月`;
    const selectedMonths = await selectMultiOrDefault(
      quickAddApi, qopts.recent_months, defaultMonth, "执行月", "📆"
    );
    if (selectedMonths === null) {
      new Notice("❌ 已取消", 3000);
      return;
    }
    console.log("[快记任务 v2] months:", selectedMonths);

    // ============ Step 7: 执行周 ============
    const iso = isoWeek(nowBJ);
    const defaultWeekPrefix = `${iso.year % 100}W${String(iso.week).padStart(2, "0")}`;
    // 飞书侧的 option name 可能是 "26W22(5月25日-5月31日)",优先复用完整字符串
    const matchedRecentWeek = (qopts.recent_weeks || []).find(w => w.startsWith(defaultWeekPrefix));
    const defaultWeek = matchedRecentWeek || defaultWeekPrefix;
    const selectedWeeks = await selectMultiOrDefault(
      quickAddApi, qopts.recent_weeks, defaultWeek, "执行周", "📅"
    );
    if (selectedWeeks === null) {
      new Notice("❌ 已取消", 3000);
      return;
    }
    console.log("[快记任务 v2] weeks:", selectedWeeks);

    // ============ Step 8: 是否今日 ============
    const isToday = await quickAddApi.suggester(
      ["📥 进需求池(默认,后续在飞书勾今日)", "⭐ 今日(立即排进今日 journal)"],
      [false, true]
    );
    if (isToday === undefined) {
      new Notice("❌ 已取消", 3000);
      return;
    }

    // ============ Step 9: 标题 ============
    const title = await quickAddApi.inputPrompt("任务标题(简短;后续可加详情)");
    if (!title || !title.trim()) {
      new Notice("❌ 标题为空,已取消", 3000);
      return;
    }
    const titleTrimmed = `${titlePrefix}${title.trim()}`;

    // ============ Step 10: 计算日期 + 路径 ============
    const bjISO = new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 19);
    const dateContext = getDateContext(app);
    const createdISO = `${dateContext}T${bjISO.slice(11)}`;
    const safeTitle = titleTrimmed.replace(/[\\\/:*?"<>|]/g, "_");
    const filename = `${dateContext}-${safeTitle}.md`;
    const taskPath = `04 Inbox/task/${filename}`;
    const journalPath = `journals/${dateContext}`;

    if (app.vault.getAbstractFileByPath(taskPath)) {
      new Notice(`❌ 文件已存在: ${filename}\n请改名后再试`, 5000);
      return;
    }

    // ============ Step 11: 生成 task md 内容 ============
    // parent_project 语义(沿用 v0.2.4):**最终归属** — 选了小类用小类名,否则用大类名
    // 飞书侧只有 1 个「产品项目」link 字段,必须指向最精细 record 才能按二级看板筛选
    // parent_subproject 是 OB 侧 metadata(可空),给 OB base 视图分层显示用,不推飞书
    const finalParentName = chosenSubName || chosenParentName;
    const parentProjectLine = finalParentName
      ? `parent_project: "[[${finalParentName}]]"`
      : `parent_project:`;
    const parentSubLine = chosenSubName
      ? `parent_subproject: "[[${chosenSubName}]]"`
      : `parent_subproject:`;
    const adhdLine = adhdChoice ? `adhd_priority: ${adhdChoice}` : `adhd_priority:`;
    const dueLine = dueDate ? `due: ${dueDate}` : `due:`;
    const monthsLine = selectedMonths.length > 0
      ? `iteration_month: [${selectedMonths.join(", ")}]`
      : `iteration_month:`;
    const weeksLine = selectedWeeks.length > 0
      ? `iteration_week: [${selectedWeeks.join(", ")}]`
      : `iteration_week:`;
    // today_history 事件流:today=true 时立即 init 为 [dateContext];今日 journal 才能查到
    const todayHistoryInit = isToday ? `[${dateContext}]` : `[]`;
    // v0.3.6: today_source 区分"计划/非计划"(ADHD 自觉察用)
    // 此 userscript 触发 = 当天 Cmd+P 临时建 → unplanned
    // pull-today 流程 (sync.py) 设 today=true 时 → planned(早晨规划好拉的)
    // today=false 时 today_source 留空(不在今日)
    const todaySourceLine = isToday ? `today_source: unplanned` : `today_source:`;

    const content = `---
priority: ${priorityChoice}
status: todo
today: ${isToday}
today_history: ${todayHistoryInit}
${todaySourceLine}
created: ${createdISO}
${dueLine}
done_date:
category:
subcategory:
${adhdLine}
estimate_hours:
efficiency:
acceptance:
thinking:
resources:
retrospective:
${parentProjectLine}
${parentSubLine}
parent_inspiration:
日志: "[[${journalPath}]]"
feishu_record:
feishu_url:
${weeksLine}
${monthsLine}
completion_month:
tags:
  - task
---

# ${titleTrimmed}

## 📝 执行概述


## ✅ 验收条件


## 💡 执行思路


## 🔗 相关资料


## 🪞 复盘


## ✅ 完成标记
<!-- dataview TASK 查询读这一行渲染 checkbox + 点击跳飞书(sync 成功后会自动改为 markdown link) -->
- [ ] ${titleTrimmed}
`;

    // ============ Step 12: 创建 task md ============
    await app.vault.create(taskPath, content);
    const todayBanner = isToday
      ? "⭐ 今日 task(today: true,会进今日 journal「🎯 今日计划」段)"
      : "📥 进需求池(today: false,飞书勾今日 + pull-today 才进 journal)";
    new Notice(
      `✅ 已创建 task: ${filename}\n${todayBanner}\n🔄 正在同步飞书...(预计 5-10 秒)`,
      5000
    );

    // ============ Step 13: 调 sync.py --task-md --apply ============
    // 铁律 #1 例外:单条 CREATE 自动 apply,无覆盖风险
    const escapedTaskPath = `${vaultRoot}/${taskPath}`.replace(/"/g, '\\"');
    const syncCmd = `python3 "${syncScript.replace(/"/g, '\\"')}" --vault "${vaultRoot.replace(/"/g, '\\"')}" --task-md "${escapedTaskPath}" --apply`;
    console.log("[快记任务 v2] syncCmd:", syncCmd);

    let recordId = null;
    let syncOK = false;
    try {
      const { stdout, stderr } = await execAsync(syncCmd, { timeout: 60000, env: execEnv });
      console.log("[快记任务 v2] sync stdout:", stdout);
      if (stderr) console.warn("[快记任务 v2] sync stderr:", stderr);

      const recMatch = stdout.match(/record_id:\s*(rec[a-zA-Z0-9]+)/);
      if (recMatch) {
        recordId = recMatch[1];
        syncOK = true;
      }
    } catch (e) {
      console.error("[快记任务 v2] sync 失败:", e);
      new Notice(
        `⚠️ 飞书同步失败(task md 已建,稍后手动跑同步):\n${e.message || e}`,
        10000
      );
    }

    if (syncOK) {
      const syncBanner = isToday
        ? "⭐ 飞书「是否今日」已同步勾选 → 跑 pull-today 可写入今日 journal"
        : "📥 task 在需求池;后续在飞书勾「是否今日」+ pull-today 才进 journal";
      new Notice(
        `✅ 飞书同步成功!\nrecord_id: ${recordId}\n💾 task md frontmatter 已更新\n${syncBanner}`,
        5000
      );
    }

    console.log("[快记任务 v2] 全流程完成");
  } catch (e) {
    console.error("[快记任务 v2] 顶层异常:", e);
    new Notice(
      `❌ 脚本异常: ${e.message}\n请打开 Console (Cmd+Opt+I) 看详情`,
      10000
    );
  }
};
