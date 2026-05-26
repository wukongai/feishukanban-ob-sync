/**
 * QuickAdd UserScript: ✅ 完成当前 task + sync 飞书
 *
 * 触发方式: Cmd+P → 搜「完成 task」/「complete task」 → 回车
 * 前置条件: current note 必须是 `04 Inbox/task/YYYY-MM-DD-<标题>.md` 路径下的 task md
 *
 * 行为(v1 - 2026-05-26):
 * 1. 检查 current note 是否在 04 Inbox/task/ 下
 * 2. 检查 frontmatter 有 feishu_record(说明这个 task 已 sync 过飞书)
 * 3. 改 frontmatter status: done + done_date: today
 * 4. 改 inline checkbox `- [ ]` / `- [/]` → `- [x]` + 加 `✅ today`(如还没勾)
 * 5. 调 sync.py --task-md --apply 走 UPDATE 飞书(铁律 #1 飞书例外扩展)
 *
 * 铁律 #1 飞书例外(2026-05-26 第二轮扩展):
 * - 原例外:仅"单条 CREATE 新 task"自动 apply
 * - 新增:"单条 UPDATE 完成 task 状态"也自动 apply(OB 端主导,不覆盖飞书后台手编)
 *
 * 参考 quickadd-快记任务-v2-task-md.js / quickadd-拉今日todo.js 同款 exec 模式
 */

