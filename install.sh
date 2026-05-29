#!/usr/bin/env bash
# install.sh — 把 feishukanban-ob-sync 部署到你的 Obsidian vault
#
# 用法:
#   ./install.sh                                    # dry-run(预览改什么,不真做)
#   ./install.sh --apply                            # 真执行
#   ./install.sh --vault-path <path>                # 指定 vault 路径(默认询问)
#   ./install.sh --scripts-dir <vault-rel-path>     # 自定义装到 vault 哪个相对位置
#                                                   # 默认 scripts/feishukanban-ob-sync
#   ./install.sh --apply --force                    # 覆盖已存在的文件(慎用)
#
# 行为(简化版,2026-05-26 v0.3.2 定型 / 2026-05-27 v0.3.3 仅版本 bump):
#   1. 检查依赖(python3 / feishu-cli / Obsidian)
#   2. 询问/解析 vault 路径
#   3. symlink scripts(sync.py / auto_collect_today.py)到 vault/$SCRIPTS_DIR
#   4. symlink userscripts 到 vault/$SCRIPTS_DIR/userscripts
#   5. 复制 templates / base / rules(检查 mtime,默认不覆盖)
#   6. 输出 QuickAdd choices JSON snippet 让用户粘贴(path 字段自动跟 --scripts-dir)
#   7. 提示后续手动步骤(飞书表字段 + config.yaml)

set -euo pipefail

# ============================================================
# 配置
# ============================================================
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPLY=0
FORCE=0
VAULT=""
# v0.3.2: SCRIPTS_DIR 是 vault 相对路径(从 vault 根算起,不含前导/尾随 /)
# 默认开源友好值;用户可用 --scripts-dir 覆盖装到 vault 任意位置
# 自适应原理:userscripts/*.js 用 __filename 推导 sync.py 路径,
# install.sh 只要保证 sync.py 在 userscripts/ 上一级,就 100% 工作
SCRIPTS_DIR="scripts/feishukanban-ob-sync"

# ============================================================
# 参数解析
# ============================================================
while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --force) FORCE=1; shift ;;
    --vault-path) VAULT="$2"; shift 2 ;;
    --scripts-dir)
      # 去掉前后多余的 /,接受 "foo/bar" / "/foo/bar" / "foo/bar/" 等格式
      SCRIPTS_DIR="${2#/}"; SCRIPTS_DIR="${SCRIPTS_DIR%/}"
      shift 2 ;;
    --help|-h)
      head -22 "${BASH_SOURCE[0]}" | tail -20
      exit 0 ;;
    *) echo "❌ 未知参数: $1"; exit 1 ;;
  esac
done

# ============================================================
# 工具函数
# ============================================================
log() { echo "$@"; }
ok() { echo "✅ $@"; }
warn() { echo "⚠️  $@"; }
err() { echo "❌ $@" >&2; }

run_or_dry() {
  if [[ $APPLY -eq 1 ]]; then
    "$@"
  else
    log "  [dry-run] $@"
  fi
}

# ============================================================
# Step 1: 依赖检查
# ============================================================
log ""
log "============================================================"
log "📦 feishukanban-ob-sync v0.3.8 install"
log "============================================================"
[[ $APPLY -eq 0 ]] && log "📌 模式: dry-run(--apply 才真执行)" || log "🚀 模式: --apply(真执行)"
log "📂 装到 vault 相对路径: $SCRIPTS_DIR(用 --scripts-dir 改)"
log ""

log "Step 1: 依赖检查"
if ! command -v python3 >/dev/null 2>&1; then
  err "python3 未安装。需要 Python 3.8+"
  exit 1
fi
ok "python3: $(python3 --version)"

if ! command -v feishu-cli >/dev/null 2>&1; then
  warn "feishu-cli 未安装 — sync 必需。装:https://github.com/feishu-cli/feishu-cli"
else
  ok "feishu-cli: $(feishu-cli --version 2>&1 | head -1)"
fi
log ""

# ============================================================
# Step 2: 询问 / 解析 vault 路径
# ============================================================
log "Step 2: vault 路径"
if [[ -z "$VAULT" ]]; then
  # 尝试常见位置
  for candidate in "$HOME/Documents/Obsidian" "$HOME/Documents/OB" "$HOME/Obsidian"; do
    if [[ -d "$candidate/.obsidian" ]]; then
      log "  发现 vault: $candidate"
      read -r -p "  使用这个 vault? [Y/n] " ans
      if [[ -z "$ans" || "$ans" =~ ^[Yy] ]]; then
        VAULT="$candidate"
        break
      fi
    fi
  done

  if [[ -z "$VAULT" ]]; then
    read -r -p "  输入 vault 绝对路径: " VAULT
  fi
