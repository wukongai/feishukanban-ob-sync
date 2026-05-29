/**
 * QuickAdd UserScript: 📥 拉今日 todo
 *
 * 触发方式: Cmd+P → 搜「拉今日 todo」/「pull-today」 → 回车
 *
 * 行为(v1 - 2026-05-26):
 * 1. 调 `sync.py --pull-today --apply` 直接同步(铁律 #1 例外:本地 frontmatter 写,不写飞书)
 * 2. 解析 stdout 报告(set true 数 / set false 数 / 飞书有 OB 无 数)
 * 3. 弹 Notice 显示结果
 *
 * 设计权衡(为什么默认 --apply 不走 dry-run):
 * - sync.py --pull-today 只改 OB task md frontmatter,不写飞书(飞书侧只读)
 * - 影响范围 ≤ 几个 task md 的 today 字段,完全可逆(直接改 frontmatter 回滚)
 * - 这不是铁律 #1 "sync apply 写飞书生产" 的核心保护场景
 *
 * 参考 quickadd-快记任务-v2-task-md.js 同款 exec 模式
 */

module.exports = async function (params) {
  const { app, obsidian } = params;
  const { Notice } = obsidian;

  try {
    // ============ Step 1: 构造命令 ============
    const { exec } = require("child_process");
    const util = require("util");
    const path = require("path");
    const execAsync = util.promisify(exec);

    const vaultRoot =
      app.vault.adapter.basePath || app.vault.adapter.getBasePath();
    // v0.3.4: install.sh 装的时候 sed 替换占位符为 sync.py 绝对路径
    // (v0.3.2 用 __filename 推导失败 — Obsidian QuickAdd 上下文里 __filename 指向
    //  /Applications/Obsidian.app/Contents/Resources/electron.asar/,不是 vault 内 .js 真实位置)
    const syncScript = "__SYNC_PY_ABS_PATH__";
    // v0.3.1: 用 --vault 替代 `cd && python3`,命令开头是 python3,Claude Code allowlist 友好
    const syncCmd = `python3 "${syncScript.replace(/"/g, '\\"')}" --vault "${vaultRoot.replace(/"/g, '\\"')}" --pull-today --apply`;

    console.log("[拉今日 todo v1] syncCmd:", syncCmd);

    // ============ 注入 PATH(2026-05-26 v0.2.3 修复)============
    // Obsidian GUI 启动时不继承 shell 的 PATH(.zshrc 不会被 source),
    // 导致 feishu-cli(装在 ~/.local/bin/)找不到 → FileNotFoundError
    // 修复:exec 时显式注入用户级 PATH(覆盖 ~/.local/bin / homebrew 等常见位置)
    const userPaths = [
      `${process.env.HOME}/.local/bin`,     // pipx / uv tool / 用户 Python tools
      "/usr/local/bin",                      // Intel Mac homebrew
      "/opt/homebrew/bin",                   // Apple Silicon homebrew
    ];
    const execEnv = {
      ...process.env,
      PATH: `${userPaths.join(":")}:${process.env.PATH || ""}`,
      // v0.3.3: 强制北京时区,sync.py 的 datetime.now() 不再受 shell TZ=PDT 影响
      TZ: "Asia/Shanghai",
    };

    new Notice(`🔄 正在拉飞书今日 todo...(预计 5-10 秒)`, 3000);

    // ============ Step 2: 跑 sync.py ============
    let stdout = "";
    let stderr = "";
    try {
      const result = await execAsync(syncCmd, { timeout: 60000, env: execEnv });
      stdout = result.stdout || "";
      stderr = result.stderr || "";
      console.log("[拉今日 todo v1] stdout:", stdout);
      if (stderr) console.warn("[拉今日 todo v1] stderr:", stderr);
    } catch (e) {
      console.error("[拉今日 todo v1] 跑 sync.py 失败:", e);
      new Notice(
        `❌ 拉今日 todo 失败:\n${e.message || e}\n查 Console (Cmd+Opt+I)`,
        10000
      );
      return;
    }

    // ============ Step 3: 解析 stdout 摘要 ============
    // 期望 stdout 含:
    //   📋 计划摘要:
    //     ➡️  设 today=true:    N 条
    //     ⬅️  设 today=false:   M 条
    //     ⏭️  已是 today,跳过: K 条
    //     ⚠️  飞书有 OB 无:    P 条
    let setTrueCount = 0;
    let setFalseCount = 0;
    let skipCount = 0;
    let missingCount = 0;
    let failCount = 0;

    const setTrueMatch = stdout.match(/设 today=true:\s*(\d+)\s*条/);
    if (setTrueMatch) setTrueCount = parseInt(setTrueMatch[1], 10);

    const setFalseMatch = stdout.match(/设 today=false:\s*(\d+)\s*条/);
    if (setFalseMatch) setFalseCount = parseInt(setFalseMatch[1], 10);

    const skipMatch = stdout.match(/已是 today,跳过:\s*(\d+)\s*条/);
    if (skipMatch) skipCount = parseInt(skipMatch[1], 10);

    const missingMatch = stdout.match(/飞书有 OB 无:\s*(\d+)\s*条/);
    if (missingMatch) missingCount = parseInt(missingMatch[1], 10);

    const failMatch = stdout.match(/(\d+)\s*成功\s*\/\s*(\d+)\s*失败/);
    if (failMatch) failCount = parseInt(failMatch[2], 10);

    // ============ Step 4: 自动刷新今日 journal(2026-05-26 v0.2.4 加 / v0.4.0 根治升级)============
    // 痛点:sync.py 外部改 frontmatter 后,Obsidian metadata cache 有延迟,
    // dataview 接到 reload 命令时还是用老 cache → 即使调了 rebuild,task 也不显示新状态
    // 根治链路:
    //   等 1.5s(给 fs watcher + metadata cache 跑完)
    //   → 调多个可能的 dataview command ID(版本兼容)
    //   → 直接调 dataview plugin internal API(index reload)
    //   → 重新打开 today journal 触发 preview rerender
    const bjDate = new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10);
    const todayJournalPath = `journals/${bjDate}.md`;
    const journalFile = app.vault.getAbstractFileByPath(todayJournalPath);

    // ⭐ 关键:等 fs watcher + metadata cache 同步(1.5s 测试稳)
    await new Promise(r => setTimeout(r, 1500));

    try {
      // 方法 A:调 Dataview 全局 rebuild 命令 — 试多个 ID(不同 dataview 版本不同)
      const dvCommandIds = [
        "dataview:dataview-drop-cache-and-reload",
        "dataview:dataview-force-refresh-views",
        "dataview:dataview-rebuild-current-view",
        "dataview:dataview-rebuild",
        "dataview:rebuild",
      ];
      let dvFired = false;
      for (const cmdId of dvCommandIds) {
        if (app.commands.findCommand?.(cmdId)) {
          app.commands.executeCommandById(cmdId);
          dvFired = true;
          console.log(`[拉今日 todo v1] dataview command 触发: ${cmdId}`);
          break;
        }
      }
      if (!dvFired) console.warn("[拉今日 todo v1] 所有 dataview command ID 都未找到");

      // 方法 B:直接调 dataview plugin internal API 强制 reindex
      // API 名可能不同 dataview 版本不同,逐个 try
      const dv = app.plugins.plugins["dataview"];
      if (dv) {
        if (typeof dv.index?.reload === "function") {
          await dv.index.reload();
          console.log("[拉今日 todo v1] dv.index.reload() 触发");
        } else if (typeof dv.index?.touch === "function" && journalFile) {
          // touch 单个文件 — 强制重 index
          dv.index.touch(journalFile.path);
          console.log(`[拉今日 todo v1] dv.index.touch(${todayJournalPath}) 触发`);
        }
      } else {
        console.warn("[拉今日 todo v1] dataview plugin 未启用");
      }

      // 方法 C:对所有打开 today journal 的 leaf,触发 preview rerender
      if (journalFile) {
        const leaves = app.workspace.getLeavesOfType("markdown");
        for (const leaf of leaves) {
          if (leaf.view?.file?.path === todayJournalPath) {
            if (leaf.view.previewMode?.rerender) {
              leaf.view.previewMode.rerender(true);
              console.log("[拉今日 todo v1] preview rerender 触发");
            }
          }
        }
      }

      // 方法 D(v0.4.0 Step 3 终极兜底):重启 dataview plugin
      // 如果 A/B/C 都不生效 — disable + enable plugin 强制完全 reinit
      // 所有 task md 重新 index,所有 dataview 块重新 query
      // 视觉效果:dataview 块短暂 "Loading..." 1-2 秒,然后正确渲染
      try {
        if (app.plugins.plugins["dataview"] && app.plugins.disablePlugin && app.plugins.enablePlugin) {
          console.log("[拉今日 todo v1] 终极兜底:disable+enable dataview plugin");
          await app.plugins.disablePlugin("dataview");
          await new Promise(r => setTimeout(r, 300));
          await app.plugins.enablePlugin("dataview");
          console.log("[拉今日 todo v1] dataview plugin 重启完成 — 全量重 index");
        }
      } catch (e) {
        console.warn("[拉今日 todo v1] dataview 重启兜底失败:", e);
      }
    } catch (e) {
      console.warn("[拉今日 todo v1] 自动刷新失败(不阻塞流程):", e);
    }

    // ============ Step 5: 弹 Notice 报告 ============
    const totalChanged = setTrueCount + setFalseCount;

    if (totalChanged === 0 && missingCount === 0) {
      new Notice(
        `✅ OB ↔ 飞书 today 已对齐\n无需更新(跳过 ${skipCount} 条已是 today)`,
        5000
      );
    } else {
      let msg = `✅ 拉今日 todo 完成\n`;
      if (setTrueCount > 0)
        msg += `➡️ 设 today=true: ${setTrueCount} 条\n`;
      if (setFalseCount > 0)
        msg += `⬅️ 设 today=false: ${setFalseCount} 条\n`;
      if (skipCount > 0)
        msg += `⏭️ 跳过(已是 today): ${skipCount} 条\n`;
      if (missingCount > 0)
        msg += `⚠️ 飞书有 OB 无: ${missingCount} 条(去 Cmd+P 手建)\n`;
      if (failCount > 0)
        msg += `❌ 失败: ${failCount} 条(看 Console)\n`;
      msg += `👀 今日 journal 已自动刷新`;

      new Notice(msg, 10000);
    }
  } catch (e) {
    console.error("[拉今日 todo v1] 顶层异常:", e);
    new Notice(
      `❌ 脚本异常: ${e.message}\n请打开 Console (Cmd+Opt+I) 看详情`,
      10000
    );
  }
};
