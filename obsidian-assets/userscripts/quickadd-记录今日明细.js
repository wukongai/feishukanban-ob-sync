/**
 * QuickAdd UserScript: 📈 记录今日执行明细 + sync 飞书子表
 *
 * 触发方式: Cmd+P → 搜「记录今日明细」/「log-detail」 → 回车
 * 前置条件: current note 必须是 task md(04 Inbox/task/ 下,frontmatter 有 feishu_record)
 *
 * v3 行为(2026-05-30,v0.6.7):覆盖飞书子表全部 6 个字段 + 每步可退回/跳过 + 末步可见预览
 *   字段顺序对齐飞书子表 schema:状态 → 计划 → 估时 → 用时 → 完成度 → 复盘
 *   (review/复盘是最长文本字段,放最末;事前 plan/est → 事中事后 act/done → 文字 review)
 *
 *   Step 1: 🎯 执行状态(必填,7 态)            → status
 *   Step 2: 📋 计划/策略(可选)                 → 计划=
 *   Step 3: ⏰ 估时(可选,小时数字)             → 估时=
 *   Step 4: ⏱️ 用时(可选,小时数字)             → 用时=
 *   Step 5: 🎯 完成度(可选,5 选项)             → 完成度=
 *   Step 6: 📝 执行/复盘(可选,长文本)          → 复盘=
 *   Step 7: ✅ 多行预览 + 确认写入(可退回)
 *
 * v0.6.7 设计选择:
 * - 状态值:纯文本首字母大写(Todo/Doing/Done/SubDone/Block/Cancel/Idea)— 去 emoji,
 *   因为明细段是事后手动修改的,emoji 会被 Obsidian 渲染成 checkbox 阻碍编辑。
 *   menu 显示时仍带 emoji 做视觉提示,写入是纯文本。
 * - key 中文化(`计划=` / `估时=` / `用时=` / `完成度=` / `复盘=`)— 中文识别度更高,
 *   sync.py 解析端双向兼容(中文 + 英文老 key),老段下次 push 自动 normalize 为中文。
 *
 *   每个可选字段先弹 suggester 入口:[✏️ 输入 / ⏭️ 跳过 / ⏪ 退回 / ❌ 取消]
 *   退回会回到上一步重新选择;取消整个流程不写任何内容
 *
 * 写入 + 推送:
 *   - 本地 task md「## 📈 执行明细」段同日覆盖
 *   - 调 sync.py --task-md --apply 推飞书子表(CREATE 1 条 record)
 *
 * 跟「完成 task」的区别:
 *   - 完成 task = 终态记录(status: done 一次性)
 *   - 记录今日明细 = 过程记录(每天可以加一条,描述当天的执行情况)
 *
 * v2(2026-05-29):加 ⏱️ 用时 + 🎯 完成度
 * v3(2026-05-30,v0.6.7):加 📋 plan + ⏰ est + 每步退回/跳过 + 预览
 */