fi

if [[ ! -d "$VAULT/.obsidian" ]]; then
  err "vault 路径不含 .obsidian/ 目录: $VAULT"
  exit 1
fi
ok "vault: $VAULT"
log ""

# ============================================================
# Step 3: symlink scripts
# ============================================================
log "Step 3: symlink scripts(sync.py + auto_collect_today.py)"
SCRIPTS_TARGET="$VAULT/$SCRIPTS_DIR"
run_or_dry mkdir -p "$SCRIPTS_TARGET"

# sync.py
if [[ -e "$SCRIPTS_TARGET/sync.py" && $FORCE -eq 0 ]]; then
  warn "sync.py 已存在 → 跳过(用 --force 覆盖)"
else
  [[ $APPLY -eq 1 && -e "$SCRIPTS_TARGET/sync.py" ]] && rm "$SCRIPTS_TARGET/sync.py"
  run_or_dry ln -s "$REPO_DIR/sync.py" "$SCRIPTS_TARGET/sync.py"
  ok "  symlink: $SCRIPTS_TARGET/sync.py → $REPO_DIR/sync.py"
fi

# auto_collect_today.py
if [[ -e "$SCRIPTS_TARGET/auto_collect_today.py" && $FORCE -eq 0 ]]; then
  warn "auto_collect_today.py 已存在 → 跳过"
else
  [[ $APPLY -eq 1 && -e "$SCRIPTS_TARGET/auto_collect_today.py" ]] && rm "$SCRIPTS_TARGET/auto_collect_today.py"
  run_or_dry ln -s "$REPO_DIR/scripts/auto_collect_today.py" "$SCRIPTS_TARGET/auto_collect_today.py"
  ok "  symlink: $SCRIPTS_TARGET/auto_collect_today.py"
fi
log ""

# ============================================================
# Step 4: 装 QuickAdd UserScripts(cp + sed 注入 sync.py 路径)
# ============================================================
# v0.3.4 改造背景:v0.3.2 用 __filename 在 userscript 里推导 sync.py 路径,
# 但 Obsidian QuickAdd 上下文里 __filename 指向 electron.asar 内部,不是 vault 内
# 真实位置 → sync.py 路径推导成 /Applications/Obsidian.app/.../sync.py(不存在)→ 报错
# 修复:install.sh 时 cp(不再 symlink) + sed 替换占位符 __SYNC_PY_ABS_PATH__ 为
# $REPO_DIR/sync.py 真实绝对路径,userscript 不再依赖 __filename
# trade-off:升级 obsidian-assets/userscripts/*.js 后需要重跑 install.sh --force
log "Step 4: 装 QuickAdd UserScripts(cp + sed 注入,v0.3.4)"
US_TARGET="$SCRIPTS_TARGET/userscripts"
run_or_dry mkdir -p "$US_TARGET"

SYNC_PY_ABS="$REPO_DIR/sync.py"

for js in "$REPO_DIR/obsidian-assets/userscripts/"*.js; do
  name=$(basename "$js")
  target="$US_TARGET/$name"
  if [[ -e "$target" && $FORCE -eq 0 ]]; then
    warn "  $name 已存在 → 跳过(用 --force 覆盖)"
    continue
  fi
  if [[ $APPLY -eq 1 ]]; then
    [[ -e "$target" || -L "$target" ]] && rm "$target"
    cp "$js" "$target"
    # macOS sed -i 需要 '' 参数(BSD sed)
    sed -i '' "s|__SYNC_PY_ABS_PATH__|$SYNC_PY_ABS|g" "$target"
    ok "  cp + sed inject: $target(sync.py → $SYNC_PY_ABS)"
  else
    log "  [dry-run] cp $js → $target"
    log "  [dry-run] sed inject __SYNC_PY_ABS_PATH__ → $SYNC_PY_ABS"
  fi
done
log ""

# ============================================================
# Step 5: 复制 templates / base / rules(不覆盖已有,除非 --force)
# ============================================================
log "Step 5: 复制 obsidian-assets(模板 / base / rules)"

