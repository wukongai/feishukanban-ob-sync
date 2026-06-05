/**
 * QuickAdd UserScript: 📝 快记任务 v2(task md 化版)
 *
 * 触发方式: Cmd+P → 搜「快记任务」 → 回车
 *
 * 行为(v0.4.2 state machine + v0.6.4-6 优先级/today_source 语义清洗 — priority 纯价值维度):
 * 0. Step 0:batch 调 sync.py --quickadd-options 拿活跃项目 / 最近 5 月 / 最近 5 周 / 最近 5 项目小类
 * 1. 优先级(🔺 P0 / ⏫ P1 / 🔼 P2 / 🔽 P3)
 * 2. ADHD 优先级(🚨 待抢救 / ⏰ 有 DDL / 🌱 自由待办 / ❌ 跳过)
 * 3. 业务大类(📦 产品项目 / 🪣 杂务 / 🔧 技能工具 / 📚 领域学习)
 *    └ 选「产品项目」走 3a/3b/3c;选其他三类走 3d
 * 3a. 产品项目一级(飞书产品项目表「活跃=true 且 父产品=空」)— 仅产品项目分支
 * 3b. 产品项目子级(飞书产品项目表「活跃=true 且 父产品=选中一级」)— 仅产品项目分支
 * 3c. 项目小类(飞书 task 表「项目小类」字段最近 5 条 distinct)— 仅产品项目分支
 * 3d. 小类手输(可选,逗号分隔,如「财务, 家务」)— 仅非产品项目分支
 * 4. 截止日期 DDL(preset:今天/明天/本周末/下周末/本月底/手输/跳过)
 * 5. 执行月(飞书最近 5 个 enum,多选循环 / 默认=created 当月)
 * 6. 执行周(飞书最近 5 个 enum,多选循环 / 默认=created 当周)
 * 7. 是否今日 + today_source(📥 需求池 / ⭐ 今日·计划 / 🌀 今日·非计划)— v0.6.5 加 3 选 1
 * 8. 执行状态(默认 Todo / Doing / SubDone / Done / Block / cancel / Idea)
 * 9. 标题输入
 * 10. 创建 task md + 调 sync.py --task-md --apply 同步飞书
 *
 * v0.4.2 新增「⬅ 回上一步」机制:
 *  - 每个 suggester 步骤顶部加「⬅ 回上一步」选项 → 跳回上一步重选(Step 1 没有,因为没有上一步)
 *  - inputPrompt 类(标题 / DDL 手输 / subcategory 手输)输入单字符 `^` 表示回上一步
 *  - Esc 仍是「整体取消」语义(保持原行为)
 *  - 多选循环(月/周)只在首次进入(还没选任何值)时支持后退;选了 ≥1 个后只能 Esc(避免撤销栈复杂度)
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

// v0.3.9: 始终用北京时间(回退 v0.3.1 块 ④)
function getDateContext(app) {
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

// v0.4.2 state machine sentinels
const BACK = "__BACK__";       // step fn 返回此值 = 回上一步
const CANCEL = "__CANCEL__";   // step fn 返回此值 = 整体取消(Esc / 标题空)
const SKIPPED = "__SKIPPED__"; // v0.7.12: step fn 返回此值 = silent skip(没向用户弹 UI,BACK 时透过)

// suggester 包装:第一项可选加「⬅ 回上一步」
// canBack=false → 不加(用于 Step 1 priority,没有上一步)
async function pickWithBack(quickAddApi, options, values, canBack) {
  const opts = canBack ? ["⬅ 回上一步", ...options] : options;
  const vals = canBack ? [BACK, ...values] : values;
  const pick = await quickAddApi.suggester(opts, vals);
  if (pick === undefined) return CANCEL;
  return pick;   // 可能是 BACK,也可能是具体值
}

// inputPrompt 包装:输入单字符 `^` 表示回上一步
async function inputWithBack(quickAddApi, label, placeholder, defaultValue) {
  const tail = "(输入 ^ 回上一步)";
  const fullLabel = label.endsWith(tail) ? label : `${label} ${tail}`;
  const raw = await quickAddApi.inputPrompt(fullLabel, placeholder || "", defaultValue || "");
  if (raw === undefined || raw === null) return CANCEL;
  if (raw.trim() === "^") return BACK;
  return raw;
}

// 多选循环 helper(执行月/周 复用),v0.4.2 加 back 支持
// recentList 空 → 直接返回 [defaultValue](不弹窗;若 defaultValue=null → 返回 [])
// defaultValue=null → 首项只显示「❌ 跳过 / 不填」(可选字段语义)
// defaultValue=<具体值> → 首项同时显示「⏭ 用默认(<值>)」+「❌ 跳过 / 不填」(v0.7.11 加跳过)
//
// v0.4.2 back 语义:
//   - 首次进入(还没选任何值)→ 顶部加「⬅ 回上一步」,选了 → 返回 BACK
//   - 选了 ≥1 个值后 → 不再支持后退(避免撤销栈复杂度)
async function selectMultiOrDefault(quickAddApi, recentList, defaultValue, label, emoji) {
  if (!recentList || recentList.length === 0) {
    return defaultValue === null ? [] : [defaultValue];
  }
  let selected = [];
  while (true) {
    const remaining = recentList.filter(x => !selected.includes(x));
    if (remaining.length === 0) break;

    const opts = [];
    const vals = [];
    if (selected.length === 0) {
      // 首次进入:顶部「⬅ 回上一步」+「⏭ 用默认」(有 default 时)+「❌ 跳过 / 不填」
      opts.push("⬅ 回上一步");
      vals.push(BACK);
      if (defaultValue !== null) {
        opts.push(`⏭ 用默认(${defaultValue})`);
        vals.push("__DEFAULT__");
      }
      opts.push(`❌ 跳过 / 不填(${label})`);
      vals.push("__SKIP__");
    } else {
      // 已选 ≥1 个:首项变完成
      opts.push(`✓ 完成,已选 [${selected.join(", ")}]`);
      vals.push("__DONE__");
    }
    // 剩余 enum 选项
    remaining.forEach(x => {
      opts.push(`${emoji} ${x}`);
      vals.push(x);
    });

    const pick = await quickAddApi.suggester(opts, vals);
    if (pick === undefined) return CANCEL;
    if (pick === BACK) return BACK;
    if (pick === "__DEFAULT__") return [defaultValue];
    if (pick === "__SKIP__") return [];
    if (pick === "__DONE__") break;
    selected.push(pick);
  }
  if (selected.length > 0) return selected;
  return defaultValue === null ? [] : [defaultValue];
}

// ============================================================
// State machine 主体
// ============================================================

// step 列表(扁平,分支用 isStepActive 跳过)
const STEPS = [
  "priority",          // 0
  "adhd",              // 1
  "category",          // 2
  "parentLevel1",      // 3a 仅产品项目
  "parentLevel2",      // 3b 仅产品项目
  "projectMinor",      // 3c 仅产品项目
  "subcategoryManual", // 3d 仅非产品项目
  "due",               // 4
  "months",            // 5
  "weeks",             // 6
  "isToday",           // 7
  "status",            // 8
  "title",             // 9
];

// 当前 state 下该 step 是否激活
function isStepActive(stepName, state) {
  if (["parentLevel1", "parentLevel2", "projectMinor"].includes(stepName)) {
    return state.category === "产品项目";
  }
  if (stepName === "subcategoryManual") {
    return state.category && state.category !== "产品项目";
  }
  return true;
}

// 给定 idx,找上一个 active 且**非 silent-skipped** step 的 idx;找不到返回 -1
// v0.7.12: 加 silentSkipped 参数,BACK 跳转时跳过那些 silent skip 的 step(没弹 UI 的)
//          避免"用户在 stepA 按 BACK → 跳回 silent-skipped step → 立即又被推到 stepA"的死循环
function findPrevActive(idx, state, silentSkipped) {
  let j = idx - 1;
  while (j >= 0) {
    const stepName = STEPS[j];
    if (isStepActive(stepName, state) && !(silentSkipped && silentSkipped.has(stepName))) {
      return j;
    }
    j--;
  }
  return -1;
}

// ============================================================
// 各 step 实现(每个返回 BACK / CANCEL / null=继续,直接改 state)
// ============================================================

async function stepPriority(state, qa, ctx) {
  const pick = await pickWithBack(qa,
    ["🔺 P0", "⏫ P1", "🔼 P2", "🔽 P3"],
    ["P0", "P1", "P2", "P3"],
    ctx.canBack
  );
  if (pick === CANCEL || pick === BACK) return pick;
  state.priority = pick;
  return null;
}

async function stepAdhd(state, qa, ctx) {
  const pick = await pickWithBack(qa,
    ["🚨 待抢救", "⏰ 有 DDL", "🌱 自由待办", "❌ 跳过 / 不填"],
    ["待抢救", "有 DDL", "自由待办", "__SKIP__"],
    ctx.canBack
  );
  if (pick === CANCEL || pick === BACK) return pick;
  state.adhd = pick === "__SKIP__" ? null : pick;
  return null;
}

async function stepCategory(state, qa, ctx) {
  const pick = await pickWithBack(qa,
    ["📦 产品项目", "🪣 杂务", "🔧 技能工具", "📚 领域学习"],
    ["产品项目", "杂务", "技能工具", "领域学习"],
    ctx.canBack
  );
  if (pick === CANCEL || pick === BACK) return pick;
  // 切换分支时清掉对侧 state(避免脏数据 — 用户回上一步改大类时)
  if (state.category !== pick) {
    state.parentName = null;
    state.parentRecordId = null;
    state.subName = null;
    state.projectMinor = [];
    state.subcategoryList = [];
    state.titlePrefix = "";
  }
  state.category = pick;
  return null;
}

async function stepParentLevel1(state, qa, ctx) {
  if (!ctx.qopts.active_top_level || ctx.qopts.active_top_level.length === 0) {
    state.parentName = null;
    state.parentRecordId = null;
    return SKIPPED;  // v0.7.12: 没弹 UI,BACK 时透过
  }
  const topNames = ctx.qopts.active_top_level.map(p => p.name);
  const pick = await pickWithBack(qa,
    ["❌ 跳过 / 不归类(临时小事)", ...topNames.map(n => `📁 ${n}`)],
    ["__SKIP__", ...topNames],
    ctx.canBack
  );
  if (pick === CANCEL || pick === BACK) return pick;
  if (pick === "__SKIP__") {
    state.parentName = null;
    state.parentRecordId = null;
  } else {
    state.parentName = pick;
    const found = ctx.qopts.active_top_level.find(p => p.name === pick);
    state.parentRecordId = found?.record_id || null;
  }
  return null;
}

async function stepParentLevel2(state, qa, ctx) {
  if (!state.parentRecordId || !ctx.qopts.subprojects_by_parent) {
    if (state.parentName) state.titlePrefix = `【${state.parentName}】`;
    return SKIPPED;  // v0.7.12
  }
  const subs = ctx.qopts.subprojects_by_parent[state.parentRecordId] || [];
  if (subs.length === 0) {
    state.titlePrefix = `【${state.parentName}】`;
    return SKIPPED;  // v0.7.12
  }
  const subNames = subs.map(s => s.name);
  const pick = await pickWithBack(qa,
    [`❌ 跳过(只填一级「${state.parentName}」)`, ...subNames.map(n => `📂 ${n}`)],
    ["__SKIP__", ...subNames],
    ctx.canBack
  );
  if (pick === CANCEL || pick === BACK) return pick;
  if (pick === "__SKIP__") {
    state.subName = null;
    state.titlePrefix = `【${state.parentName}】`;
  } else {
    state.subName = pick;
    state.titlePrefix = `【${pick}】`;
  }
  return null;
}

async function stepProjectMinor(state, qa, ctx) {
  if (!ctx.qopts.recent_project_minor || ctx.qopts.recent_project_minor.length === 0) {
    state.projectMinor = [];
    return SKIPPED;  // v0.7.12
  }
  const pick = await pickWithBack(qa,
    ["❌ 跳过 / 不填(项目小类)", ...ctx.qopts.recent_project_minor.map(x => `🏷 ${x}`)],
    ["__SKIP__", ...ctx.qopts.recent_project_minor],
    ctx.canBack
  );
  if (pick === CANCEL || pick === BACK) return pick;
  state.projectMinor = pick === "__SKIP__" ? [] : [pick];
  return null;
}

async function stepSubcategoryManual(state, qa, ctx) {
  // input 类 step,用 inputWithBack;canBack 永远 true(在 step 2 category 之后)
  const raw = await inputWithBack(qa,
    `「${state.category}」小类(可选,逗号分隔,如:财务, 家务;留空跳过)`,
    "", ""
  );
  if (raw === CANCEL || raw === BACK) return raw;
  if (raw && raw.trim()) {
    state.subcategoryList = raw
      .split(/[,，]/)
      .map(s => s.trim())
      .filter(Boolean);
  } else {
    state.subcategoryList = [];
  }
  if (state.subcategoryList.length > 0) {
    // v0.7.11 改 `/` → `-`:`/` 被 sanitize 转 `_` → 文件名 _ 进 dataview wikilink 触发 markdown emphasis 配对 → wikilink 渲染失败
    state.titlePrefix = `【${state.category}-${state.subcategoryList.join("-")}】`;
  } else {
    state.titlePrefix = `【${state.category}】`;
  }
  return null;
}

async function stepDue(state, qa, ctx) {
  const nowBJ = new Date(Date.now() + 8 * 3600 * 1000);
  const toISODate = d => d.toISOString().slice(0, 10);
  const addDays = (d, n) => {
    const r = new Date(d);
    r.setUTCDate(r.getUTCDate() + n);
    return r;
  };
  const dayOfWeek = nowBJ.getUTCDay();
  const daysToThisSun = (7 - dayOfWeek) % 7;
  const thisWeekend = daysToThisSun === 0 ? nowBJ : addDays(nowBJ, daysToThisSun);
  const nextWeekend = addDays(thisWeekend, 7);
  const lastDayOfMonth = new Date(Date.UTC(nowBJ.getUTCFullYear(), nowBJ.getUTCMonth() + 1, 0));

  // 内部 loop:手输 ^ 退回 DDL 选项菜单(局部);DDL 选 ⬅ 退到上一 step
  while (true) {
    const pick = await pickWithBack(qa,
      [
        "❌ 跳过 / 无 DDL",
        `⏰ 今天(${toISODate(nowBJ)})`,
        `📅 明天(${toISODate(addDays(nowBJ, 1))})`,
        `🌅 本周末(${toISODate(thisWeekend)})`,
        `🗓 下周末(${toISODate(nextWeekend)})`,
        `🌙 本月底(${toISODate(lastDayOfMonth)})`,
        "📝 手输 YYYY-MM-DD",
      ],
      [
        "__SKIP__",
        toISODate(nowBJ),
        toISODate(addDays(nowBJ, 1)),
        toISODate(thisWeekend),
        toISODate(nextWeekend),
        toISODate(lastDayOfMonth),
        "__INPUT__",
      ],
      ctx.canBack
    );
    if (pick === CANCEL || pick === BACK) return pick;
    if (pick === "__SKIP__") {
      state.due = null;
      break;
    }
    if (pick === "__INPUT__") {
      const manual = await inputWithBack(qa,
        "截止日期 (YYYY-MM-DD,输入 ^ 回 DDL 选项)",
        "", toISODate(nowBJ)
      );
      if (manual === CANCEL) return CANCEL;
      if (manual === BACK) continue;     // 回 DDL 选项菜单(局部 loop)
      if (/^\d{4}-\d{2}-\d{2}$/.test(manual.trim())) {
        state.due = manual.trim();
        break;
      }
      new Notice("⚠️ 格式不对(需 YYYY-MM-DD),请重试 / 或选 preset", 4000);
      continue;
    }
    state.due = pick;
    break;
  }
  if (state.adhd === "有 DDL" && !state.due) {
    new Notice("⚠️ 选了「有 DDL」却没设截止日期,继续创建", 4000);
  }
  return null;
}

async function stepMonths(state, qa, ctx) {
  const nowBJ = new Date(Date.now() + 8 * 3600 * 1000);
  const defaultMonth = `${nowBJ.getUTCFullYear() % 100} 年 ${nowBJ.getUTCMonth() + 1} 月`;
  // v0.7.12: qopts 空时 silent skip — 让 wizard 知道 BACK 时透过这步
  if (!ctx.qopts.recent_months || ctx.qopts.recent_months.length === 0) {
    state.months = [defaultMonth];
    return SKIPPED;
  }
  const sel = await selectMultiOrDefault(qa, ctx.qopts.recent_months, defaultMonth, "执行月", "📆");
  if (sel === CANCEL || sel === BACK) return sel;
  state.months = sel;
  return null;
}

async function stepWeeks(state, qa, ctx) {
  const nowBJ = new Date(Date.now() + 8 * 3600 * 1000);
  const iso = isoWeek(nowBJ);
  const defaultWeekPrefix = `${iso.year % 100}W${String(iso.week).padStart(2, "0")}`;
  const matchedRecentWeek = (ctx.qopts.recent_weeks || []).find(w => w.startsWith(defaultWeekPrefix));
  const defaultWeek = matchedRecentWeek || defaultWeekPrefix;
  // v0.7.12: qopts 空时 silent skip
  if (!ctx.qopts.recent_weeks || ctx.qopts.recent_weeks.length === 0) {
    state.weeks = [defaultWeek];
    return SKIPPED;
  }
  const sel = await selectMultiOrDefault(qa, ctx.qopts.recent_weeks, defaultWeek, "执行周", "📅");
  if (sel === CANCEL || sel === BACK) return sel;
  state.weeks = sel;
  return null;
}

async function stepIsToday(state, qa, ctx) {
  // v0.6.5:3 选 1,补登 today_source 字段语义(原硬编码 unplanned 是 bug,丢失计划/非计划分流)
  // v0.7.12:dogfood 实证 QuickAdd suggester 偶发 idx 映射偏移(返回的字符串不是用户实际点的项)
  //   终极方案:① suggester 主选(用户要的视觉)+ displays === actualItems 双保险
  //             ② inputPrompt y/n 二次确认 — 弹框上显示「你刚选的是 XX」,用户必看清,错就 n 重选
  //             两段式确认 → 即使 QuickAdd 内部 idx 抖动,用户也不会被锁定到错选项
  while (true) {
    const optsBack = ctx.canBack ? ["⬅ 回上一步"] : [];
    const opts = [
      ...optsBack,
      "📥 进需求池(默认,后续在飞书勾今日)",
      "⭐ 今日 · 计划(前一晚 / 早晨规划好的)",
      "🌀 今日 · 非计划(临时插入,ADHD 自觉察用)",
    ];
    const pick = await qa.suggester(opts, opts);
    console.warn("[快记任务 v2] stepIsToday raw pick:", JSON.stringify(pick));
    if (pick === undefined || pick === null) return CANCEL;
    if (typeof pick !== "string") return CANCEL;
    if (pick.startsWith("⬅")) return BACK;

    // emoji 前缀解析
    let summary, isToday, todaySource;
    if (pick.startsWith("📥")) {
      summary = "📥 进需求池"; isToday = false; todaySource = null;
    } else if (pick.startsWith("⭐")) {
      summary = "⭐ 今日 · 计划"; isToday = true; todaySource = "planned";
    } else if (pick.startsWith("🌀")) {
      summary = "🌀 今日 · 非计划"; isToday = true; todaySource = "unplanned";
    } else {
      summary = "📥 进需求池(fallback)"; isToday = false; todaySource = null;
    }

    // 二次确认:inputPrompt y/n 绕开 suggester idx 映射风险
    const confirm = await qa.inputPrompt(
      `你刚选的是: ${summary}\n\n` +
      `✅ 回车 / 输 y = 确认\n` +
      `🔁 输 n = 重选`,
      "y", "y"
    );
    if (confirm === undefined || confirm === null) return CANCEL;
    const c = String(confirm).trim().toLowerCase();
    if (c === "n" || c === "no" || c === "否" || c === "重" || c === "重选") {
      if (ctx.Notice) new ctx.Notice(`🔁 重新选择...`, 2000);
      continue;
    }
    state.isToday = isToday;
    state.todaySource = todaySource;
    if (ctx.Notice) new ctx.Notice(`✅ 已选: ${summary}`, 3000);
    console.warn("[快记任务 v2] stepIsToday 解析:", { pick: pick.slice(0, 30), isToday, todaySource });
    return null;
  }
}

async function stepStatus(state, qa, ctx) {
  const pick = await pickWithBack(qa,
    [
      "📋 Todo(默认 — 待办)",
      "🔄 Doing(进行中)",
      "💡 Idea(想法 / 草稿)",
      "🚧 Block(受阻)",
      "⏸ SubDone(子任务完成,主任务未完)",
      "✅ Done(已完成 — 补录历史)",
      "❌ cancel(取消)",
    ],
    ["todo", "doing", "idea", "block", "subdone", "done", "cancel"],
    ctx.canBack
  );
  if (pick === CANCEL || pick === BACK) return pick;
  state.status = pick;
  return null;
}

async function stepTitle(state, qa, ctx) {
  const raw = await inputWithBack(qa, "任务标题(简短;后续可加详情)", "", "");
  if (raw === CANCEL || raw === BACK) return raw;
  if (!raw || !raw.trim()) {
    // 标题空 = 取消创建(顶层会 Notice)
    return CANCEL;
  }
  state.title = raw.trim();
  return null;
}

const STEP_DISPATCH = {
  priority: stepPriority,
  adhd: stepAdhd,
  category: stepCategory,
  parentLevel1: stepParentLevel1,
  parentLevel2: stepParentLevel2,
  projectMinor: stepProjectMinor,
  subcategoryManual: stepSubcategoryManual,
  due: stepDue,
  months: stepMonths,
  weeks: stepWeeks,
  isToday: stepIsToday,
  status: stepStatus,
  title: stepTitle,
};

// 跑完整 wizard,返回 state(或 null 表示取消)
async function runWizard(qaApi, qopts, Notice) {
  const state = {
    priority: null,
    adhd: null,
    category: null,
    parentName: null,
    parentRecordId: null,
    subName: null,
    projectMinor: [],
    subcategoryList: [],
    titlePrefix: "",
    due: null,
    months: [],
    weeks: [],
    isToday: false,
    todaySource: null,        // v0.6.5: planned / unplanned / null
    status: "todo",
    title: null,
  };

  // v0.7.12: 追踪 silent skip 的 step(没向用户弹 UI 的),BACK 时透过它们
  // 触发场景:qopts 拉飞书选项失败 / recent 数组为空 → stepProjectMinor / stepMonths 等直接 return SKIPPED
  // 修复 bug:之前 silent skip 走 return null 让 i 自增,用户在下一步按 BACK 会回到 silent skip step,
  //          立即又被推到下一步,表象就是"回不去上一步"
  const silentSkipped = new Set();

  let i = 0;
  while (i < STEPS.length) {
    const stepName = STEPS[i];
    if (!isStepActive(stepName, state)) { i++; continue; }
    const canBack = findPrevActive(i, state, silentSkipped) >= 0;
    const result = await STEP_DISPATCH[stepName](state, qaApi, { canBack, qopts, Notice });
    if (result === CANCEL) {
      new Notice("❌ 已取消", 3000);
      return null;
    }
    if (result === BACK) {
      const prev = findPrevActive(i, state, silentSkipped);
      if (prev < 0) {
        new Notice("⚠️ 已是第一步,无法后退(Esc 整体取消)", 3000);
        continue;
      }
      i = prev;
      continue;
    }
    if (result === SKIPPED) {
      silentSkipped.add(stepName);
    } else {
      silentSkipped.delete(stepName);  // 这步有 UI 了 → 撤销 silent 标记
    }
    i++;
  }
  return state;
}

// ============================================================
// 入口
// ============================================================
module.exports = async function (params) {
  const { app, obsidian, quickAddApi } = params;
  const { Notice } = obsidian;

  try {
    // ============ Step 0: batch 拉飞书选项 ============
    const { exec } = require("child_process");
    const util = require("util");
    const execAsync = util.promisify(exec);

    const vaultRoot = app.vault.adapter.basePath || app.vault.adapter.getBasePath();
    // v0.3.4: install.sh 装的时候 sed 替换占位符为 sync.py 绝对路径
    // ⚠️ 不要加 if 判断检测占位符 — install.sh 的 sed 是 `s|占位符|路径|g` 全替换,
    //    if 里的占位符也会被替换成同样路径,if 永远为 true 走 fallback,误导诊断
    //    (v0.7.12 第 1 次加 fallback 就踩了这个坑,Console 显示 electron.asar 错路径)
    //    若占位符未替换 → python3 命令直接 ENOENT,catch 块打 Notice 让用户跑 install.sh
    const syncScript = "__SYNC_PY_ABS_PATH__";
    const userPaths = [
      `${process.env.HOME}/.local/bin`,
      "/usr/local/bin",
      "/opt/homebrew/bin",
    ];
    const execEnv = {
      ...process.env,
      PATH: `${userPaths.join(":")}:${process.env.PATH || ""}`,
      // v0.5.2: 删 TZ 强制,sync.py 走 config.behavior.timezone(默认 mac local)
    };

    let qopts = {
      active_top_level: [],
      subprojects_by_parent: {},
      recent_months: [],
      recent_weeks: [],
      recent_project_minor: [],
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
        project_minor: qopts.recent_project_minor,
      });
    } catch (e) {
      console.warn("[快记任务 v2] quickadd-options 失败,降级:", e);
      new Notice(
        "⚠️ 飞书选项拉取失败,大类/小类/月/周菜单将跳过(降级运行)\n详情看 Console",
        4000
      );
    }

    // ============ 跑 state machine wizard ============
    const state = await runWizard(quickAddApi, qopts, Notice);
    if (!state) return;  // 用户 Esc 整体取消

    console.log("[快记任务 v2] final state:", state);

    // ============ 计算日期 + 路径 ============
    const bjISO = new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 19);
    const dateContext = getDateContext(app);
    const createdISO = `${dateContext}T${bjISO.slice(11)}`;
    const titleTrimmed = `${state.titlePrefix}${state.title}`;
    const safeTitle = titleTrimmed.replace(/[\\\/:*?"<>|]/g, "_");
    const filename = `${dateContext}-${safeTitle}.md`;
    const taskPath = `04 Inbox/task/${filename}`;
    const journalPath = `journals/${dateContext}`;

    if (app.vault.getAbstractFileByPath(taskPath)) {
      new Notice(`❌ 文件已存在: ${filename}\n请改名后再试`, 5000);
      return;
    }

    // ============ 生成 task md 内容 ============
    // parent_project 语义(沿用 v0.2.4):**最终归属** — 选了小类用小类名,否则用大类名
    const finalParentName = state.subName || state.parentName;
    const parentProjectLine = finalParentName
      ? `parent_project: "[[${finalParentName}]]"`
      : `parent_project:`;
    const parentSubLine = state.subName
      ? `parent_subproject: "[[${state.subName}]]"`
      : `parent_subproject:`;
    const adhdLine = state.adhd ? `adhd_priority: ${state.adhd}` : `adhd_priority:`;
    const dueLine = state.due ? `due: ${state.due}` : `due:`;
    const monthsLine = state.months.length > 0
      ? `iteration_month: [${state.months.join(", ")}]`
      : `iteration_month:`;
    const weeksLine = state.weeks.length > 0
      ? `iteration_week: [${state.weeks.join(", ")}]`
      : `iteration_week:`;
    const projectMinorLine = state.projectMinor.length > 0
      ? `project_minor: [${state.projectMinor.join(", ")}]`
      : `project_minor:`;
    const categoryLine = `category: ${state.category}`;
    const subcategoryLine = state.subcategoryList.length > 0
      ? `subcategory: [${state.subcategoryList.join(", ")}]`
      : `subcategory:`;
    const todayHistoryInit = state.isToday ? `[${dateContext}]` : `[]`;
    // v0.6.5: today_source 由 Step 7 用户选择(planned/unplanned),不再硬编码 unplanned
    const todaySourceLine = state.todaySource ? `today_source: ${state.todaySource}` : `today_source:`;

    const content = `---
priority: ${state.priority}
status: ${state.status}
today: ${state.isToday}
today_history: ${todayHistoryInit}
${todaySourceLine}
created: ${createdISO}
${dueLine}
done_date:
${categoryLine}
${subcategoryLine}
${projectMinorLine}
${adhdLine}
estimate_hours:
actual_hours:
efficiency:
quality:
${parentProjectLine}
${parentSubLine}
parent_task:
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

<!-- v0.4.0(2026-05-28)H2 段顺序对齐飞书看板视图字段顺序 -->

## 👥 用户故事
<!-- 同步到飞书「用户故事」字段。"作为 X,我希望 Y,以便 Z"句式。可选,产品类 task 用 -->


## ✅ 验收条件


## 💡 执行思路


## 📝 执行概述


## 📦 交付
<!-- ⭐ 最重要字段。同步到飞书「交付」字段。完成后填:做出来什么?产出 / 文件 / 链接 / 截图 / 部署位置 等 -->


## 🔗 相关资料


## 🪞 复盘


## ✅ 完成标记
<!-- dataview TASK 查询读这一行渲染 checkbox + 点击跳飞书(sync 成功后会自动改为 markdown link) -->
- [ ] ${titleTrimmed}
`;

    // ============ 创建 task md ============
    await app.vault.create(taskPath, content);
    const todayBanner = state.isToday
      ? "⭐ 今日 task(today: true,会进今日 journal「🎯 今日计划」段)"
      : "📥 进需求池(today: false,飞书勾今日 + pull-today 才进 journal)";
    new Notice(
      `✅ 已创建 task: ${filename}\n${todayBanner}\n🔄 正在同步飞书...(预计 5-10 秒)`,
      5000
    );

    // ============ 调 sync.py --task-md --apply ============
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
      const syncBanner = state.isToday
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
