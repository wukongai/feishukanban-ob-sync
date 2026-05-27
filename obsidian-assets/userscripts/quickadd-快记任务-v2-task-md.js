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
 * 6. 日期上下文(2026-05-26 v0.3.1 加跨日支持):
 *    - 当前打开 journal(`journals/YYYY-MM-DD.md`)→ 用 journal 日期作为文件名前缀 / today_history / 日志字段
 *    - 其他场景 → fallback 北京时间(原行为)
 *    详见 docs/handoff/OB对接/2026-05-26-userscript-跨日-handoff.md
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
 *  - sync.py task md 模式:userscripts/ 上一级的 sync.py --task-md(v0.3.2 起 __filename 自适应)
 *  - task 模板:03 Resources/素材库/模版/task 模版.md
 *  - base 视图:04 Inbox/task/_task.base
 */

// 算 dateContext:优先用当前打开 journal 日期(跨日工作友好),fallback 北京时间
// 详见 docs/handoff/OB对接/2026-05-26-userscript-跨日-handoff.md
function getDateContext(app) {
  // 1) 优先:当前打开的 journal 日期
  const active = app.workspace.getActiveFile();
  if (active && active.path.startsWith("journals/")
      && /^\d{4}-\d{2}-\d{2}\.md$/.test(active.name)) {
    return active.name.slice(0, 10);  // "YYYY-MM-DD"
  }
  // 2) fallback:北京时间(原 bjDate 行为)
  return new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10);
}

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

    // ============ Step 2.5: 二级菜单 + override 处理(2026-05-26 v0.2.4 加)============
    // 调 sync.py --resolve-project 查飞书侧的:
    //   - override_map 命中(如 zhixinggame → 布丁开发)
    //   - 当前一级在飞书「产品项目表」下的子 records(二级菜单)
    // 命中 override → 不弹二级,标题加【effective_name】
    // 有二级 record → 弹二级 suggester,选了就标题加【子 name】,跳过保持一级
    // 都没 → 无二级菜单,标题不加前缀
    //
    // 设计要点:
    // - 二级数据从飞书动态读(不在 config 维护重复列表),加新二级只改飞书
    // - resolve-project 失败 → 降级走一级原值,不阻塞 task 创建(鲁棒性)
    let chosenParentName = projectChoice;  // 最终写到 frontmatter 的项目名
    let titlePrefix = "";                  // 加在标题前的前缀(含【】)

    if (projectChoice) {
      // 提前准备 exec(同 Step 7 用一份,避免重复)
      const { exec: execEarly } = require("child_process");
      const utilEarly = require("util");
      const pathEarly = require("path");
      const execAsyncEarly = utilEarly.promisify(execEarly);
      const vaultRootEarly = app.vault.adapter.basePath || app.vault.adapter.getBasePath();
      // v0.3.2: __filename 自适应,不依赖 install.sh 装在 vault 哪里
      const syncScriptEarly = pathEarly.resolve(pathEarly.dirname(__filename), "..", "sync.py");
      const userPathsEarly = [
        `${process.env.HOME}/.local/bin`,
        "/usr/local/bin",
        "/opt/homebrew/bin",
      ];
      const execEnvEarly = {
        ...process.env,
        PATH: `${userPathsEarly.join(":")}:${process.env.PATH || ""}`,
        // v0.3.3: 强制北京时区,sync.py 的 datetime.now() 不再受 shell TZ=PDT 影响
        TZ: "Asia/Shanghai",
      };

      try {
        const escapedChoice = projectChoice.replace(/"/g, '\\"');
        // v0.3.1: 用 --vault 替代 `cd && python3`,命令开头是 python3,Claude Code allowlist 友好
        const resolveCmd = `python3 "${syncScriptEarly.replace(/"/g, '\\"')}" --vault "${vaultRootEarly.replace(/"/g, '\\"')}" --resolve-project "${escapedChoice}"`;
        console.log("[快记任务 v2] resolveCmd:", resolveCmd);
        const { stdout: resolveStdout } = await execAsyncEarly(resolveCmd, {
          timeout: 15000,
          env: execEnvEarly,
        });
        // stdout 第一行 / 最后一行可能是 JSON,容错地取最后一个 { 开头的行
        const lines = resolveStdout.trim().split("\n").filter(Boolean);
        const jsonLine = lines.reverse().find(l => l.trim().startsWith("{"));
        const resolved = jsonLine ? JSON.parse(jsonLine) : null;
        console.log("[快记任务 v2] resolved:", resolved);

        if (resolved && resolved.override_hit) {
          // override 命中(如 zhixinggame → 布丁开发)
          chosenParentName = resolved.effective_name;
          titlePrefix = `【${resolved.effective_name}】`;
          new Notice(
            `📌 项目映射: ${projectChoice} → ${resolved.effective_name}\n标题将加前缀: ${titlePrefix}`,
            3000
          );
        } else if (resolved && resolved.subprojects && resolved.subprojects.length > 0) {
          // 有子 record → 弹二级 suggester
          const subOptions = [
            `❌ 跳过 / 用一级「${projectChoice}」(标题不加前缀)`,
            ...resolved.subprojects.map(s => `📂 ${s.name}`),
          ];
          const subValues = [null, ...resolved.subprojects.map(s => s.name)];
          const subChoice = await quickAddApi.suggester(subOptions, subValues);
          if (subChoice === undefined) {
            new Notice("❌ 已取消", 3000);
            return;
          }
          if (subChoice) {
            chosenParentName = subChoice;
            titlePrefix = `【${subChoice}】`;
            console.log("[快记任务 v2] 选了二级:", subChoice);
          } else {
            console.log("[快记任务 v2] 跳过二级,保持一级:", projectChoice);
          }
        }
        // 都没 → 一级无 override 无子 → 不加前缀,frontmatter 写一级原值
      } catch (e) {
        console.warn("[快记任务 v2] resolve-project 失败,降级走一级:", e);
        new Notice(
          `⚠️ 二级菜单查询失败(降级用一级「${projectChoice}」,不加前缀)\n详情看 Console`,
          4000
        );
        // chosenParentName / titlePrefix 保持初始值
      }
    }

    // ============ Step 2.7: 是否今日(2026-05-26 v0.2.4 加)============
    // 默认 today=false(进需求池,飞书侧自己挑日子)
    // 选 today=true → frontmatter today: true + sync.py CREATE 时同步到飞书「是否今日」=true
    // 免去"先创建 → 再去飞书 app 勾今日"的双步操作
    const todayOptions = [
      "📥 进需求池(默认,后续在飞书勾今日)",
      "⭐ 今日(立即排进今日 journal)",
    ];
    const todayValues = [false, true];
    const isToday = await quickAddApi.suggester(todayOptions, todayValues);
    if (isToday === undefined) {
      new Notice("❌ 已取消", 3000);
      return;
    }
    console.log("[快记任务 v2] today:", isToday);

    // ============ Step 3: 弹任务标题输入 ============
    const title = await quickAddApi.inputPrompt("任务标题(简短;后续可加详情)");
    if (!title || !title.trim()) {
      new Notice("❌ 标题为空,已取消", 3000);
      return;
    }
    const titleTrimmed = `${titlePrefix}${title.trim()}`;

    // ============ Step 4: 计算日期上下文 + 北京时间 + 构造路径 ============
    // dateContext 优先用「当前打开 journal 日期」(跨日工作支持),fallback 北京时间
    // bjISO 保留(用于 created 完整时间戳;时间部分始终北京时间)
    const bjISO = new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 19);
    const dateContext = getDateContext(app);
    // created:日期部分用 dateContext,时间部分用北京时间 HH:mm:ss
    const createdISO = `${dateContext}T${bjISO.slice(11)}`;
    // 文件名安全字符(替换 Windows/Mac 不允许的字符)
    const safeTitle = titleTrimmed.replace(/[\\\/:*?"<>|]/g, "_");
    const filename = `${dateContext}-${safeTitle}.md`;
    const taskPath = `04 Inbox/task/${filename}`;
    const journalPath = `journals/${dateContext}`;

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
    // 注意:用 chosenParentName(可能是一级 / 二级名 / override 目标),不是原 projectChoice
    const parentProjectLine = chosenParentName
      ? `parent_project: "[[${chosenParentName}]]"`
      : `parent_project:`;

    // today_history 事件流(v0.3.0):today=true 时立即 init 为 [今日],今日 journal 才能查到
    // 这里用 dateContext(支持跨日:journal 触发用 journal 日期 / 否则北京时间)
    const todayHistoryInit = isToday ? `[${dateContext}]` : `[]`;
    const content = `---
priority: ${priorityChoice}
status: todo
today: ${isToday}
today_history: ${todayHistoryInit}
created: ${createdISO}
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
    const todayBanner = isToday
      ? "⭐ 今日 task(today: true,会进今日 journal「🎯 今日计划」段)"
      : "📥 进需求池(today: false,飞书勾今日 + pull-today 才进 journal)";
    new Notice(
      `✅ 已创建 task: ${filename}\n${todayBanner}\n🔄 正在同步飞书...(预计 5-10 秒)`,
      5000
    );

    // ============ Step 7: 调 sync.py --task-md --apply ============
    // 铁律 #1 例外:单条 CREATE 自动 apply,无覆盖风险
    const { exec } = require("child_process");
    const util = require("util");
    const path = require("path");
    const execAsync = util.promisify(exec);

    const vaultRoot = app.vault.adapter.basePath || app.vault.adapter.getBasePath();
    // v0.3.2: __filename 自适应,不依赖 install.sh 装在 vault 哪里
    const syncScript = path.resolve(path.dirname(__filename), "..", "sync.py");
    // shell-escape 路径
    const escapedTaskPath = `${vaultRoot}/${taskPath}`.replace(/"/g, '\\"');
    // v0.3.1: 用 --vault 替代 `cd && python3`,命令开头是 python3,Claude Code allowlist 友好
    const syncCmd = `python3 "${syncScript.replace(/"/g, '\\"')}" --vault "${vaultRoot.replace(/"/g, '\\"')}" --task-md "${escapedTaskPath}" --apply`;

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
      // v0.3.3: 强制北京时区,sync.py 的 datetime.now() 不再受 shell TZ=PDT 影响
      TZ: "Asia/Shanghai",
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
      const syncBanner = isToday
        ? "⭐ 飞书「是否今日」已同步勾选 → 跑 pull-today 可写入今日 journal"
        : "📥 task 在需求池;后续在飞书勾「是否今日」+ pull-today 才进 journal";
      new Notice(
        `✅ 飞书同步成功!\nrecord_id: ${recordId}\n💾 task md frontmatter 已更新\n${syncBanner}`,
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