# 5.1 task 模版
TASK_TPL_TARGET="$VAULT/03 Resources/素材库/模版/task 模版.md"
if [[ -e "$TASK_TPL_TARGET" && $FORCE -eq 0 ]]; then
  warn "task 模版 已存在 → 跳过"
else
  run_or_dry mkdir -p "$(dirname "$TASK_TPL_TARGET")"
  run_or_dry cp "$REPO_DIR/obsidian-assets/templates/task-template.md" "$TASK_TPL_TARGET"
  ok "  task 模版 → $TASK_TPL_TARGET"
fi

# 5.2 _task.base
TASK_BASE_TARGET="$VAULT/04 Inbox/task/_task.base"
if [[ -e "$TASK_BASE_TARGET" && $FORCE -eq 0 ]]; then
  warn "_task.base 已存在 → 跳过"
else
  run_or_dry mkdir -p "$(dirname "$TASK_BASE_TARGET")"
  run_or_dry cp "$REPO_DIR/obsidian-assets/base/_task.base" "$TASK_BASE_TARGET"
  ok "  _task.base → $TASK_BASE_TARGET"
fi

# 5.3 主 rules
RULES_TARGET="$VAULT/.claude/rules/feishu-project-sync.md"
if [[ -e "$RULES_TARGET" && $FORCE -eq 0 ]]; then
  warn "rules/feishu-project-sync.md 已存在 → 跳过"
else
  run_or_dry mkdir -p "$(dirname "$RULES_TARGET")"
  run_or_dry cp "$REPO_DIR/obsidian-assets/rules/feishu-project-sync.md" "$RULES_TARGET"
  ok "  rules → $RULES_TARGET"
fi
log ""

# ============================================================
# Step 6: 输出 QuickAdd choices JSON snippet(给用户手动粘贴)
# ============================================================
log "Step 6: QuickAdd choices(用户需手动加到 .obsidian/plugins/quickadd/data.json)"
log ""

