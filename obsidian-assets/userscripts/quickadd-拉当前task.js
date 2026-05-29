/**
 * QuickAdd UserScript: 📥 拉当前 task(单条 pull,类 git pull 单条粒度)
 *
 * 触发方式: Cmd+P → 搜「拉当前 task」/「pull-task」 → 回车
 *
 * 行为(v1 - 2026-05-29,v0.5.3 加):
 * 1. 拿当前打开的 task md 路径
 * 2. 调 `sync.py --pull-task <path> --apply` 单条拉飞书 → OB
 * 3. 弹 Notice 报告
 *
 * 设计目的(用户原话):"和 git 一样,只提交一条也不容易覆盖其他的"
 * - 不动其他 today task md 的字段
 * - 只关心当前打开的这一条 task,飞书侧改了什么字段就同步什么
 * - 早上拉今日 + 临时拉单条 + 晚上推今日 = 完整工作流
 *
 * 参考 quickadd-拉今日todo.js 同款 exec 模式
 */

module.exports = async function (params) {
  const { app, obsidian } = params;
  const { Notice } = obsidian;

  try {
    // Step 1: 检查 current note
    const activeFile = app.workspace.getActiveFile();
    if (!activeFile) {
      new Notice(`❌ 没有打开的 task md`, 5000);
      return;
    }
    if (!activeFile.path.endsWith(".md")) {
      new Notice(`❌ 当前文件不是 .md`, 5000);
      return;
    }

    // Step 2: 检查 frontmatter feishu_record(必填,没有就不能拉)
    const content = await app.vault.read(activeFile);
    const fmMatch = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n/);
    if (!fmMatch) {
      new Notice(`❌ task md 没有 frontmatter,无法拉`, 5000);
      return;
    }
    const fmText = fmMatch[1];
    const recMatch = fmText.match(/^feishu_record:\s*(.+?)\s*$/m);
    const feishuRecord = recMatch ? recMatch[1].trim().replace(/^['"]|['"]$/g, "") : "";
    if (!feishuRecord || feishuRecord.startsWith("#")) {
      new Notice(
        `❌ task md 无 feishu_record(未 sync 过飞书,无法拉)\n建议:Cmd+P「↗️ 推当前 task」先 CREATE 飞书 record`,
        7000
      );
      return;
    }

    console.log("[拉当前 task v1] 当前文件:", activeFile.path, "record_id:", feishuRecord);

    // Step 3: 构造命令
    const { exec } = require("child_process");
    const util = require("util");
    const execAsync = util.promisify(exec);

    const vaultRoot =
      app.vault.adapter.basePath || app.vault.adapter.getBasePath();
    const syncScript = "__SYNC_PY_ABS_PATH__";
    const absPath = `${vaultRoot}/${activeFile.path}`;
    const syncCmd = `python3 "${syncScript.replace(/"/g, '\\"')}" --vault "${vaultRoot.replace(/"/g, '\\"')}" --pull-task "${absPath.replace(/"/g, '\\"')}" --apply`;

    console.log("[拉当前 task v1] syncCmd:", syncCmd);

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

    new Notice(`🔄 正在拉飞书 → 当前 task...(预计 3-5 秒)`, 3000);

    let stdout = "";
    let stderr = "";
    try {
      const result = await execAsync(syncCmd, { timeout: 30000, env: execEnv });
      stdout = result.stdout || "";
      stderr = result.stderr || "";
      console.log("[拉当前 task v1] stdout:", stdout);
      if (stderr) console.warn("[拉当前 task v1] stderr:", stderr);
    } catch (e) {
      console.error("[拉当前 task v1] 跑 sync.py 失败:", e);
      new Notice(
        `❌ 拉当前 task 失败:\n${e.message || e}\n查 Console (Cmd+Opt+I)`,
        10000
      );
      return;
    }

    // Step 4: 解析 stdout 报告
    const alignedMatch = stdout.match(/OB ↔ 飞书 已对齐/);
    const successMatch = stdout.match(/✅ pull-task 完成/);

    // 触发 dataview reload(单条改 frontmatter 后,journal 显示可能需要刷新)
    await new Promise(r => setTimeout(r, 500));
    try {
      const dvCmds = [
        "dataview:dataview-rebuild-current-view",
        "dataview:dataview-force-refresh-views",
      ];
      for (const cmdId of dvCmds) {
        if (app.commands.findCommand?.(cmdId)) {
          app.commands.executeCommandById(cmdId);
          break;
        }
      }
    } catch (e) {
      console.warn("[拉当前 task v1] dataview 刷新失败:", e);
    }

    if (alignedMatch) {
      new Notice(`✅ OB ↔ 飞书 已对齐,${activeFile.basename} 无需更新`, 5000);
    } else if (successMatch) {
      // 解析 diff 数(简单计数)
      const fmDiffCount = (stdout.match(/^\s*• /gm) || []).length;
      const h2DiffCount = (stdout.match(/^\s*• 📑 /gm) || []).length;
      new Notice(
        `✅ 拉当前 task 完成\n📝 ${activeFile.basename}\n📊 ${fmDiffCount - h2DiffCount} 字段 + ${h2DiffCount} H2 段 sync`,
        7000
      );
    } else {
      new Notice(`⚠️ pull-task 结果不明,查 Console`, 5000);
    }
  } catch (e) {
    console.error("[拉当前 task v1] 顶层异常:", e);
    new Notice(
      `❌ 脚本异常: ${e.message}\n请打开 Console (Cmd+Opt+I) 看详情`,
      10000
    );
  }
};
