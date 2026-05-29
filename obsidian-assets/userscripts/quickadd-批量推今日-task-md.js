/**
 * QuickAdd UserScript: 🎯 批量推今日 task md → 飞书
 *
 * 触发方式: Cmd+P → 搜「批量推今日」/「push-all-today」 → 回车
 *
 * 行为(v1 - 2026-05-28,v0.4.0 Step 3 加):
 * 1. 调 `sync.py --push-all-today --apply` 反向推 OB → 飞书
 * 2. 场景:AI 助手 / Claude Code 在 OB 端补充了多条 task md 的「## 📦 交付」/
 *    「## 🪞 复盘」/「## 💡 执行思路」等内容,一键把所有 today task 推到飞书看板
 * 3. 对称 pull-today:pull 拉飞书 → OB;push-all-today 推 OB → 飞书
 *
 * 设计权衡(为什么默认 --apply 不走 dry-run):
 * - 用户已在 OB 端确认内容,期望"按一下立刻推飞书",不要再来一道 SOP
 * - build_fields_payload 内部 handle 空字段(空不写),不会清空飞书侧已有数据
 * - 影响范围:今日 task(几条到二十几条),飞书侧可逆(用户可在飞书 app 撤销 / 重填)
 *
 * 参考 quickadd-拉今日todo.js 同款 exec 模式
 */

module.exports = async function (params) {
  const { app, obsidian } = params;
  const { Notice } = obsidian;

  try {
    const { exec } = require("child_process");
    const util = require("util");
    const execAsync = util.promisify(exec);

    const vaultRoot =
      app.vault.adapter.basePath || app.vault.adapter.getBasePath();
    const syncScript = "__SYNC_PY_ABS_PATH__";
    const syncCmd = `python3 "${syncScript.replace(/"/g, '\\"')}" --vault "${vaultRoot.replace(/"/g, '\\"')}" --push-all-today --apply`;

    console.log("[批量推今日 v1] syncCmd:", syncCmd);

    // Obsidian GUI 不继承 .zshrc PATH,显式注入(对齐其他 userscript)
    const userPaths = [
      `${process.env.HOME}/.local/bin`,
      "/usr/local/bin",
      "/opt/homebrew/bin",
    ];
    const execEnv = {
      ...process.env,
      PATH: `${userPaths.join(":")}:${process.env.PATH || ""}`,
      TZ: "Asia/Shanghai",
    };

    new Notice(`🔄 正在批量推今日 task md → 飞书...(预计 10-30 秒)`, 5000);

    let stdout = "";
    let stderr = "";
    try {
      // 批量 push 可能慢(每条 task 都调 cli upsert),timeout 120 秒
      const result = await execAsync(syncCmd, { timeout: 120000, env: execEnv });
      stdout = result.stdout || "";
      stderr = result.stderr || "";
      console.log("[批量推今日 v1] stdout:", stdout);
      if (stderr) console.warn("[批量推今日 v1] stderr:", stderr);
    } catch (e) {
      console.error("[批量推今日 v1] 跑 sync.py 失败:", e);
      new Notice(
        `❌ 批量推今日失败:\n${e.message || e}\n查 Console (Cmd+Opt+I)`,
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

    const foundMatch = stdout.match(/找到 (\d+) 条 today=true task md/);
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
          console.log(`[批量推今日 v1] dataview command 触发: ${cmdId}`);
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
          console.log("[批量推今日 v1] dataview plugin 重启完成");
        }
      } catch (e) {
        console.warn("[批量推今日 v1] dataview 重启失败:", e);
      }
    } catch (e) {
      console.warn("[批量推今日 v1] dataview 刷新失败(不阻塞):", e);
    }

    // 弹 Notice 报告
    if (totalCount === 0) {
      new Notice(`⚠️ 无 today=true task md 可推`, 5000);
    } else {
      let msg = `✅ 批量推今日完成\n`;
      msg += `📊 总: ${totalCount} 条\n`;
      msg += `✅ 成功: ${successCount}`;
      if (createCount > 0 || updateCount > 0) {
        msg += `(${createCount} CREATE / ${updateCount} UPDATE)`;
      }
      msg += `\n`;
      if (failCount > 0) {
        msg += `❌ 失败: ${failCount} 条(看 Console)\n`;
      }
      new Notice(msg, 10000);
    }
  } catch (e) {
    console.error("[批量推今日 v1] 顶层异常:", e);
    new Notice(
      `❌ 脚本异常: ${e.message}\n请打开 Console (Cmd+Opt+I) 看详情`,
      10000
    );
  }
};
