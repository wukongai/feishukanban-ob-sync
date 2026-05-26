/**
 * QuickAdd UserScript: 🎯 同步今日 task 到飞书
 *
 * 触发方式: Cmd+P → 搜「同步飞书项目」/「同步今日 task」 → 回车
 *
 * 行为（v1 - 2026-05-25，照搬 quickadd-同步布丁.js v1 的成熟管道）:
 * 1. 计算北京日期（用户 Mac 系统时区可能是 PDT，但 journal 文件名按北京日期）
 *    参考 base-and-frontmatter.md「时间字段四原则」第 4 条
 * 2. 检测今日 journal 是否存在（不存在 → 提示用户先创建）
 * 3. 构造 `/飞书项目同步 @journals/YYYY-MM-DD.md --only-completed` 命令
 *    （@ 引用让 Claudian 把 journal 作为 context）
 * 4. 复制到剪贴板（兜底）
 * 5. 调 `claudian:open-view` 打开 Claudian 面板
 * 6. DOM 注入自动填充 + 自动 Enter 提交（多重策略）
 * 7. 失败时降级到剪贴板 + Notice 提示
 *
 * ⚠️ 命令不带 --apply——Claudian 收到后走 SKILL.md 5 步 SOP：
 *    类型识别 → 类型预检 → dry-run → 等用户审批 → apply。
 *    符合 OB 项目铁律 #1「sync apply 必须先用户审核」。
 *
 * ⚠️ DOM 注入是 fragile 操作（依赖 Claudian 内部 DOM 结构）
 *    备用机制: 剪贴板复制始终发生, 用户手动 Cmd+V 总能继续
 */

module.exports = async function (params) {
  const { app, obsidian } = params;
  const { Notice } = obsidian;

  try {
    // ============ Step 1: 计算北京日期 ============
    // 北京时间 = UTC + 8h，避开 Mac 系统时区可能是 PDT 的陷阱
    const bjDate = new Date(Date.now() + 8 * 3600 * 1000)
      .toISOString()
      .slice(0, 10);
    const journalPath = `journals/${bjDate}.md`;
    console.log("[同步飞书项目 v1] 北京日期:", bjDate);
    console.log("[同步飞书项目 v1] journal path:", journalPath);

    // ============ Step 2: 检测今日 journal 是否存在 ============
    const journalFile = app.vault.getAbstractFileByPath(journalPath);
    if (!journalFile) {
      new Notice(
        `❌ 今日 journal 不存在: ${journalPath}\n请先打开/创建今日日志，再触发本命令`,
        8000
      );
      return;
    }

    // ============ Step 3: 构造命令 ============
    // @ 引用让 Claudian 把 journal 作为 context
    // 不带 --apply, 让 SKILL.md 走 5 步 SOP（dry-run + 用户审批）
    const SLASH_CMD = `/飞书项目同步 @${journalPath} --only-completed`;
    console.log("[同步飞书项目 v1] SLASH_CMD:", SLASH_CMD);

    // ============ Step 4: 复制剪贴板（兜底）============
    let copied = false;
    try {
      await navigator.clipboard.writeText(SLASH_CMD);
      copied = true;
    } catch (e) {
      console.warn("[同步飞书项目 v1] 剪贴板写入失败:", e);
    }

    // ============ Step 5: 打开 Claudian ============
    let opened;
    try {
      opened = app.commands.executeCommandById("claudian:open-view");
    } catch (e) {
      new Notice(`❌ 打开 Claudian 异常: ${e.message}`, 8000);
      return;
    }

    if (opened === false) {
      new Notice("❌ Claudian 插件未启用", 8000);
      return;
    }

    // ============ Step 6: 等 Claudian 视图渲染 ============
    new Notice(
      `⏳ 同步今日 task 到飞书: ${bjDate}\n自动填入 + 提交中...`,
      3000
    );
    await new Promise((r) => setTimeout(r, 400));

    // ============ Step 7: 尝试自动填充 + 提交（DOM 注入）============
    const result = await tryAutoFillSubmit(SLASH_CMD);
    console.log("[同步飞书项目 v1] 自动填充结果:", result);

    // ============ Step 8: 根据结果显示对应 Notice ============
    if (result.submitted === true) {
      new Notice(
        `✅ 已发送 /飞书项目同步\n（提交方式: ${result.method}）\n👀 切到 Claudian 看 dry-run 结果\n等你审批后才会真 apply 到飞书`,
        6000
      );
    } else if (result.submitted === "uncertain") {
      new Notice(
        `⚠️ 已自动填入\n所有提交策略都试过了，可能成功也可能没\n如果 Claudian 没动静，请手动按 Enter`,
        7000
      );
    } else if (result.filled) {
      new Notice(
        `⚠️ 已自动填入\n但未能自动发送——请手动按 Enter 发送`,
        6000
      );
    } else {
      // 完全失败 → 降级到剪贴板 + 让用户粘贴
      const msg = copied
        ? `⚠️ 自动填充失败 → 降级方案\n📋 已复制到剪贴板\n👉 在 Claudian 输入框 Cmd+V → 回车`
        : `❌ 自动填充失败 + 剪贴板写入失败\n请手动输入「${SLASH_CMD}」`;
      new Notice(msg, 8000);
    }
  } catch (e) {
    console.error("[同步飞书项目 v1] 顶层异常:", e);
    new Notice(
      `❌ 脚本异常: ${e.message}\n请打开 Console (Cmd+Opt+I) 看详情`,
      10000
    );
  }
};