module.exports = async function (params) {
  const { app, obsidian } = params;
  const { Notice } = obsidian;

  try {
    // ============ Step 1: 检查 current note ============
    const activeFile = app.workspace.getActiveFile();
    if (!activeFile) {
      new Notice(`❌ 没有打开的 task md`, 5000);
      return;
    }
    if (!activeFile.path.startsWith("04 Inbox/task/")) {
      new Notice(
        `❌ 当前文件不是 task md(必须在 04 Inbox/task/ 下)\n当前:${activeFile.path}`,
        6000
      );
      return;
    }

    console.log("[完成 task v1] 当前文件:", activeFile.path);

    // ============ Step 2: 读 frontmatter + inline ============
    const content = await app.vault.read(activeFile);

    // 抽 frontmatter
    const fmMatch = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n/);
    if (!fmMatch) {
      new Notice(`❌ task md 没有 frontmatter,无法处理`, 5000);
      return;
    }
    const fmText = fmMatch[1];

    // 抽 feishu_record(必填,说明已 sync 过飞书才能 UPDATE)
    const recMatch = fmText.match(/^feishu_record:\s*(.+?)\s*$/m);
    const feishuRecord = recMatch ? recMatch[1].trim().replace(/^['"]|['"]$/g, "") : "";
    if (!feishuRecord || feishuRecord.startsWith("#")) {
      new Notice(
        `❌ task md 没有 feishu_record 字段(应该先 sync 创建飞书 record)\n建议:跑 sync.py --task-md 创建新 record`,
        7000
      );
      return;
    }

    // 抽 status
    const statusMatch = fmText.match(/^status:\s*(.+?)\s*$/m);
    const currentStatus = statusMatch ? statusMatch[1].trim().toLowerCase() : "";
    if (currentStatus === "done") {
      new Notice(
        `⚠️ task 已经是 done 状态,无需再完成\n如果飞书没同步,跑 sync.py --task-md --apply 手动同步`,
        6000
      );
      return;
    }

    console.log("[完成 task v1] feishu_record:", feishuRecord);
    console.log("[完成 task v1] 当前 status:", currentStatus);

    // ============ Step 3: 计算今天日期(北京时间)============
    const bjISO = new Date(Date.now() + 8 * 3600 * 1000)
      .toISOString()
      .slice(0, 19);
    const bjDate = bjISO.slice(0, 10);

    // ============ Step 4: 改 frontmatter ============
    let newContent = content;

    // 改 status: 任意 → done
    if (statusMatch) {
      newContent = newContent.replace(
        /^status:\s*.+?\s*$/m,
        `status: done`
      );
    }

    // 改 done_date: 空 → today
    const doneDateMatch = fmText.match(/^done_date:\s*(.*)\s*$/m);
    if (doneDateMatch && !doneDateMatch[1].trim()) {
      // 空字段 → 填 today
      newContent = newContent.replace(
        /^done_date:\s*$/m,
        `done_date: ${bjDate}`
      );
    } else if (!doneDateMatch) {
      // 没有 done_date 字段 → 在 frontmatter 末尾追加
      // (跳过,因为 task 模板已有这个字段,这种情况罕见)
    }

    // ============ Step 5: 改 inline checkbox ============
    // 找「## ✅ 完成标记」section 下方的 `- [ ]` / `- [/]` 行,改为 `- [x] ... ✅ <today>`
    // pattern: `- [ ]` 或 `- [/]` 后跟内容,可能已有 markdown link
    const checkboxRegex = /^(- \[)( |\/)(\] .+?)(\s*✅ \d{4}-\d{2}-\d{2})?$/m;
    const cbMatch = newContent.match(checkboxRegex);
    if (cbMatch) {
      // 拆开:`- [` + ' '|'/' + `] <body>` + 可选 ✅
      const body = cbMatch[3];
      // 重新拼接 — done + ✅ today
      const cleanBody = body.replace(/\s*✅ \d{4}-\d{2}-\d{2}\s*$/, ""); // 去掉旧 ✅
      const newCheckboxLine = `- [x${cleanBody} ✅ ${bjDate}`;
      newContent = newContent.replace(checkboxRegex, newCheckboxLine);
    }
    // 如果没找到 checkbox,跳过(可能 task md 没有「## ✅ 完成标记」section)

    // ============ Step 6: 写文件 ============
    await app.vault.modify(activeFile, newContent);
    new Notice(
      `✅ 已改 frontmatter status:done + done_date:${bjDate}\n🔄 正在 sync 飞书 UPDATE...(5-10 秒)`,
      4000
    );

    // ============ Step 7: 调 sync.py --task-md --apply ============
    const { exec } = require("child_process");
    const util = require("util");
    const execAsync = util.promisify(exec);

    const vaultRoot =
      app.vault.adapter.basePath || app.vault.adapter.getBasePath();
    const syncScript = `${vaultRoot}/scripts/feishukanban-ob-sync/sync.py`;
    const escapedTaskPath = `${vaultRoot}/${activeFile.path}`.replace(/"/g, '\\"');
    const syncCmd = `cd "${vaultRoot.replace(
      /"/g,
      '\\"'
    )}" && python3 "${syncScript.replace(/"/g, '\\"')}" --task-md "${escapedTaskPath}" --apply`;

    console.log("[完成 task v1] syncCmd:", syncCmd);

    // 注入 PATH(2026-05-26 v0.2.3 修复 — feishu-cli 找不到)
    const userPaths = [
      `${process.env.HOME}/.local/bin`,
      "/usr/local/bin",
      "/opt/homebrew/bin",
    ];
    const execEnv = {
      ...process.env,
      PATH: `${userPaths.join(":")}:${process.env.PATH || ""}`,
    };

    let syncOK = false;
    let recordId = null;
    try {
      const { stdout, stderr } = await execAsync(syncCmd, { timeout: 60000, env: execEnv });
      console.log("[完成 task v1] sync stdout:", stdout);
      if (stderr) console.warn("[完成 task v1] sync stderr:", stderr);

      // 看 stdout 是否含 UPDATE 成功标志
      if (stdout.includes("UPDATE 成功") || stdout.includes("✅ UPDATE")) {
        syncOK = true;
        const recMatch2 = stdout.match(/record_id:\s*(rec[a-zA-Z0-9]+)/);
        if (recMatch2) recordId = recMatch2[1];
      }
    } catch (e) {
      console.error("[完成 task v1] sync 失败:", e);
      new Notice(
        `⚠️ 飞书同步失败(OB frontmatter 已改,需要手动跑 sync):\n${e.message || e}`,
        10000
      );
      return;
    }

    // ============ Step 8: Notice 报告 ============
    if (syncOK) {
      new Notice(
        `✅ task 完成!\n📝 OB frontmatter: status=done + done_date=${bjDate}\n☁️ 飞书 UPDATE 成功(record: ${recordId || feishuRecord})\n📌 全闭环完成`,
        6000
      );
    } else {
      new Notice(
        `⚠️ OB 已改但飞书 UPDATE 不确定(看 Console)\nsync stdout 没匹配到 UPDATE 成功标志`,
        8000
      );
    }
  } catch (e) {
    console.error("[完成 task v1] 顶层异常:", e);
    new Notice(
      `❌ 脚本异常: ${e.message}\n请打开 Console (Cmd+Opt+I) 看详情`,
      10000
    );
  }
};
