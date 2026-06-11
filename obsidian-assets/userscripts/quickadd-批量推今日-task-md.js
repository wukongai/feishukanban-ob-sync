/**
 * QuickAdd UserScript: 🎯 批量推今日/补推某日 task md → 飞书
 *
 * 触发方式: Cmd+P → 搜「批量推今日」/「push-all-today」 → 回车
 *
 * 行为(v2 - 2026-06-06,v0.8.6 加日期选择):
 * 1. 弹 suggester:今日 / 昨日 / 自定义日期
 *    - 今日:走老逻辑 `--push-all-today --apply`(today=true ∪ 飞书今日 union)
 *    - 昨日:`--push-all-today --push-date <昨日> --apply`(today_history 含昨日,
 *      不写回 today_flag → 飞书「是否今日」字段交由用户自己在看板手动管)
 *    - 自定义:inputPrompt 输 YYYY-MM-DD,同昨日行为
 * 2. 场景:第二天早上才想起补推前一日的 task,日期一选直接批量
 * 3. 对称 pull-today:pull 拉飞书 → OB;push-all-today 推 OB → 飞书
 *
 * v1 行为(2026-05-28,v0.4.0 Step 3 加):无日期选择,只推 today=true
 * v2 升级(2026-06-06,v0.8.6):加日期 suggester + --push-date 参数透传
 *
 * 设计权衡(为什么默认 --apply 不走 dry-run):
 * - 用户已在 OB 端确认内容,期望"按一下立刻推飞书",不要再来一道 SOP
 * - build_fields_payload 内部 handle 空字段(空不写),不会清空飞书侧已有数据
 * - 影响范围:几条到二十几条,飞书侧可逆(用户可在飞书 app 撤销 / 重填)
 * - 补推历史模式额外加保护:不写回 today_flag → 飞书「是否今日」字段
 *
 * 参考 quickadd-拉今日todo.js 同款 exec 模式
 */