module.exports = async function (params) {
  const { app, obsidian, quickAddApi } = params;
  const { Notice } = obsidian;

  // 导航 sentinel(用 Symbol 避免和真实输入串味)
  const ACT_BACK = "__BACK__";
  const ACT_CANCEL = "__CANCEL__";
  const ACT_SKIP = "__SKIP__";    // 跳过 = 不写该字段(数据存 "")
  const ACT_INPUT = "__INPUT__";  // 选了"输入"分支后真正弹 inputPrompt

  /** 通用「可选字段入口」suggester(输入/跳过/退回/取消) */
  async function navMenu(label, currentValueHint) {
    const hintSuffix = currentValueHint ? ` (当前: ${currentValueHint})` : "";
    const display = [
      `✏️ 输入${label}${hintSuffix}`,
      `⏭️ 跳过此项(不记 ${label})`,
      `⏪ 退回上一步`,
      `❌ 取消整个流程`,
    ];
    const value = [ACT_INPUT, ACT_SKIP, ACT_BACK, ACT_CANCEL];
    const pick = await quickAddApi.suggester(display, value);
    if (!pick) return ACT_CANCEL;  // Esc 视同取消
    return pick;
  }

  try {
    // ============================================================
    // Step 0: 检查 current note(沿用 v2 逻辑)
    // ============================================================
    const activeFile = app.workspace.getActiveFile();
    if (!activeFile) {
      new Notice(`❌ 没有打开的 task md`, 5000);
      return;
    }
    if (!activeFile.path.endsWith(".md")) {
      new Notice(`❌ 当前文件不是 .md`, 5000);
      return;
    }

    const content = await app.vault.read(activeFile);
    const fmMatch = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n/);
    if (!fmMatch) {
      new Notice(`❌ 当前文件无 frontmatter,不是 task md`, 5000);
      return;
    }
    const fmText = fmMatch[1];
    const recMatch = fmText.match(/^feishu_record:\s*(.+?)\s*$/m);
    const feishuRecord = recMatch ? recMatch[1].trim().replace(/^['"]|['"]$/g, "") : "";
    if (!feishuRecord || feishuRecord.startsWith("#")) {
      new Notice(
        `❌ task md 还没 sync 飞书(无 feishu_record)\n先跑「推当前 task」CREATE 飞书 record 后再记明细`,
        7000
      );
      return;
    }

    console.log("[记录今日明细 v3] task:", activeFile.path, "rec:", feishuRecord);

    // ============================================================
    // State machine: 6 步采集 + 1 步预览
    // ============================================================
    // 状态选项:menu 显示带 emoji 做视觉提示,但 value 是纯文本(v0.6.7 — 写入 task md 用)
    const STATUS_OPTIONS = [
      { display: "🔄 Doing — 正在做", value: "Doing" },
      { display: "✅ Done — 完成", value: "Done" },
      { display: "🟧 SubDone — 部分完成", value: "SubDone" },
      { display: "🚧 Block — 卡住", value: "Block" },
      { display: "⬜ Todo — 还没开始", value: "Todo" },
      { display: "💡 Idea — 仅构思", value: "Idea" },
      { display: "❌ Cancel — 取消", value: "Cancel" },
    ];
    const COMPLETION_OPTIONS = ["标准完成", "最小完成", "超额完成", "阻碍", "未启动"];

    // 收集的数据(undefined = 还没经过,'' = 用户选了跳过,具体值 = 用户输入了)
    const data = { status: undefined, plan: "", est: "", act: "", done: "", review: "" };

    // STEPS 顺序对齐飞书子表 schema:status → plan → est → act → done → review → preview
    // v0.6.7 修正:review 从原第 2 位挪到末尾(原来错误地放在 plan 后面)
    const STEPS = ["status", "plan", "est", "act", "done", "review", "preview"];
    let idx = 0;

    while (idx < STEPS.length) {
      const step = STEPS[idx];

      // ----- Step 1: status(必填,不能跳过) -----
      if (step === "status") {
        const currentHint = data.status ? `当前 ${data.status},直接选新值替换` : "";
        const display = [
          ...STATUS_OPTIONS.map(o => o.display),
          "❌ 取消整个流程",
        ];
        const value = [
          ...STATUS_OPTIONS.map(o => o.value),
          ACT_CANCEL,
        ];
        const pick = await quickAddApi.suggester(display, value);
        if (!pick || pick === ACT_CANCEL) {
          new Notice(`❌ 已取消`, 3000);
          return;
        }
        data.status = pick;
        idx += 1;
        continue;
      }

      // ----- Step 7: preview + 确认(v0.6.7:多行 display 让预览可见) -----
      if (step === "preview") {
        const today = todayBJ();
        const previewLine = buildLine(today, data);

        // 多行 suggester display:每个已填字段一行(NOOP 不可选),最后是 3 个动作
        // ❗ 每个 NOOP value 必须唯一 — QuickAdd suggester 若多个 value 相同,会用第一个 display
        //    渲染所有匹配项,导致预览行全显示成 status header(bug 实测于 2026-05-30 v3.0)
        const display = [`📋 ${today}   状态: ${data.status}`];
        const value = ["__NOOP_header__"];
        const truncate = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
        if (data.plan)   { display.push(`   📋 计划:   ${truncate(data.plan, 50)}`);   value.push("__NOOP_plan__"); }
        if (data.est)    { display.push(`   ⏰ 估时:   ${data.est} 小时`);             value.push("__NOOP_est__"); }
        if (data.act)    { display.push(`   ⏱  用时:   ${data.act} 小时`);             value.push("__NOOP_act__"); }
        if (data.done)   { display.push(`   🎯 完成度: ${data.done}`);                 value.push("__NOOP_done__"); }
        if (data.review) { display.push(`   📝 复盘:   ${truncate(data.review, 50)}`); value.push("__NOOP_review__"); }
        const filledCount = display.length - 1;
        if (filledCount === 0) {
          display.push(`   (跳过了所有可选字段,只记状态)`);
          value.push("__NOOP_empty__");
        }
        display.push(`─────────────────`);
        value.push("__NOOP_sep__");
        display.push(`✅ 确认写入并 sync 飞书`);
        value.push("CONFIRM");
        display.push(`⏪ 退回上一步(改复盘)`);
        value.push(ACT_BACK);
        display.push(`❌ 取消整个流程`);
        value.push(ACT_CANCEL);

        // NOOP 行不可选 → 选中重弹(用 prefix 匹配,因为每行 NOOP value 唯一)
        let pick;
        while (true) {
          pick = await quickAddApi.suggester(display, value);
          if (typeof pick !== "string" || !pick.startsWith("__NOOP_")) break;
        }
        console.log("[记录今日明细 v3] 预览:", previewLine);
        if (!pick || pick === ACT_CANCEL) {
          new Notice(`❌ 已取消(未写入)`, 3000);
          return;
        }
        if (pick === ACT_BACK) {
          idx -= 1;
          continue;
        }
        // CONFIRM → break loop 进入写入阶段
        break;
      }

      // ----- 通用可选字段 step:plan / review / est / act / done -----
      const meta = stepMeta(step);
      const currentHint = data[step];
      const nav = await navMenu(meta.label, currentHint);

      if (nav === ACT_CANCEL) {
        new Notice(`❌ 已取消`, 3000);
        return;
      }
      if (nav === ACT_BACK) {
        idx -= 1;
        continue;
      }
      if (nav === ACT_SKIP) {
        data[step] = "";
        idx += 1;
        continue;
      }
      // nav === ACT_INPUT
      if (step === "done") {
        // done 是 enum,用 suggester(不是 inputPrompt)
        const pick = await quickAddApi.suggester(
          ["⏪ 退回(重选)", ...COMPLETION_OPTIONS],
          [ACT_BACK, ...COMPLETION_OPTIONS]
        );
        if (!pick || pick === ACT_BACK) {
          // 不前进,留在当前 step 重弹 navMenu
          continue;
        }
        data.done = pick;
        idx += 1;
        continue;
      }
      // plan / review / est / act 走 inputPrompt
      const raw = await quickAddApi.inputPrompt(
        meta.prompt,
        meta.placeholder,
        data[step] || ""
      );
      if (raw === null || raw === undefined) {
        // 用户在 inputPrompt 按 Esc → 视为退回(回 navMenu)
        continue;
      }
      const trimmed = String(raw).trim();
      if (!trimmed) {
        // 空字符串 = 跳过
        data[step] = "";
        idx += 1;
        continue;
      }
      // 数字字段做校验(est / act)
      if (step === "est" || step === "act") {
        const n = parseFloat(trimmed);
        if (isNaN(n) || n < 0) {
          new Notice(`⚠️ 不是有效的小时数 "${trimmed}",已跳过此项`, 5000);
          data[step] = "";
          idx += 1;
          continue;
        }
        data[step] = String(n);
      } else {
        data[step] = trimmed;
      }
      idx += 1;
    }

    // ============================================================
    // 写入阶段:本地 task md + sync 飞书子表
    // ============================================================
    const today = todayBJ();
    const newLine = buildLine(today, data);

    let newContent;
    const sectionRegex = /^(## +📈 +执行明细\s*\n)((?:.*\n)*?)(?=\n## |\n*$)/m;
    const secMatch = content.match(sectionRegex);
    if (secMatch) {
      const header = secMatch[1];
      const oldBody = secMatch[2];
      const sameDayRegex = new RegExp(`^\\- ${today}\\s*\\|.*$`, "gm");
      const filteredBody = oldBody.replace(sameDayRegex, "").replace(/\n{3,}/g, "\n\n");
      const trimmedBody = filteredBody.replace(/\s+$/, "");
      const newBody = trimmedBody ? `${trimmedBody}\n${newLine}\n` : `\n${newLine}\n`;
      newContent = content.replace(sectionRegex, `${header}${newBody}`);
    } else {
      const marker = "## ✅ 完成标记";
      if (!content.includes(marker)) {
        new Notice(
          `❌ task md 没有「## ✅ 完成标记」段,无法自动插入「## 📈 执行明细」\n请手动加段后再试`,
          7000
        );
        return;
      }
      const newSection = `## 📈 执行明细\n\n${newLine}\n\n\n`;
      newContent = content.replace(marker, newSection + marker);
    }

    await app.vault.modify(activeFile, newContent);
    new Notice(
      `✅ 已写本地: ${today} | ${data.status}\n🔄 正在 sync 飞书子表...(3-8 秒)`,
      4000
    );

    // 调 sync.py --task-md --apply
    const { exec } = require("child_process");
    const util = require("util");
    const execAsync = util.promisify(exec);

    const vaultRoot =
      app.vault.adapter.basePath || app.vault.adapter.getBasePath();
    const syncScript = "__SYNC_PY_ABS_PATH__";
    const absPath = `${vaultRoot}/${activeFile.path}`;
    const syncCmd = `python3 "${syncScript.replace(/"/g, '\\"')}" --vault "${vaultRoot.replace(/"/g, '\\"')}" --task-md "${absPath.replace(/"/g, '\\"')}" --apply`;

    console.log("[记录今日明细 v3] syncCmd:", syncCmd);

    const userPaths = [
      `${process.env.HOME}/.local/bin`,
      "/usr/local/bin",
      "/opt/homebrew/bin",
    ];
    const execEnv = {
      ...process.env,
      PATH: `${userPaths.join(":")}:${process.env.PATH || ""}`,
    };

    try {
      const { stdout, stderr } = await execAsync(syncCmd, { timeout: 60000, env: execEnv });
      console.log("[记录今日明细 v3] sync stdout:", stdout);
      if (stderr) console.warn("[记录今日明细 v3] sync stderr:", stderr);

      const detailMatch = stdout.match(/CREATE (\d+) \/ UPDATE (\d+) \/ SKIP (\d+) \/ ERROR (\d+)/);
      if (detailMatch) {
        const [, c, u, s, e] = detailMatch;
        const action = parseInt(c) > 0 ? "CREATE" : (parseInt(u) > 0 ? "UPDATE" : "SKIP");
        new Notice(
          `✅ 今日明细已推飞书子表\n📈 ${today} | ${data.status}\n☁️ ${action} (CREATE ${c} / UPDATE ${u} / SKIP ${s})`,
          6000
        );
      } else {
        new Notice(
          `⚠️ 本地已写,飞书推送结果不明(查 Console)\n看 stdout 是否有 "明细" 字样`,
          7000
        );
      }
    } catch (e) {
      console.error("[记录今日明细 v3] sync 失败:", e);
      new Notice(
        `⚠️ 本地已写,飞书 sync 失败:\n${e.message || e}`,
        10000
      );
    }
  } catch (e) {
    console.error("[记录今日明细 v3] 顶层异常:", e);
    new Notice(
      `❌ 脚本异常: ${e.message}\n打开 Console (Cmd+Opt+I) 看详情`,
      10000
    );
  }
};

// ============ helpers ============

function todayBJ() {
  // 北京时间 YYYY-MM-DD
  return new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10);
}

function stepMeta(step) {
  switch (step) {
    case "plan":
      return {
        label: "计划/策略",
        prompt: "📋 计划/策略 plan(可选):今天打算做什么/用什么策略?",
        placeholder: "例:先把 sync.py 的子表 push 跑通,再加 wizard",
      };
    case "review":
      return {
        label: "执行/复盘",
        prompt: "📝 执行/复盘 review(可选):实际做了什么/遇到什么?",
        placeholder: "例:写完了 push-all-today 修复,dry-run 全 PASS",
      };
    case "est":
      return {
        label: "估时",
        prompt: "⏰ 估时 est(可选,小时数):打算花几小时?",
        placeholder: "1.5",
      };
    case "act":
      return {
        label: "用时",
        prompt: "⏱️ 用时 act(可选,小时数):实际花了几小时?",
        placeholder: "2",
      };
    case "done":
      return {
        label: "完成度",
        prompt: "🎯 完成度 done(可选):本日完成达成度?",
        placeholder: "",
      };
    default:
      return { label: step, prompt: step, placeholder: "" };
  }
}

function buildLine(today, data) {
  // 子表 schema 顺序拼装(v0.6.7):计划 → 估时 → 用时 → 完成度 → 复盘(空字段不写)
  // 跟飞书子表「计划&策略 → 估时 → 用时 → 完成度 → 执行&复盘」字段顺序一致
  // key 中文化:用户反馈"中文更容易识别",sync.py 端解析双向兼容老英文 key
  const parts = [];
  if (data.plan && data.plan.trim()) parts.push(`计划=${data.plan.trim()}`);
  if (data.est && data.est.trim()) parts.push(`估时=${data.est.trim()}`);
  if (data.act && data.act.trim()) parts.push(`用时=${data.act.trim()}`);
  if (data.done && data.done.trim()) parts.push(`完成度=${data.done.trim()}`);
  if (data.review && data.review.trim()) parts.push(`复盘=${data.review.trim()}`);
  let line = `- ${today} | ${data.status}`;
  if (parts.length) line += ` | ${parts.join(" / ")}`;
  return line;
}
