/**
 * QuickAdd UserScript: 📝 快记任务 v2(task md 化版)
 *
 * 触发方式: Cmd+P → 搜「快记任务」 → 回车
 *
 * 行为(v2 - 2026-05-25 task md 化 + 2026-05-26 双层架构升级):
 * 1. 弹优先级选择(🔺 P0 / ⏫ P1 / 🔼 P2 / 🔽 P3)
 * 2. 弹大项目选择(2026-05-26 v0.2.2 加,可选)
 * 3. 弹任务标题输入
 * 4. 创建 `04 Inbox/task/YYYY-MM-DD-<标题>.md`(默认 today: false,进需求池)
 * 5. 自动调 sync.py --task-md --apply 同步到飞书(铁律 #1 例外:单条 CREATE 自动跑)
 *
 * ⚠️ 重要:task 默认 today: false → 不显示在今日 journal「🎯 今日计划」段
 *    想"今天就做这条" → 飞书 app 勾「是否今日」=true + Mac 跑 `sync.py --pull-today --apply`
 *    详见 rules/feishu-project-sync.md「今日 todo 双层架构」section
 *
 * ⚠️ 铁律 #1 例外说明:
 *    本 UserScript 自动跑 `sync.py --apply` 跳过 dry-run + 用户审批。
 *    精确例外条件:单条 CREATE 新 task(无覆盖风险,空白记录新建)。
 *    UPDATE / 批量同步仍走 Cmd+P → 「🎯 同步今日 task 到飞书」5 步 SOP。
 *    详见 rules/feishu-project-sync.md「铁律 #1 飞书例外」section。
 *
 * 关联文件:
 *  - sync.py task md 模式:scripts/feishukanban-ob-sync/sync.py --task-md
 *  - task 模板:03 Resources/素材库/模版/task 模版.md
 *  - base 视图:04 Inbox/task/_task.base
 */

