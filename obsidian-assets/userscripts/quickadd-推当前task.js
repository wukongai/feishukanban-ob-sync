/**
 * QuickAdd UserScript: ↗️ 推当前 task(单条 push,类 git push 单条 commit 粒度)
 *
 * 触发方式: Cmd+P → 搜「推当前 task」/「push-task」 → 回车
 *
 * 行为(v1 - 2026-05-29,v0.5.3 加):
 * 1. 拿当前打开的 task md 路径
 * 2. 调 `sync.py --task-md <path> --apply` 单条推 OB → 飞书
 * 3. 弹 Notice 报告(CREATE 还是 UPDATE)
 *
 * 设计目的(用户原话):"和 git 一样,只提交一条也不容易覆盖其他的"
 * - 跟批量「↗️ 推今日所有」对应,单条粒度风险更低
 * - 改了某条 task 立刻 push 该条,不需要等晚上批量
 *
 * 跟「📝 快记任务」的区别:
 * - 快记任务 = 新建 task md + 立刻 CREATE 飞书(向导式 9 步)
 * - 推当前 task = 已有 task md(可能已 sync) → CREATE 或 UPDATE 飞书
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

    // Step 2: 简单 frontmatter 检查
    const content = await app.vault.read(activeFile);
    const fmMatch = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n/);
    if (!fmMatch) {
      new Notice(`❌ 当前文件无 frontmatter,不是 task md`, 5000);
      return;
    }
    const fmText = fmMatch[1];
    const recMatch = fmText.match(/^feishu_record:\s*(.+?)\s*$/m);
    const feishuRecord = recMatch ? recMatch[1].trim().replace(/^['"]|['"]$/g, "") : "";
    const action = (feishuRecord && !feishuRecord.startsWith("#")) ? "UPDATE" : "CREATE";

    console.log("[推当前 task v1] 当前文件:", activeFile.path, "action:", action);

    // Step 3: 构造命令
    const { exec } = require("child_process");
    const util = require("util");
    const execAsync = util.promisify(exec);

    const vaultRoot =
      app.vault.adapter.basePath || app.vault.adapter.getBasePath();
    const syncScript = "__SYNC_PY_ABS_PATH__";
    const absPath = `${vaultRoot}/${activeFile.path}`;
    const syncCmd = `python3 "${syncScript.replace(/"/g, '\\"')}" --vault "${vaultRoot.replace(/"/g, '\\"')}" --task-md "${absPath.replace(/"/g, '\\"')}" --apply`;

    console.log("[推当前 task v1] syncCmd:", syncCmd);

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

    new Notice(`🔄 正在推当前 task → 飞书(${action})...(预计 3-5 秒)`, 3000);

    let stdout = "";
    let stderr = "";
    try {
      const result = await execAsync(syncCmd, { timeout: 30000, env: execEnv });
      stdout = result.stdout || "";
      stderr = result.stderr || "";
      console.log("[推当前 task v1] stdout:", stdout);
      if (stderr) console.warn("[推当前 task v1] stderr:", stderr);
    } catch (e) {
      console.error("[推当前 task v1] 跑 sync.py 失败:", e);
      new Notice(
        `❌ 推当前 task 失败:\n${e.message || e}\n查 Console (Cmd+Opt+I)`,
        10000
      );
      return;
    }

    // Step 4: 解析 stdout 报告
    const createMatch = stdout.match(/✅ CREATE 成功[\s\S]*?record_id:\s*(rec\w+)/);
    const updateMatch = stdout.match(/✅ UPDATE 成功/);

    if (createMatch) {
      new Notice(
        `✅ 推当前 task 完成(CREATE)\n📝 ${activeFile.basename}\n🆔 record: ${createMatch[1]}`,
        7000
      );
    } else if (updateMatch) {
      new Notice(
        `✅ 推当前 task 完成(UPDATE)\n📝 ${activeFile.basename}`,
        5000
      );
    } else {
      new Notice(`⚠️ push 结果不明,查 Console`, 5000);
    }
  } catch (e) {
    console.error("[推当前 task v1] 顶层异常:", e);
    new Notice(
      `❌ 脚本异常: ${e.message}\n请打开 Console (Cmd+Opt+I) 看详情`,
      10000
    );
  }
};
