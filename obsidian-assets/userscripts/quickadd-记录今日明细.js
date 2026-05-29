/**
 * QuickAdd UserScript: 📈 记录今日执行明细 + sync 飞书子表
 *
 * 触发方式: Cmd+P → 搜「记录今日明细」/「log-detail」 → 回车
 * 前置条件: current note 必须是 task md(04 Inbox/task/ 下,frontmatter 有 feishu_record)
 *
 * 行为(v1 - 2026-05-29,v0.6.0 加):
 * 1. 检查当前 task md(含 feishu_record)
 * 2. 弹 suggester 选执行状态(7 态:todo/doing/subdone/done/block/cancel/idea)
 * 3. inputPrompt 输入描述(可选,空 = 只记状态)
 * 4. 写入 task md「## 📈 执行明细」段 — 今日行(同日覆盖)
 * 5. 调 sync.py --task-md --apply 推飞书子表(自动 CREATE 1 条 record)
 * 6. Notice 报告
 *
 * 跟「完成 task」的区别:
 * - 完成 task = 终态记录(status: done 一次性)
 * - 记录今日明细 = 过程记录(每天可以加一条,描述当天的执行情况)
 *
 * 设计参考 quickadd-完成task.js / quickadd-推当前task.js 同款 exec 模式
 */

module.exports = async function (params) {
  const { app, obsidian, quickAddApi } = params;
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

    console.log("[记录今日明细 v1] task:", activeFile.path, "rec:", feishuRecord);

    // Step 2: 弹 suggester 选执行状态(对齐 OB 端 7 态小写)
    const STATUS_OPTIONS = [
      { display: "🔄 Doing — 正在做", value: "doing" },
      { display: "✅ Done — 完成", value: "done" },
      { display: "🟧 SubDone — 部分完成", value: "subdone" },
      { display: "🚧 Block — 卡住", value: "block" },
      { display: "⬜ Todo — 还没开始", value: "todo" },
      { display: "💡 Idea — 仅构思", value: "idea" },
      { display: "❌ cancel — 取消", value: "cancel" },
    ];
    const statusPick = await quickAddApi.suggester(
      STATUS_OPTIONS.map(o => o.display),
      STATUS_OPTIONS.map(o => o.value)
    );
    if (!statusPick) {
      new Notice(`❌ 没选状态,取消`, 3000);
      return;
    }

    // Step 3: 输入描述(可选)
    const description = await quickAddApi.inputPrompt(
      `📈 描述今日执行(可选,Enter 跳过):`,
      "例:写完 push-all-today 修复,跑了 dry-run 验证 OK",
      ""
    );

    // Step 4: 算今天日期(北京时间)
    const today = new Date(Date.now() + 8 * 3600 * 1000)
      .toISOString()
      .slice(0, 10);

    // 构造新行
    let newLine = `- ${today} | ${statusPick}`;
    if (description && description.trim()) {
      newLine += ` | review=${description.trim()}`;
    }

    // Step 5: 写入 task md「## 📈 执行明细」段
    // - 段存在:删除同日老行 + 追加新行(同日覆盖语义,跟 sync.py 一致)
    // - 段不存在:在「## ✅ 完成标记」前插入完整段
    let newContent;
    const sectionRegex = /^(## +📈 +执行明细\s*\n)((?:.*\n)*?)(?=\n## |\n*$)/m;
    const secMatch = content.match(sectionRegex);
    if (secMatch) {
      const header = secMatch[1];
      // 段内容: 滤掉今日老行(包括注释行 / 空行也保留前面 placeholder)
      const oldBody = secMatch[2];
      const sameDayRegex = new RegExp(`^\\- ${today}\\s*\\|.*$`, "gm");
      const filteredBody = oldBody.replace(sameDayRegex, "").replace(/\n{3,}/g, "\n\n");
      // 在段末尾追加新行(确保有空行分隔)
      const trimmed = filteredBody.replace(/\s+$/, "");
      const newBody = trimmed ? `${trimmed}\n${newLine}\n` : `\n${newLine}\n`;
      newContent = content.replace(sectionRegex, `${header}${newBody}`);
    } else {
      // 段不存在 → 在「## ✅ 完成标记」之前插入
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
      `✅ 已写本地: ${today} | ${statusPick}\n🔄 正在 sync 飞书子表...(3-8 秒)`,
      4000
    );

    // Step 6: 调 sync.py --task-md --apply 推飞书子表
    const { exec } = require("child_process");
    const util = require("util");
    const execAsync = util.promisify(exec);

    const vaultRoot =
      app.vault.adapter.basePath || app.vault.adapter.getBasePath();
    const syncScript = "__SYNC_PY_ABS_PATH__";
    const absPath = `${vaultRoot}/${activeFile.path}`;
    const syncCmd = `python3 "${syncScript.replace(/"/g, '\\"')}" --vault "${vaultRoot.replace(/"/g, '\\"')}" --task-md "${absPath.replace(/"/g, '\\"')}" --apply`;

    console.log("[记录今日明细 v1] syncCmd:", syncCmd);

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
      console.log("[记录今日明细 v1] sync stdout:", stdout);
      if (stderr) console.warn("[记录今日明细 v1] sync stderr:", stderr);

      // 解析明细推送结果(v0.6.0 sync.py 输出 "CREATE X / UPDATE Y / SKIP Z" 行)
      const detailMatch = stdout.match(/CREATE (\d+) \/ UPDATE (\d+) \/ SKIP (\d+) \/ ERROR (\d+)/);
      if (detailMatch) {
        const [, c, u, s, e] = detailMatch;
        const action = parseInt(c) > 0 ? "CREATE" : (parseInt(u) > 0 ? "UPDATE" : "SKIP");
        new Notice(
          `✅ 今日明细已推飞书子表\n📈 ${today} | ${statusPick}\n☁️ ${action} (CREATE ${c} / UPDATE ${u} / SKIP ${s})`,
          6000
        );
      } else {
        new Notice(
          `⚠️ 本地已写,飞书推送结果不明(查 Console)\n看 stdout 是否有 "明细" 字样`,
          7000
        );
      }
    } catch (e) {
      console.error("[记录今日明细 v1] sync 失败:", e);
      new Notice(
        `⚠️ 本地已写,飞书 sync 失败:\n${e.message || e}`,
        10000
      );
    }
  } catch (e) {
    console.error("[记录今日明细 v1] 顶层异常:", e);
    new Notice(
      `❌ 脚本异常: ${e.message}\n打开 Console (Cmd+Opt+I) 看详情`,
      10000
    );
  }
};