module.exports = async function (params) {
  const { app, obsidian, quickAddApi } = params;
  const { Notice } = obsidian;

  try {
    // ============ Step 1: 弹优先级选择 ============
    const priorityOptions = [
      "🔺 P0  紧急重要",
      "⏫ P1  本周必做",
      "🔼 P2  有空就做",
      "🔽 P3  非计划",
    ];
    const priorityValues = ["P0", "P1", "P2", "P3"];
    const priorityChoice = await quickAddApi.suggester(priorityOptions, priorityValues);
    if (!priorityChoice) {
      new Notice("❌ 已取消", 3000);
      return;
    }

    // ============ Step 2: 弹大项目选择(2026-05-26 v0.2.2 加)============
    // 扫 01 Project/00 进行中/ 下含 frontmatter project_type: 大项目 + status: active 的 md
    const projectFiles = app.vault.getMarkdownFiles().filter(f => {
      if (!f.path.startsWith("01 Project/00 进行中/")) return false;
      const fm = app.metadataCache.getFileCache(f)?.frontmatter;
      if (!fm) return false;
      return fm.project_type === "大项目" && fm.status === "active";
    });

    // 按文件名排序(数字前缀编号自然排序)
    projectFiles.sort((a, b) => a.basename.localeCompare(b.basename, "zh-CN"));

    const projectOptions = [
      "❌ 无 / 跳过(临时小事 / 暂不归类)",
      ...projectFiles.map(f => `📁 ${f.basename}`),
    ];
    const projectValues = [null, ...projectFiles.map(f => f.basename)];

    const projectChoice = await quickAddApi.suggester(projectOptions, projectValues);
    // 注意:projectChoice 可能是 null(用户选"无")或 undefined(用户按 Esc 取消)
    if (projectChoice === undefined) {
      new Notice("❌ 已取消", 3000);
      return;
    }
    console.log("[快记任务 v2] project:", projectChoice || "(无)");

    // ============ Step 3: 弹任务标题输入 ============
    const title = await quickAddApi.inputPrompt("任务标题(简短;后续可加详情)");
    if (!title || !title.trim()) {
      new Notice("❌ 标题为空,已取消", 3000);
      return;
    }
    const titleTrimmed = title.trim();

    // ============ Step 4: 计算北京时间 + 构造路径 ============
    const bjISO = new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 19);
    const bjDate = bjISO.slice(0, 10);
    // 文件名安全字符(替换 Windows/Mac 不允许的字符)
    const safeTitle = titleTrimmed.replace(/[\\\/:*?"<>|]/g, "_");
    const filename = `${bjDate}-${safeTitle}.md`;
    const taskPath = `04 Inbox/task/${filename}`;
    const journalPath = `journals/${bjDate}`;

    console.log("[快记任务 v2] priority:", priorityChoice);
    console.log("[快记任务 v2] title:", titleTrimmed);
    console.log("[快记任务 v2] taskPath:", taskPath);

    // ============ Step 4: 检查文件是否已存在 ============
    if (app.vault.getAbstractFileByPath(taskPath)) {
      new Notice(`❌ 文件已存在: ${filename}\n请改名后再试`, 5000);
      return;
    }

    // ============ Step 5: 内联生成 task md 内容 ============
    // parent_project 行:有项目就填 wikilink,无则空
    const parentProjectLine = projectChoice
      ? `parent_project: "[[${projectChoice}]]"`
      : `parent_project:`;

    const content = `---
priority: ${priorityChoice}
status: todo
today: false
created: ${bjISO}
due:
done_date:
category:
subcategory:
adhd_priority:
estimate_hours:
efficiency:
acceptance:
thinking:
resources:
retrospective:
${parentProjectLine}
parent_subproject:
parent_inspiration:
日志: "[[${journalPath}]]"
feishu_record:
feishu_url:
iteration_week:
iteration_month:
completion_month:
tags:
  - task
---

# ${titleTrimmed}

## 📝 执行概述


## ✅ 验收条件


## 💡 执行思路


## 🔗 相关资料


## 🪞 复盘


## ✅ 完成标记
<!-- dataview TASK 查询读这一行渲染 checkbox + 点击跳飞书(sync 成功后会自动改为 markdown link) -->
- [ ] ${titleTrimmed}
`;

    // ============ Step 6: 创建 task md 文件 ============
    await app.vault.create(taskPath, content);
    new Notice(
      `✅ 已创建 task: ${filename}\n📥 进需求池(默认 today: false,不显示在今日 journal)\n🔄 正在同步飞书...(预计 5-10 秒)`,
      5000
    );

    // ============ Step 7: 调 sync.py --task-md --apply ============
    // 铁律 #1 例外:单条 CREATE 自动 apply,无覆盖风险
    const { exec } = require("child_process");
    const util = require("util");
    const execAsync = util.promisify(exec);

    const vaultRoot = app.vault.adapter.basePath || app.vault.adapter.getBasePath();
    const syncScript = `${vaultRoot}/scripts/feishukanban-ob-sync/sync.py`;
    // shell-escape 路径
    const escapedTaskPath = `${vaultRoot}/${taskPath}`.replace(/"/g, '\\"');
    const syncCmd = `cd "${vaultRoot.replace(/"/g, '\\"')}" && python3 "${syncScript.replace(/"/g, '\\"')}" --task-md "${escapedTaskPath}" --apply`;

    console.log("[快记任务 v2] syncCmd:", syncCmd);

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

    let recordId = null;
    let syncOK = false;
    try {
      const { stdout, stderr } = await execAsync(syncCmd, { timeout: 60000, env: execEnv });
      console.log("[快记任务 v2] sync stdout:", stdout);
      if (stderr) console.warn("[快记任务 v2] sync stderr:", stderr);

      // 从 stdout 抽 record_id
      const recMatch = stdout.match(/record_id:\s*(rec[a-zA-Z0-9]+)/);
      if (recMatch) {
        recordId = recMatch[1];
        syncOK = true;
      }
    } catch (e) {
      console.error("[快记任务 v2] sync 失败:", e);
      new Notice(
        `⚠️ 飞书同步失败(task md 已建,稍后手动跑同步):\n${e.message || e}`,
        10000
      );
      // 继续 Step 8(journal wikilink)
    }

    if (syncOK) {
      new Notice(
        `✅ 飞书同步成功!\nrecord_id: ${recordId}\n💾 task md frontmatter 已更新\n📥 待在需求池(飞书勾「是否今日」+ pull-today 才进 journal)`,
        5000
      );
    }

    // Step 8(写 wikilink 到 journal)已删除(2026-05-26):
    // 改为依赖 journal 内 dataview TASK 查询自动渲染 task md
    // 理由:wikilink + dataview 渲染冗余(同一个 task 显示两次:checkbox + 圆点 wikilink)
    // dataview 查询会自动扫 04 Inbox/task/ 下所有 priority 匹配的 task md 渲染 checkbox

    console.log("[快记任务 v2] 全流程完成");
  } catch (e) {
    console.error("[快记任务 v2] 顶层异常:", e);
    new Notice(
      `❌ 脚本异常: ${e.message}\n请打开 Console (Cmd+Opt+I) 看详情`,
      10000
    );
  }
};
