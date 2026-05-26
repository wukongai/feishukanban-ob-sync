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
    const execAsync = util.promisify(exec);

    const vaultRoot =
      app.vault.adapter.basePath || app.vault.adapter.getBasePath();
    const syncScript = `${vaultRoot}/scripts/feishukanban-ob-sync/sync.py`;
    const syncCmd = `cd "${vaultRoot.replace(
      /"/g,
      '\\"'
    )}" && python3 "${syncScript.replace(/"/g, '\\"')}" --pull-today --apply`;

    console.log("[拉今日 todo v1] syncCmd:", syncCmd);

    new Notice(`🔄 正在拉飞书今日 todo...(预计 5-10 秒)`, 3000);

    // ============ Step 2: 跑 sync.py ============
    let stdout = "";
    let stderr = "";
    try {
      const result = await execAsync(syncCmd, { timeout: 60000 });
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

    // ============ Step 4: 弹 Notice 报告 ============
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
      msg += `👀 刷新今日 journal(Cmd+R)查看「🎯 今日计划」段`;

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
