/**
 * QuickAdd Macro 第 2 步 — 新建布丁需求 后处理(backlog → task md 自动镜像)
 *
 * 触发链:
 *   Cmd+P → 「🎮 新建布丁需求」 Macro
 *     ├─ Step 1: Template(套「好奇猫开发需求模版.md」+ 文件名 idea-{{NAME}}.md
 *     │           + folder = 01 Project/00 进行中/应用产品/布丁/zhixing-game-docs/backlog/)
 *     │   ↓ 经 symlink 落到 ~/Documents/CodingProject/zhixing-game/docs/backlog/
 *     └─ Step 2: UserScript(本文件)→ exec backlog_to_task.py 中间件
 *                                  → 在 04 Inbox/task/ 落对应 task md(today=false 进需求池)
 *
 * 中间件:~/Documents/CodingProject/feishukanban-ob-sync/scripts/backlog_to_task.py
 * 紧急关闭:env BACKLOG_TO_TASK_DISABLE=1 export 一下,再 reload Obsidian
 *
 * 失败模式:exec 失败弹 Notice 但不抛错,不影响 backlog md 已创建的事实
 */

module.exports = async (params) => {
  const { app, obsidian } = params;
  const { exec } = require("child_process");
  const path = require("path");

  // 拿 Macro 第 1 步刚创建(且默认打开)的 backlog md
  const activeFile = app.workspace.getActiveFile();
  if (!activeFile) {
    new obsidian.Notice("⚠️ 拿不到当前文件,task 镜像跳过", 6000);
    return;
  }

  // vault 内相对路径 → 系统绝对路径
  const vaultBasePath = app.vault.adapter.basePath;
  const relPath = activeFile.path;
  const absPath = path.join(vaultBasePath, relPath);

  // 兜底:只在 backlog 目录(经 symlink)下才触发,避免误调
  if (!relPath.includes("zhixing-game-docs/backlog/")) {
    // 用户跑这个 Macro 但当前文件不是 backlog → 静默跳过
    return;
  }

  // 中间件路径(用户机器固定)
  const home = process.env.HOME || "/Users/aim5";
  const middleware = path.join(
    home,
    "Documents/CodingProject/feishukanban-ob-sync/scripts/backlog_to_task.py"
  );

  const cmd = `python3 "${middleware}" --backlog "${absPath}" --apply`;

  new obsidian.Notice("🟡 镜像到 task 看板中...", 3000);

  exec(cmd, { timeout: 15000 }, (err, stdout, stderr) => {
    if (err) {
      console.error("[backlog_to_task] 失败:", err.message);
      console.error("[backlog_to_task] stderr:", stderr);
      new obsidian.Notice(
        `❌ task 镜像失败:\n${err.message.slice(0, 150)}\n(查看 console)`,
        10000
      );
      return;
    }
    const lastLine = stdout.trim().split("\n").pop() || "完成";
    new obsidian.Notice(`✅ task 镜像完成\n${lastLine}`, 6000);
  });
};