SNIPPET_FILE="$REPO_DIR/.quickadd-choices.json"
cat > "$SNIPPET_FILE" <<EOF
[
  {
    "id": "quick-task-v2-choice",
    "name": "📝 快记任务",
    "type": "Macro",
    "command": true,
    "macro": {
      "name": "📝 快记任务",
      "id": "quick-task-v2-macro-id",
      "commands": [{
        "name": "📝 快记任务 v2(task md 化)",
        "type": "UserScript",
        "id": "quick-task-v2-userscript-cmd",
        "path": "$SCRIPTS_DIR/userscripts/quickadd-快记任务-v2-task-md.js",
        "settings": {}
      }],
      "runOnStartup": false
    },
    "runOnStartup": false
  },
  {
    "id": "pull-today-choice",
    "name": "📥 拉今日 todo",
    "type": "Macro",
    "command": true,
    "macro": {
      "name": "📥 拉今日 todo",
      "id": "pull-today-macro-id",
      "commands": [{
        "name": "拉飞书侧今日 todo 到 OB",
        "type": "UserScript",
        "id": "pull-today-userscript-cmd",
        "path": "$SCRIPTS_DIR/userscripts/quickadd-拉今日todo.js",
        "settings": {}
      }],
      "runOnStartup": false
    },
    "runOnStartup": false
  },
  {
    "id": "complete-task-choice",
    "name": "✅ 完成当前 task",
    "type": "Macro",
    "command": true,
    "macro": {
      "name": "✅ 完成当前 task",
      "id": "complete-task-macro-id",
      "commands": [{
        "name": "改 frontmatter + sync 飞书 UPDATE",
        "type": "UserScript",
        "id": "complete-task-userscript-cmd",
        "path": "$SCRIPTS_DIR/userscripts/quickadd-完成task.js",
        "settings": {}
      }],
      "runOnStartup": false
    },
    "runOnStartup": false
  },
  {
    "id": "feishu-task-sync-quickadd-choice",
    "name": "🎯 同步今日 task 到飞书",
    "type": "Macro",
    "command": true,
    "macro": {
      "name": "🎯 同步今日 task 到飞书",
      "id": "feishu-task-sync-macro-id",
      "commands": [{
        "name": "调起 Claudian + 发送 /飞书项目同步",
        "type": "UserScript",
        "id": "feishu-task-sync-userscript-cmd",
        "path": "$SCRIPTS_DIR/userscripts/quickadd-同步飞书项目.js",
        "settings": {}
      }],
      "runOnStartup": false
    },
    "runOnStartup": false
  },
  {
    "id": "push-all-today-choice",
    "name": "🎯 批量推今日 task 到飞书(反向)",
    "type": "Macro",
    "command": true,
    "macro": {
      "name": "🎯 批量推今日 task 到飞书(反向)",
      "id": "push-all-today-macro-id",
      "commands": [{
        "name": "扫全 vault today=true task → 各自 push 飞书(v0.4.0 Step 3)",
        "type": "UserScript",
        "id": "push-all-today-userscript-cmd",
        "path": "$SCRIPTS_DIR/userscripts/quickadd-批量推今日-task-md.js",
        "settings": {}
      }],
      "runOnStartup": false
    },
    "runOnStartup": false
  },
  {
    "id": "pull-current-task-choice",
    "name": "📥 拉当前 task(单条 pull,类 git)",
    "type": "Macro",
    "command": true,
    "macro": {
      "name": "📥 拉当前 task(单条 pull,类 git)",
      "id": "pull-current-task-macro-id",
      "commands": [{
        "name": "当前 task md → 拉飞书对应 record(v0.5.3)",
        "type": "UserScript",
        "id": "pull-current-task-userscript-cmd",
        "path": "$SCRIPTS_DIR/userscripts/quickadd-拉当前task.js",
        "settings": {}
      }],
      "runOnStartup": false
    },
    "runOnStartup": false
  },
  {
    "id": "push-current-task-choice",
    "name": "↗️ 推当前 task(单条 push,类 git)",
    "type": "Macro",
    "command": true,
    "macro": {
      "name": "↗️ 推当前 task(单条 push,类 git)",
      "id": "push-current-task-macro-id",
      "commands": [{
        "name": "当前 task md → push 飞书(CREATE 或 UPDATE)(v0.5.3)",
        "type": "UserScript",
        "id": "push-current-task-userscript-cmd",
        "path": "$SCRIPTS_DIR/userscripts/quickadd-推当前task.js",
        "settings": {}
      }],
      "runOnStartup": false
    },
    "runOnStartup": false
  },
  {
    "id": "log-detail-choice",
    "name": "📈 记录今日明细(daily execution log)",
    "type": "Macro",
    "command": true,
    "macro": {
      "name": "📈 记录今日明细(daily execution log)",
      "id": "log-detail-macro-id",
      "commands": [{
        "name": "记今天的执行状态 + 描述 → 飞书子表 record(v0.6.0)",
        "type": "UserScript",
        "id": "log-detail-userscript-cmd",
        "path": "$SCRIPTS_DIR/userscripts/quickadd-记录今日明细.js",
        "settings": {}
      }],
      "runOnStartup": false
    },
    "runOnStartup": false
  }
]
EOF
ok "QuickAdd choices JSON 写到: $SNIPPET_FILE"
log ""
log "  手动操作:"
log "  1. 打开 $VAULT/.obsidian/plugins/quickadd/data.json"
log "  2. 在 'choices' 数组里加入 $SNIPPET_FILE 内容(注意 JSON 逗号)"
log "  3. Cmd+Q 重启 Obsidian"
log ""

# ============================================================
# Step 7: 后续手动步骤
# ============================================================
log "Step 7: 后续手动步骤"
log ""
log "  📋 必做:"
log "  1. 在飞书新建多维表 + 加 22 个字段"
log "     → 参考 $REPO_DIR/docs/feishu-schema.md(含 feishu-cli 一键命令)"
log ""
log "  2. 复制 config.example.yaml → vault config:"
log "     cp $REPO_DIR/config.example.yaml $SCRIPTS_TARGET/config.yaml"
log "     编辑 base_token / table_id / tenant_domain"
log ""
log "  3. feishu-cli auth login(如未登录)"
log ""
log "  4. Cmd+Q 重启 Obsidian → Cmd+P 测试「📝 快记任务」"
log ""
log "  📚 详细教程: $REPO_DIR/docs/tutorial/05-task-md-workflow.md"
log ""

if [[ $APPLY -eq 0 ]]; then
  log "============================================================"
  log "📌 这是 dry-run。--apply 真执行"
  log "============================================================"
else
  log "============================================================"
  ok "feishukanban-ob-sync v0.3.8 部署完成!"
  log "============================================================"
fi