module.exports = async function (params) {
  const { app, obsidian, quickAddApi } = params;
  const { Notice } = obsidian;

  try {
    const { exec } = require("child_process");
    const util = require("util");
    const execAsync = util.promisify(exec);

    // === Step 0: 日期选择(v0.8.6,v2 新增)===
    // 北京时间今日 / 昨日 — 跟 sync.py `_now_with_tz(config)` 的 Asia/Shanghai 默认对齐
    const bjNow = new Date(Date.now() + 8 * 3600 * 1000);
    const todayISO = bjNow.toISOString().slice(0, 10);
    const yesterdayISO = new Date(bjNow.getTime() - 24 * 3600 * 1000)
      .toISOString()
      .slice(0, 10);

    const dateChoices = [
      `📅 今日 (${todayISO}) — 推 today=true 的全部 task`,
      `⏪ 昨日 (${yesterdayISO}) — 补推 today_history 含昨日的全部 task`,
      `🎯 自定义日期 — 输 YYYY-MM-DD 补推某历史日`,
    ];
    const dateChoice = await quickAddApi.suggester(dateChoices, dateChoices);
    if (!dateChoice) {
      new Notice("已取消", 2000);
      return;
    }

    let pushDate = null; // null = 今日模式(走原 --push-all-today),非 null = --push-date
    if (dateChoice.startsWith("📅 今日")) {
      pushDate = null;
    } else if (dateChoice.startsWith("⏪ 昨日")) {
      pushDate = yesterdayISO;
    } else {
      const input = await quickAddApi.inputPrompt(
        "输入日期 YYYY-MM-DD",
        yesterdayISO,
        yesterdayISO,
      );
      if (!input) {
        new Notice("已取消", 2000);
        return;
      }
      if (!/^\d{4}-\d{2}-\d{2}$/.test(input.trim())) {
        new Notice(`❌ 日期格式错(要 YYYY-MM-DD):${input}`, 5000);
        return;
      }
      pushDate = input.trim();
    }

    const vaultRoot =
      app.vault.adapter.basePath || app.vault.adapter.getBasePath();
    const syncScript = "__SYNC_PY_ABS_PATH__";
    let syncCmd = `python3 "${syncScript.replace(/"/g, '\\"')}" --vault "${vaultRoot.replace(/"/g, '\\"')}" --push-all-today --apply`;
    if (pushDate) {
      syncCmd += ` --push-date "${pushDate}"`;
    }

    console.log("[批量推今日 v2] syncCmd:", syncCmd);

    // Obsidian GUI 不继承 .zshrc PATH,显式注入(对齐其他 userscript)
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

    const modeLabel = pushDate ? `补推 ${pushDate}` : "今日";
    new Notice(`🔄 正在批量${modeLabel} task md → 飞书...(预计 10-30 秒)`, 5000);

    let stdout = "";
    let stderr = "";
    try {
      // 批量 push 可能慢(每条 task 都调 cli upsert),timeout 120 秒
      const result = await execAsync(syncCmd, { timeout: 120000, env: execEnv });
      stdout = result.stdout || "";
      stderr = result.stderr || "";
      console.log("[批量推 v2] stdout:", stdout);
      if (stderr) console.warn("[批量推 v2] stderr:", stderr);
    } catch (e) {
      console.error("[批量推 v2] 跑 sync.py 失败:", e);
      new Notice(
        `❌ 批量${modeLabel}失败:\n${e.message || e}\n查 Console (Cmd+Opt+I)`,
        10000
      );
      return;
    }

    // 解析 stdout 汇总(sync.py 输出格式见 push_all_today_task_md)
    // ✅ 成功: 22(0 CREATE / 22 UPDATE)
    // ❌ 失败: 0
    let totalCount = 0;
    let successCount = 0;
    let failCount = 0;
    let createCount = 0;
    let updateCount = 0;

    // v2 兼容两种汇总行:
    //   今日模式: `✅ 待推 22 条(today=true: 22,取消今日: 0)`
    //   补推模式: `✅ 待补推 5 条(today_history 含 2026-06-05)`
    const foundMatch = stdout.match(/✅ 待(?:补)?推 (\d+) 条/);
    if (foundMatch) totalCount = parseInt(foundMatch[1], 10);

    const successMatch = stdout.match(/✅ 成功: (\d+)\((\d+) CREATE \/ (\d+) UPDATE\)/);
    if (successMatch) {
      successCount = parseInt(successMatch[1], 10);
      createCount = parseInt(successMatch[2], 10);
      updateCount = parseInt(successMatch[3], 10);
    }

    const failMatch = stdout.match(/❌ 失败: (\d+)/);
    if (failMatch) failCount = parseInt(failMatch[1], 10);

    // 触发 dataview reindex(对称 pull-today 的 Step 4 自动刷新)
    // OB 端 frontmatter 没改但飞书可能改了 feishu_url cache,刷一下保险
    const bjDate = new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10);
    const todayJournalPath = `journals/${bjDate}.md`;
    const journalFile = app.vault.getAbstractFileByPath(todayJournalPath);

    await new Promise(r => setTimeout(r, 800));  // 给 fs watcher 时间

    try {
      const dvCommandIds = [
        "dataview:dataview-drop-cache-and-reload",
        "dataview:dataview-force-refresh-views",
        "dataview:dataview-rebuild-current-view",
        "dataview:dataview-rebuild",
        "dataview:rebuild",
      ];
      for (const cmdId of dvCommandIds) {
        if (app.commands.findCommand?.(cmdId)) {
          app.commands.executeCommandById(cmdId);
          console.log(`[批量推 v2] dataview command 触发: ${cmdId}`);
          break;
        }
      }
      if (journalFile) {
        const leaves = app.workspace.getLeavesOfType("markdown");
        for (const leaf of leaves) {
          if (leaf.view?.file?.path === todayJournalPath) {
            leaf.view.previewMode?.rerender?.(true);
          }
        }
      }

      // 终极兜底:disable+enable dataview plugin(对齐拉今日 todo)
      try {
        if (app.plugins.plugins["dataview"] && app.plugins.disablePlugin && app.plugins.enablePlugin) {
          await app.plugins.disablePlugin("dataview");
          await new Promise(r => setTimeout(r, 300));
          await app.plugins.enablePlugin("dataview");
          console.log("[批量推 v2] dataview plugin 重启完成");
        }
      } catch (e) {
        console.warn("[批量推 v2] dataview 重启失败:", e);
      }
    } catch (e) {
      console.warn("[批量推 v2] dataview 刷新失败(不阻塞):", e);
    }

    // 弹 Notice 报告
    if (totalCount === 0) {
      const emptyHint = pushDate
        ? `⚠️ 无 today_history 含 ${pushDate} 的 task md 可推`
        : `⚠️ 无 today=true task md 可推`;
      new Notice(emptyHint, 5000);
    } else {
      let msg = `✅ 批量${modeLabel}完成\n`;
      msg += `📊 总: ${totalCount} 条\n`;
      msg += `✅ 成功: ${successCount}`;
      if (createCount > 0 || updateCount > 0) {
        msg += `(${createCount} CREATE / ${updateCount} UPDATE)`;
      }
      msg += `\n`;
      if (failCount > 0) {
        msg += `❌ 失败: ${failCount} 条(看 Console)\n`;
      }
      if (pushDate) {
        msg += `\n💡 飞书侧「是否今日」字段未动,如需取消请在看板手动操作后跑「拉今日 todo」回写 OB`;
      }
      new Notice(msg, pushDate ? 15000 : 10000);
    }
  } catch (e) {
    console.error("[批量推 v2] 顶层异常:", e);
    new Notice(
      `❌ 脚本异常: ${e.message}\n请打开 Console (Cmd+Opt+I) 看详情`,
      10000
    );
  }
};