// ============================================================
// Helper: 自动填充 + 自动提交 Claudian 输入框
// （照搬 quickadd-同步布丁.js v1，多重策略：按钮 / Cmd+Enter / Enter / form.submit）
// ============================================================
async function tryAutoFillSubmit(cmd) {
  console.log("[同步飞书项目 v1] 开始 DOM 注入...");

  // ===== Step A: 找 input 元素 =====
  let inputEl = null;
  const startTime = Date.now();

  while (Date.now() - startTime < 3000) {
    const candidates = document.querySelectorAll(
      'textarea, div[contenteditable="true"], div[contenteditable=""]'
    );

    const visible = Array.from(candidates).filter((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 100 && r.height > 20;
    });

    if (visible.length > 0) {
      // 优先找 placeholder 像聊天框的
      for (const el of visible) {
        const ph = (el.placeholder || el.getAttribute("placeholder") || "")
          .toLowerCase();
        const html = (el.outerHTML || "").toLowerCase().substring(0, 500);
        if (
          /today|ask|prompt|message|chat|help you|今|问|说|问问/.test(ph) ||
          /claudian|chat-input/.test(html)
        ) {
          inputEl = el;
          break;
        }
      }

      // 兜底: 取最后一个可见 input（通常是最新打开的）
      if (!inputEl) {
        inputEl = visible[visible.length - 1];
      }
    }

    if (inputEl) break;
    await new Promise((r) => setTimeout(r, 150));
  }

  if (!inputEl) {
    console.warn("[同步飞书项目 v1] 找不到 Claudian 输入框");
    return { filled: false, submitted: false };
  }

  // ===== Step B: 填充内容 =====
  try {
    inputEl.focus();

    if (inputEl.tagName === "TEXTAREA") {
      const proto = HTMLTextAreaElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
      if (setter) {
        setter.call(inputEl, cmd);
      } else {
        inputEl.value = cmd;
      }
      inputEl.dispatchEvent(new Event("input", { bubbles: true }));
      inputEl.dispatchEvent(new Event("change", { bubbles: true }));
    } else if (inputEl.tagName === "INPUT") {
      const proto = HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
      if (setter) {
        setter.call(inputEl, cmd);
      } else {
        inputEl.value = cmd;
      }
      inputEl.dispatchEvent(new Event("input", { bubbles: true }));
    } else {
      inputEl.textContent = cmd;
      inputEl.dispatchEvent(new Event("input", { bubbles: true }));
    }
  } catch (e) {
    console.error("[同步飞书项目 v1] 填充失败:", e);
    return { filled: false, submitted: false };
  }

  await new Promise((r) => setTimeout(r, 200));

  // ===== Step C: 多重提交策略 =====

  // 策略 0: 关键词 + 位置 双重过滤找 send 按钮
  const inputRect = inputEl.getBoundingClientRect();
  const allButtons = document.querySelectorAll('button, [role="button"]');

  const excludeKeywords = [
    "collapse", "expand", "close", "open", "copy", "edit",
    "retry", "delete", "remove", "menu", "settings", "more",
    "task list", "task-list", "panel-header", "tab-",
    "折叠", "展开", "关闭", "复制", "编辑", "重试", "删除", "菜单", "设置",
  ];

  const sendKeywords = [
    "send", "submit", "发送", "提交",
    "paper-plane", "paperplane", "arrow-up", "arrow-right",
    "lucide-send", "lucide-arrow-up",
  ];

  const candidates = [];

  for (const b of allButtons) {
    if (b.disabled) continue;
    const r = b.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;

    const aria = (b.getAttribute("aria-label") || "").toLowerCase();
    const cls = (typeof b.className === "string" ? b.className : "").toLowerCase();
    const html = (b.outerHTML || "").toLowerCase().substring(0, 500);

    if (excludeKeywords.some((kw) => aria.includes(kw) || cls.includes(kw))) {
      continue;
    }

    let score = 0;
    for (const kw of sendKeywords) {
      if (aria.includes(kw)) score += 10;
      if (cls.includes(kw)) score += 8;
      if (html.includes(kw)) score += 3;
    }

    const verticalDist = Math.abs(r.top - inputRect.top);
    const horizontalDist = Math.abs(r.left - inputRect.right);
    if (verticalDist < 200 && horizontalDist < 200) score += 5;
    if (verticalDist < 100 && horizontalDist < 100) score += 3;

    if (r.left > inputRect.left && r.bottom > inputRect.top) score += 2;

    if (score > 0) {
      candidates.push({ btn: b, score, aria, cls });
    }
  }

  candidates.sort((a, b) => b.score - a.score);

  if (candidates.length > 0) {
    const winner = candidates[0].btn;
    try {
      winner.click();
      await new Promise((r) => setTimeout(r, 200));
      const isEmpty =
        inputEl.tagName === "TEXTAREA"
          ? !inputEl.value
          : !inputEl.textContent;
      if (isEmpty) {
        return { filled: true, submitted: true, method: "nearby-button" };
      }
    } catch (e) {
      console.warn("[同步飞书项目 v1] 策略 0 click 失败:", e);
    }
  }

  // 策略 1: 标准 send selectors
  const btnSelectors = [
    'button[type="submit"]',
    'button[aria-label*="end" i]',
    'button[aria-label*="ubmit" i]',
    'button[aria-label*="发送"]',
    'button[aria-label*="提交"]',
    "button.send-button",
    "button.submit-button",
    '[role="button"][aria-label*="end" i]',
  ];

  for (const sel of btnSelectors) {
    let btn;
    try {
      btn = document.querySelector(sel);
    } catch (e) {
      continue;
    }
    if (btn && !btn.disabled) {
      const r = btn.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        try {
          btn.click();
          await new Promise((r) => setTimeout(r, 200));
          const isEmpty =
            inputEl.tagName === "TEXTAREA"
              ? !inputEl.value
              : !inputEl.textContent;
          if (isEmpty) {
            return { filled: true, submitted: true, method: "selector-button" };
          }
        } catch (e) {
          console.warn(`[同步飞书项目 v1] 策略 1 click 失败 (${sel}):`, e);
        }
      }
    }
  }

  // 策略 2: Cmd+Enter
  try {
    inputEl.focus();
    inputEl.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        code: "Enter",
        keyCode: 13,
        which: 13,
        metaKey: true,
        bubbles: true,
        cancelable: true,
      })
    );
    await new Promise((r) => setTimeout(r, 100));
    const isEmpty =
      inputEl.tagName === "TEXTAREA"
        ? !inputEl.value
        : !inputEl.textContent;
    if (isEmpty) {
      return { filled: true, submitted: true, method: "cmd+enter" };
    }
  } catch (e) {
    console.warn("[同步飞书项目 v1] 策略 2 失败:", e);
  }

  // 策略 3: plain Enter
  try {
    inputEl.focus();
    inputEl.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        code: "Enter",
        keyCode: 13,
        which: 13,
        bubbles: true,
        cancelable: true,
      })
    );
    await new Promise((r) => setTimeout(r, 100));
    const isEmpty =
      inputEl.tagName === "TEXTAREA"
        ? !inputEl.value
        : !inputEl.textContent;
    if (isEmpty) {
      return { filled: true, submitted: true, method: "enter" };
    }
  } catch (e) {
    console.warn("[同步飞书项目 v1] 策略 3 失败:", e);
  }

  // 策略 4: form.submit()
  const form = inputEl.closest("form");
  if (form) {
    try {
      form.requestSubmit ? form.requestSubmit() : form.submit();
      await new Promise((r) => setTimeout(r, 100));
      const isEmpty =
        inputEl.tagName === "TEXTAREA"
          ? !inputEl.value
          : !inputEl.textContent;
      if (isEmpty) {
        return { filled: true, submitted: true, method: "form" };
      }
    } catch (e) {
      console.warn("[同步飞书项目 v1] 策略 4 失败:", e);
    }
  }

  return { filled: true, submitted: "uncertain", method: "none" };
}
