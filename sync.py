#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书项目同步 - OB ↔ 飞书项目管理多维表 双向同步

用法:
  # === Phase 1: OB → 飞书 ===
  # dry-run(默认,不调写接口)
  python3 sync.py path/to/日志.md
  # 真写(创建新 record / 回填字段)
  python3 sync.py path/to/日志.md --apply

  # === Phase 2: 飞书 → OB ===
  # dry-run(列出会拉哪些 record)
  python3 sync.py --pull
  # 真写到当日日志(默认拉最近 7 天)
  python3 sync.py --pull --apply
  # 指定时间窗口
  python3 sync.py --pull --since 2026-05-10 --apply

依赖:
  - Python 3.11+
  - feishu-cli(已 auth login + scope 包含 base:record:retrieve/update/create)
  - PyYAML(pip install pyyaml)

环境约定:
  - 脚本必须从 vault 根目录跑(`cd /Users/aim5/Documents/OB && python3 ...`)
  - 配置文件 config.yaml 在脚本同目录
"""

import argparse                  # 命令行参数解析
import json                      # 调 cli 时构造 payload
import re                        # 解析 markdown task 行
import subprocess                # 调 feishu-cli
import sys                       # 退出码 + stderr
import urllib.parse              # Obsidian URL Scheme 编码(中文/空格)
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

try:
    import yaml                  # 解析 config.yaml
except ImportError:
    print("❌ 缺少依赖: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


# ============================================================
# 工具:加载配置 + 路径处理
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
# vault 根目录(OB 项目根),用于 C 路径反向扫描笔记 frontmatter
# 脚本路径: `OB/01 Project/00 进行中/06 小工具开发/CC命令/飞书项目同步/`
# parents 从父目录开始数:[0]=CC命令, [1]=06 小工具开发, [2]=00 进行中, [3]=01 Project, [4]=OB
VAULT_ROOT = SCRIPT_DIR.parents[4]

# 缓存配置,避免重复读
_CONFIG = None


def load_config() -> dict:
    """读 config.yaml,返回字典。失败立刻退出"""
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG
    if not CONFIG_PATH.exists():
        print(f"❌ 配置文件不存在: {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        _CONFIG = yaml.safe_load(f)
    return _CONFIG


# ============================================================
# OB 侧:解析 task 行
# ============================================================

# Task 行正则(支持 Tasks 插件格式)
# 匹配示例:
#   - [x] [【设备】macmini-修复 ](https://...) 🔼 ➕ 2026-05-16 ✅ 2026-05-16
#   - [ ] [新任务]() 🔼 ➕ 2026-05-17
#   - [ ] 燕姐电话说量化开发      ← 无链接
TASK_LINE_RE = re.compile(
    r"^(?P<indent>\s*)-\s+\[(?P<status>[ x/\-])\]\s+"  # checkbox: - [ ] / - [x] / - [/] / - [-]
    r"(?P<body>.+)$",                                   # 行内剩下的所有内容(标题+链接+emoji)
    re.MULTILINE,
)

# markdown 链接正则(可能为空 url: []())
MD_LINK_RE = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<url>[^)]*)\)")

# Tasks 插件 emoji
EMOJI_DONE = "✅"          # 完成日: ✅ YYYY-MM-DD
EMOJI_CREATED = "➕"       # 创建日: ➕ YYYY-MM-DD
EMOJI_CANCELED = "❌"      # 放弃日: ❌ YYYY-MM-DD
EMOJI_SCHEDULED = "🛫"     # 开始日: 🛫 YYYY-MM-DD
EMOJI_DUE = "📅"           # 截止日: 📅 YYYY-MM-DD
EMOJI_ID = "🆔"            # Tasks 短 ID: 🆔 xy3z9k

# 优先级 emoji
PRIORITY_EMOJIS = {"🔺", "⏫", "🔼", "🔽"}

# 日期 emoji + 日期 正则(用于抽取 ✅ ➕ ❌ 后跟的日期)
DATE_AFTER_EMOJI_RE_TEMPLATE = r"{emoji}\s+(\d{{4}}-\d{{2}}-\d{{2}})"


def extract_emoji_date(text: str, emoji: str) -> Optional[str]:
    """从 task 行抽取 `emoji YYYY-MM-DD` 形式的日期"""
    m = re.search(DATE_AFTER_EMOJI_RE_TEMPLATE.format(emoji=emoji), text)
    return m.group(1) if m else None


def extract_priority(text: str) -> Optional[str]:
    """从 task 行抽取优先级 emoji"""
    for emoji in PRIORITY_EMOJIS:
        if emoji in text:
            return emoji
    return None


def extract_link(body: str) -> tuple[str, Optional[str]]:
    """从 task body 抽取 markdown 链接。
    返回 (任务标题, URL or None)
    - 有 `[文字](url)` → text=文字, url=URL(可能为空字符串)
    - 无 markdown 链接 → text=整个 body(去掉 emoji 等), url=None
    """
    m = MD_LINK_RE.search(body)
    if m:
        text = m.group("text").strip()
        url = m.group("url").strip() or None
        return text, url
    # 无链接:整段作为标题,但去掉 emoji 和日期
    clean = body
    for emoji in PRIORITY_EMOJIS:
        clean = clean.replace(emoji, "")
    clean = re.sub(r"[✅➕❌🛫📅🆔]\s*\S*", "", clean)
    return clean.strip(), None


def extract_record_id(url: str, config: dict) -> Optional[str]:
    """从飞书 URL 抽 record_id(支持短链、base 长链、wiki 长链)
    - 短链:       https://xxx.feishu.cn/record/HrKrrZ1HOeDfu5cdgXMcYDYTnZg
    - base 长链:  https://xxx.feishu.cn/base/Vy8ubUWKbad5u1s8BCJcd1TlnFf?table=tblxxx&record=recvjLmrOiJ11K  (2026-05-19 起新写)
    - wiki 长链:  https://xxx.feishu.cn/wiki/PAtUwFxlLiIgcwkK5ixcIRuJnHb?table=tblxxx&record=recvjLmrOiJ11K  (历史兼容)
    返回:
    - 长链(base 或 wiki) → 真实 record_id(rec 开头)
    - 短链 → 短串(27 位,需要后续 search 反查 record_id)
    - 不匹配 → None

    注:正则 [?&]record=(rec...) 不挑路径,base/wiki 长链都能匹配。
    """
    if not url:
        return None
    # 长链:URL 里有 record= 参数
    m = re.search(r"[?&]record=(rec[a-zA-Z0-9]+)", url)
    if m:
        return m.group(1)
    # 短链:/record/<27 位>
    m = re.search(r"/record/([a-zA-Z0-9]+)", url)
    if m:
        return m.group(1)
    return None


def is_short_record_id(record_id: str) -> bool:
    """判断是否为分享短链(27 位)而非真实 record_id(rec 开头)"""
    return not record_id.startswith("rec")


def parse_callout_below(content: str, task_line_idx: int, callout_types: list) -> Optional[str]:
    """解析 task 行下方紧跟的 callout(用于抽交付字段)。
    返回 callout 正文(去掉 > 前缀,合并多行),无则返回 None

    2026-05-19 bug fix: 容忍前导空格缩进(Obsidian 标准:list item 下嵌套 callout 要 2 空格缩进)
    旧 regex `>\s*` 从字符串开头匹配,不接受前导空格 → 错过所有 list 嵌套场景
    """
    lines = content.split("\n")
    if task_line_idx + 1 >= len(lines):
        return None
    # 下一行必须以(可选前导空格 +) > [! 开头
    next_line = lines[task_line_idx + 1]
    callout_match = re.match(r"\s*>\s*\[!(\w+)[+\-]?\s*", next_line)
    if not callout_match:
        return None
    found_type = callout_match.group(1).lower()
    if found_type not in [t.lower() for t in callout_types]:
        return None
    # 抽 callout 后续所有 `(空格+)> ` 开头的行
    callout_lines = []
    i = task_line_idx + 1
    while i < len(lines) and lines[i].lstrip().startswith(">"):
        # 先 lstrip 去前导空格,再去 `> ` 前缀
        stripped = lines[i].lstrip()
        line = re.sub(r"^>\s?", "", stripped)
        callout_lines.append(line)
        i += 1
    # 第一行是 `[!success] 标题`,去掉
    if callout_lines:
        first = re.sub(r"\[!\w+[+\-]?\s*", "", callout_lines[0]).strip()
        callout_lines[0] = first
    return "\n".join(line for line in callout_lines if line).strip()


# ============================================================
# 交付物(delivery)D 混合架构 — 3 种 OB 端表达方式
# ============================================================
#
# A 路径:同行 wikilink
#   - [x] [task](link) ✅ 📎 [[xxx.md]] [[yyy.py]]
# B 路径:callout 块(已实现 parse_callout_below)
#   - [x] [task](link) ✅
#     > [!note]- 📎 交付物
#     > - [[xxx.md]] 教程
# C 路径:独立 md frontmatter 反向链接
#   ---
#   delivery_for: [recXXX]
#   ---
#   全 vault 扫描所有 .md 找出指向该 record_id 的笔记


# Wikilink 正则(支持 [[xxx]] 和 [[xxx|alias]] 和 [[folder/xxx.md]])
WIKILINK_RE = re.compile(r"\[\[(?P<target>[^\]|]+?)(?:\|(?P<alias>[^\]]+))?\]\]")

# 反向链接索引缓存(vault 全扫一次后复用,避免每个 task 都扫)
# 结构: {record_id: [{"path": "xxx.md", "title": "yyy"}, ...]}
_BACKLINKS_CACHE: Optional[dict] = None


def extract_inline_deliveries(body: str, config: dict) -> list:
    """A 路径:抽 task 行同行 📎 后跟的 wikilink。

    示例输入:
      "[task](link) ✅ 2026-05-16 📎 [[07 Mac Mini NAS 配置]] [[.claude/oss-sync-v2.py]] 备注随意"

    返回: [{"path": "07 Mac Mini NAS 配置", "note": ""}, {"path": ".claude/oss-sync-v2.py", "note": ""}]
    """
    emoji = config.get("fields", {}).get("delivery", {}).get("inline_emoji", "📎")
    if emoji not in body:
        return []
    # 取 emoji 后所有的 wikilink
    after_emoji = body.split(emoji, 1)[1]
    items = []
    for m in WIKILINK_RE.finditer(after_emoji):
        target = m.group("target").strip()
        alias = (m.group("alias") or "").strip()
        items.append({"path": target, "note": alias})
    return items


def extract_callout_deliveries(callout_text: str) -> list:
    """B 路径:从 callout 文本里抽 wikilink + 备注。

    示例输入(callout 文本,parse_callout_below 已去 > 前缀):
      "📎 交付物
       - [[07 Mac Mini NAS 配置]] 教程文档
       - [[.claude/oss-sync-v2.py]] 同步脚本"

    返回: [{"path": "07 Mac Mini NAS 配置", "note": "教程文档"}, ...]
    """
    if not callout_text:
        return []
    items = []
    for line in callout_text.split("\n"):
        # 跳过 callout 标题行(不含 wikilink)
        wikilinks = list(WIKILINK_RE.finditer(line))
        if not wikilinks:
            continue
        # 每行只取第一个 wikilink 作为 path,其后为备注
        first = wikilinks[0]
        target = first.group("target").strip()
        alias = (first.group("alias") or "").strip()
        # 备注 = wikilink 后的文字 - 去掉前缀符号 - 空白
        after = line[first.end():].strip()
        after = re.sub(r"^[-—\s:：]+", "", after).strip()
        note = alias or after
        items.append({"path": target, "note": note})
    return items


def build_backlinks_index(vault_root: Path, config: dict) -> dict:
    """C 路径预扫:扫全 vault 所有 .md 文件的 frontmatter,
    构建 `record_id → [产物笔记列表]` 索引。

    只在第一次调用时执行,后续走缓存。
    """
    global _BACKLINKS_CACHE
    if _BACKLINKS_CACHE is not None:
        return _BACKLINKS_CACHE

    backlink_field = config.get("fields", {}).get("delivery", {}).get("backlink_field", "delivery_for")
    print(f"⏳ 首次扫描 vault 构建交付物反向索引(C 路径)... ", end="", flush=True)

    index: dict = {}  # record_id -> [{"path", "title"}]
    md_files = list(vault_root.rglob("*.md"))
    # 排除一些大目录
    EXCLUDE_PARTS = {".obsidian", ".git", "node_modules", ".trash", ".claudian"}
    md_files = [
        f for f in md_files
        if not any(part in EXCLUDE_PARTS for part in f.parts)
    ]

    scanned = 0
    for md in md_files:
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        # 只看头部 100 行的 frontmatter,避免读全文
        head = "\n".join(text.split("\n")[:100])
        if not head.startswith("---"):
            continue
        # 抽 frontmatter
        fm_match = re.match(r"^---\n(.*?)\n---", head, re.DOTALL)
        if not fm_match:
            continue
        try:
            fm = yaml.safe_load(fm_match.group(1))
        except Exception:
            continue
        if not isinstance(fm, dict):
            continue
        backlinks = fm.get(backlink_field)
        if not backlinks:
            continue
        # 支持 list 或 str
        if isinstance(backlinks, str):
            backlinks = [backlinks]
        if not isinstance(backlinks, list):
            continue
        # 笔记标题:frontmatter.title 或文件 stem
        title = fm.get("title") or md.stem
        # 笔记路径(相对 vault 根)
        rel_path = md.relative_to(vault_root).as_posix()
        for rec_id in backlinks:
            if not isinstance(rec_id, str):
                continue
            rec_id = rec_id.strip()
            index.setdefault(rec_id, []).append({"path": rel_path, "title": title})
        scanned += 1

    print(f"完成({scanned} 篇笔记被识别为产物索引)")
    _BACKLINKS_CACHE = index
    return index


def find_delivery_for_links(record_id: str, vault_root: Path, config: dict) -> list:
    """C 路径:查 record_id 对应的产物笔记列表"""
    index = build_backlinks_index(vault_root, config)
    raw = index.get(record_id, [])
    # 转成统一结构 {path, note}
    return [{"path": item["path"], "note": item["title"]} for item in raw]


def merge_deliveries(inline: list, callout: list, backlinks: list) -> list:
    """合并 A/B/C 三路产物,以 path 为 key 去重。
    优先级:C(独立 md 反向)> B(callout)> A(同行)
    —— C 的备注最详(用 frontmatter title),B 次之(用户写的注),A 最简(可能无注)
    """
    seen = {}  # path → item
    # 倒序合并:后加的优先级高 → 先加 A → 后加 B → 后加 C(C 覆盖前者)
    for item in inline + callout + backlinks:
        path = item["path"]
        # 规范化 path(去 .md 后缀比较,避免 [[xxx]] 和 [[xxx.md]] 视为不同)
        norm = re.sub(r"\.md$", "", path)
        if norm in seen:
            # 已有,合并备注(取非空的)
            if item.get("note") and not seen[norm].get("note"):
                seen[norm]["note"] = item["note"]
            continue
        seen[norm] = item
    return list(seen.values())


def fetch_existing_delivery(record_id: str, config: dict) -> str:
    """读飞书侧现有 delivery 字段值(用于手工保护检查)。
    返回字符串(可能为空)。
    """
    field_name = config.get("fields", {}).get("delivery", {}).get("field_name", "交付")
    try:
        result = run_cli([
            "bitable", "record", "get",
            "--base-token", config["feishu"]["base_token"],
            "--table-id", config["feishu"]["table_id"],
            "--record-id", record_id,
        ])
        # v3 API 返回: {"record": {"<字段名>": <值>, ...}}
        record = result.get("record", {})
        val = record.get(field_name, "")
        if isinstance(val, list):
            # text plain 字段有时返回 [{"text": "...", "type": "text"}]
            val = "".join(seg.get("text", "") if isinstance(seg, dict) else str(seg) for seg in val)
        return val or ""
    except RuntimeError as e:
        print(f"⚠️  读 record {record_id} delivery 失败,跳过保护检查: {e}", file=sys.stderr)
        return ""


# ============================================================
# 飞书云文档(Phase 1.7,2026-05-17 上线)
# ============================================================
#
# 痛点:Phase 1.6 用 obsidian:// URL Scheme,被飞书 security 跳转破坏(完全失效)
# 方案:把 .md 推到飞书云文档,「交付」字段用 https://feishu.cn/docx/<id> 链接
# 缓存:doc_token 存在 OB 笔记 frontmatter `feishu_doc_token`,避免重复创建


# 飞书 cli token 文件位置(OAuth 流程写入)
FEISHU_TOKEN_PATH = Path.home() / ".feishu-cli" / "token.json"

# 模块级缓存:笔记路径 → doc_token(避免一次 sync 内重复调 cli)
_DOC_TOKEN_CACHE: dict = {}

# 模块级缓存:飞书表"任务标题" → [record_id, ...] (查重用,避免一次 sync 内重复调 cli list)
_RECORDS_TITLE_CACHE: Optional[dict] = None


def get_user_access_token() -> Optional[str]:
    """从 cli OAuth 写入的 token.json 读 user access token。
    返回 None 表示未登录或文件不存在(调用方应 fallback)。
    """
    if not FEISHU_TOKEN_PATH.exists():
        return None
    try:
        data = json.loads(FEISHU_TOKEN_PATH.read_text(encoding="utf-8"))
        return data.get("access_token")
    except Exception:
        return None


def parse_frontmatter(text: str) -> tuple[Optional[dict], str, str]:
    """解析 .md 文件的 frontmatter。

    返回: (frontmatter_dict 或 None, 原 frontmatter 字符串(含 ---), 正文部分)
    无 frontmatter → (None, "", 原文)
    """
    if not text.startswith("---"):
        return None, "", text
    m = re.match(r"^(---\n)(.*?)(\n---\n)(.*)$", text, re.DOTALL)
    if not m:
        return None, "", text
    head_open, body, head_close, rest = m.groups()
    try:
        fm = yaml.safe_load(body)
    except Exception:
        return None, "", text
    fm_str = head_open + body + head_close
    return (fm if isinstance(fm, dict) else None), fm_str, rest


def _format_yaml_value(value) -> str:
    """格式化 YAML value 为单行字符串,优先不加引号(保持视觉简洁)。

    - ISO 8601 datetime → 无引号(Obsidian 偏好,见 base-and-frontmatter.md 三原则)
    - 纯字母数字/_/-/./ → 无引号
    - 其他字符串 → 单引号包裹(内部单引号变 '')
    - 布尔 → 小写 `true` / `false`(YAML 标准 + dataview 解析为 boolean)
    - 非字符串(数字等) → str()
    """
    # ⚠️ bool 必须在 isinstance(int) 之前 check (Python 里 True is int)
    if isinstance(value, bool):
        return "true" if value else "false"
    if not isinstance(value, str):
        return str(value)
    # ISO 8601 datetime: 2026-05-17T19:36:47
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", value):
        return value
    # 纯日期:2026-05-17
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return value
    # 纯字母数字 + 常见安全字符
    if re.match(r"^[a-zA-Z0-9_\-./]+$", value):
        return value
    # 其他:加单引号(转义内部单引号)
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def update_md_frontmatter(md_path: Path, updates: dict) -> bool:
    """安全更新 .md 文件 frontmatter —— 字符串拼接 append-only 风格。

    设计原则:**原 frontmatter 100% 不动**(保留缩进 / 引号风格 / 字段顺序)
    - 已有的 key → 用正则替换那一行(只改值,保留行其他内容)
    - 新的 key → 在 frontmatter --- 之前追加 `key: value` 行

    解决"PyYAML 重新 dump 整个 frontmatter 导致 list 缩进 / 引号风格变化"的 bug
    """
    try:
        text = md_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"⚠️  读 {md_path} 失败: {e}", file=sys.stderr)
        return False

    # 找 frontmatter 边界(用宽松正则匹配 ---\n...\n---\n)
    m = re.match(r"^(---\r?\n)(.*?)(\r?\n---\r?\n)(.*)$", text, re.DOTALL)
    if not m:
        # 无 frontmatter → 创建一个最小骨架(末尾追加在文件头之前)
        new_body_lines = [f"{key}: {_format_yaml_value(value)}" for key, value in updates.items()]
        new_text = "---\n" + "\n".join(new_body_lines) + "\n---\n" + text
        try:
            md_path.write_text(new_text, encoding="utf-8")
            return True
        except Exception as e:
            print(f"⚠️  写 {md_path} 失败: {e}", file=sys.stderr)
            return False

    head_open, body, head_close, rest = m.groups()

    # 逐个 update 字段:替换已有 / 追加新增
    for key, value in updates.items():
        value_str = _format_yaml_value(value)
        new_line = f"{key}: {value_str}"
        # 已有 key 的行(行首,可能含缩进 0;不允许 nested 如 `  feishu_doc_token:`)
        key_re = re.compile(rf"^{re.escape(key)}:[^\n]*$", re.MULTILINE)
        if key_re.search(body):
            body = key_re.sub(new_line, body, count=1)
        else:
            # 追加到 body 末尾(确保前面有换行)
            if body and not body.endswith('\n'):
                body += '\n'
            body += new_line

    new_text = head_open + body + head_close + rest
    try:
        md_path.write_text(new_text, encoding="utf-8")
        return True
    except Exception as e:
        print(f"⚠️  写 {md_path} 失败: {e}", file=sys.stderr)
        return False


def ensure_feishu_doc(md_path: Path, config: dict, force_update: bool = False) -> Optional[str]:
    """确保 .md 笔记已推送到飞书云文档,返回 doc_token。

    策略:
    1. 读笔记 frontmatter,有 feishu_doc_token 且不强制更新 → 直接返回(缓存)
    2. 无 token → 调 feishu-cli doc import 创建新文档(用 user token)→ 写回 frontmatter
    3. 失败 → 返回 None(调用方 fallback 到 wikilink)
    """
    # 模块级缓存避免一次 sync 内多次调 cli
    abs_path = str(md_path.resolve())
    if abs_path in _DOC_TOKEN_CACHE and not force_update:
        return _DOC_TOKEN_CACHE[abs_path]

    try:
        text = md_path.read_text(encoding="utf-8")
    except Exception:
        return None

    fm, _, _ = parse_frontmatter(text)
    existing_token = fm.get("feishu_doc_token") if fm else None
    if existing_token and not force_update:
        _DOC_TOKEN_CACHE[abs_path] = existing_token
        return existing_token

    # 需要创建新 doc
    token = get_user_access_token()
    if not token:
        print(f"⚠️  无 user access token,无法推送 {md_path.name} 到飞书云文档", file=sys.stderr)
        return None

    title = (fm.get("title") if fm else None) or md_path.stem
    doc_folder = config.get("feishu", {}).get("doc_folder_token")

    cli_args = [
        "doc", "import", str(md_path),
        "--title", title,
        "--user-access-token", token,
        "--output", "json",
    ]
    if doc_folder:
        cli_args.extend(["--folder", doc_folder])

    print(f"    ⏳ 推送 {md_path.name} 到飞书云文档...", end="", flush=True)
    try:
        result = run_cli(cli_args)
        doc_id = result.get("document_id")
        if not doc_id:
            print(f" ❌ 失败:cli 返回无 document_id")
            return None
        print(f" ✅ {doc_id}")
        # 写回 frontmatter
        ok = update_md_frontmatter(md_path, {
            "feishu_doc_token": doc_id,
            "feishu_doc_synced_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        })
        if not ok:
            print(f"    ⚠️  doc 创建成功但 frontmatter 回写失败,下次 sync 会重复创建")
        _DOC_TOKEN_CACHE[abs_path] = doc_id
        return doc_id
    except Exception as e:
        print(f" ❌ 失败: {e}")
        return None


def build_records_title_index(config: dict) -> dict:
    """从飞书表 list 全部 record,建 "任务标题" → [record_id list] 索引,用于 CREATE 前查重。

    一次 sync 仅调用一次(模块级缓存),避免每条 task 都调 cli。
    返回结构: {"任务标题文本": ["recXXX", "recYYY", ...]} 同名多条返回多个 id
    """
    global _RECORDS_TITLE_CACHE
    if _RECORDS_TITLE_CACHE is not None:
        return _RECORDS_TITLE_CACHE

    base_token = config["feishu"]["base_token"]
    table_id = config["feishu"]["table_id"]
    title_field_name = config["fields"]["title"]
    print("⏳ 调 cli 拉全表 record 建标题索引(查重用)... ", end="", flush=True)

    index: dict = {}
    try:
        # 飞书 cli `record list` 单次 limit 上限 200,需要分页拉
        all_data: list = []
        all_record_ids: list = []
        fields: list = []
        offset = 0
        page_size = 200
        max_pages = 50  # 兜底:最多 10000 条 record(超过认为表过大)

        for page in range(max_pages):
            result = run_cli([
                "bitable", "record", "list",
                "--base-token", base_token,
                "--table-id", table_id,
                "--limit", str(page_size),
                "--offset", str(offset),
            ])
            page_data = result.get("data", [])
            page_ids = result.get("record_id_list", [])
            if not fields:
                fields = result.get("fields", [])
            all_data.extend(page_data)
            all_record_ids.extend(page_ids)
            # 退出条件:返回 record < page_size 说明已是最后一页
            if len(page_ids) < page_size:
                break
            offset += page_size

        # 找"任务标题"字段在 fields 中的列索引
        try:
            title_col = fields.index(title_field_name)
        except ValueError:
            print(f"⚠️ 字段 '{title_field_name}' 不在 list 返回的 fields 中, 跳过查重")
            _RECORDS_TITLE_CACHE = {}
            return _RECORDS_TITLE_CACHE

        for i, row in enumerate(all_data):
            if i >= len(all_record_ids):
                continue
            if title_col >= len(row):
                continue
            title = row[title_col]
            # 飞书 text 字段可能返回 list of segments
            if isinstance(title, list):
                title = "".join(seg.get("text", "") if isinstance(seg, dict) else str(seg) for seg in title)
            if not title:
                continue
            index.setdefault(str(title).strip(), []).append(all_record_ids[i])

        print(f"✅ 共 {len(all_record_ids)} 条 record, {len(index)} 个独立标题")
    except Exception as e:
        print(f"❌ 失败: {e}, 查重跳过")
        index = {}

    _RECORDS_TITLE_CACHE = index
    return index


def extract_original_note(existing_value: str) -> str:
    """从飞书侧现有 delivery 值里抽出"原话备注:"段(用户手填的诊断/反思)。

    保证多次 sync 时,即使现有值已含 wikilink(覆盖模式),也能保留用户原话。
    解决"第二次 sync 丢原话备注"的 bug。

    模式 1: 第一次 sync 前的纯手写(无 wikilink,无锚点)→ 全文作为原话
    模式 2: 已经被 sync 过(含 wikilink + 锚点)→ 从"原话备注:"提取
    """
    if not existing_value:
        return ""
    has_wikilink = bool(WIKILINK_RE.search(existing_value)) or "obsidian://" in existing_value
    has_anchor = "——自动同步" in existing_value
    # 模式 1: 纯手写
    if not has_wikilink and not has_anchor:
        return existing_value.strip()
    # 模式 2: 已被 sync 过,抽"原话备注:"段
    m = re.search(r"原话备注[::]\s*(.+?)(?=\n\n——自动同步|\Z)", existing_value, re.DOTALL)
    if m:
        return m.group(1).strip()
    return ""


def build_obsidian_uri(file_path: str, vault_name: str) -> str:
    """构造 Obsidian URL Scheme(本机点击 → OB 跳到笔记)。

    格式: obsidian://open?vault=<vault>&file=<path>
    - vault 和 file 都要 URL encode(中文/空格)
    - path 保留 `/` 不编码(让飞书 markdown 识别为路径)
    """
    vault_q = urllib.parse.quote(vault_name, safe='')
    file_q = urllib.parse.quote(file_path, safe='/')
    return f"obsidian://open?vault={vault_q}&file={file_q}"


def format_delivery_link(item: dict, config: dict) -> str:
    """把 1 个产物 item 格式化为飞书侧显示的链接行。

    优先级(3 档降级):
    1. 飞书云文档(enable_doc_sync=true 且 doc 推送成功)→ https://feishu.cn/docx/<id>
    2. Obsidian URI(use_obsidian_uri=true)→ obsidian://open?... ⚠️ 飞书 security 会破坏
    3. wikilink 兜底 → [[xxx]] 灰字
    """
    feishu_cfg = config.get("feishu", {})
    ob_cfg = config.get("ob", {})
    enable_doc = feishu_cfg.get("enable_doc_sync", False)
    use_uri = ob_cfg.get("use_obsidian_uri", False)
    path = item["path"]
    note = item.get("note", "").strip()
    display = note or Path(path).stem

    # === 优先级 1: 飞书云文档(双链:飞书 URL + OB 本地路径) ===
    # 2026-05-19 升级: 「交付」字段同时给出 飞书云文档可点击链接 + OB vault 内相对路径
    # 用户场景:在飞书后台看到飞书云文档 URL 可点击查看;复制 OB 路径回 OB 内 Cmd+O 直接打开本地原版
    if enable_doc:
        # 补 .md 后缀 + 拼绝对路径
        rel_path = path if path.endswith('.md') else path + '.md'
        # path 是相对 vault_root 的(因为 C 路径 backlinks 用 relative_to(VAULT_ROOT))
        abs_md = VAULT_ROOT / rel_path
        if abs_md.exists():
            doc_token = ensure_feishu_doc(abs_md, config)
            if doc_token:
                url_template = feishu_cfg.get("doc_url_template", "https://feishu.cn/docx/{doc_token}")
                doc_url = url_template.format(doc_token=doc_token)
                # 双链格式:`- [name](飞书 URL) · 📁 OB 路径`
                # 用户决策(2026-05-19): 单行点分隔, OB 路径在右侧纯文本(在飞书侧可复制回 OB 打开)
                return f"- [{display}]({doc_url}) · 📁 {rel_path}"
            # doc 推送失败 → 落到下面降级
        # 文件不存在 → 降级到 wikilink(只在 OB 内能跳)

    # === 优先级 2: Obsidian URI(已知飞书会破坏,默认禁用) ===
    if use_uri:
        vault_name = ob_cfg.get("vault_name", "")
        uri_path = path if path.endswith('.md') else path + '.md'
        uri = build_obsidian_uri(uri_path, vault_name)
        return f"- [{display}]({uri})"

    # === 优先级 3: wikilink 兜底 ===
    line = f"- [[{path}]]"
    if note:
        line += f" {note}"
    return line


def build_delivery_value(items: list, existing_value: str, config: dict) -> str:
    """构造飞书侧最终写入的 delivery 文本。

    保护逻辑:
    - 现有值含 wikilink → 之前已自动同步过,直接覆盖
    - 现有值无 wikilink → 手工填的,把原话保留 + append 自动列表
    - 现有值为空 → 直接用 format_template

    Args:
        items: 合并后的产物列表 [{"path", "note"}, ...]
        existing_value: 飞书侧当前 delivery 字段值
        config: 全局配置
    """
    if not items:
        return existing_value or ""

    delivery_cfg = config.get("fields", {}).get("delivery", {})
    format_template = delivery_cfg.get("format_template", "{items_md}")
    append_template = delivery_cfg.get("append_template", "{original_text}\n\n{items_md}")
    sync_date = datetime.now().strftime("%Y-%m-%d")

    # 格式化 items 为 markdown 列表
    # use_obsidian_uri=true → 用 obsidian:// 可点击链接;否则 [[wikilink]] 死链
    items_md_lines = [format_delivery_link(item, config) for item in items]
    items_md = "\n".join(items_md_lines)

    # 统一抽"原话备注"(无论现有值是首次手写还是已被 sync 过都能正确提取)
    # 解决"第二次 sync 丢原话备注"bug
    original_note = extract_original_note(existing_value)

    if original_note:
        # 有原话 → 用 append 模板保留原话
        return append_template.format(
            items_md=items_md,
            original_text=original_note,
            sync_date=sync_date,
        )
    # 无原话 → 用 format 模板(纯交付物列表)
    return format_template.format(items_md=items_md, sync_date=sync_date)


def parse_task_line(line: str, line_idx: int, full_content: str, journal_date: str, config: dict) -> Optional[dict]:
    """解析一行 task,返回结构化字典(或 None 如果不是 task 行)"""
    m = TASK_LINE_RE.match(line)
    if not m:
        return None

    status_char = m.group("status")
    body = m.group("body")

    # 抽标题 + 链接
    title, url = extract_link(body)

    # 跳过纯文本无标题的 task(用户写"燕姐电话说量化开发"这种本地小事)
    # 判定:没有 markdown 链接 + 没有方括号开头(可能用户后续会加)
    # 这里默认这种 task 也参与同步(更激进)——用户后续可以加 `<!-- skip -->` 注释跳过
    # 简化:全部解析,让用户审 dry-run 时决定

    # 抽 emoji 日期 + 优先级
    done_date = extract_emoji_date(body, EMOJI_DONE)
    created_date = extract_emoji_date(body, EMOJI_CREATED)
    canceled_date = extract_emoji_date(body, EMOJI_CANCELED)
    priority = extract_priority(body)

    # === 交付物 D 混合架构 ===
    # A 路径:同行 wikilink
    deliveries_inline = extract_inline_deliveries(body, config)
    # B 路径:下方 callout(先取文本,再从文本抽 wikilinks)
    callout_types = config.get("fields", {}).get("delivery", {}).get("callout_types", [])
    delivery_callout_text = parse_callout_below(full_content, line_idx, callout_types)
    deliveries_callout = extract_callout_deliveries(delivery_callout_text or "")
    # C 路径在 build_fields_payload 阶段才扫(需要 record_id + vault_root)

    # 识别 record_id
    # 优先级 1: 行内 <!-- rec=recXXX --> 注释 (Phase 2.3 短链反查 cache,避免每次 sync 都反查)
    record_id = None
    m_rec = re.search(r'<!--\s*rec=(rec[a-zA-Z0-9]+)\s*-->', line)
    if m_rec:
        record_id = m_rec.group(1)
    # 优先级 2: 从 URL 抽 (长链直接拿 rec_id; 短链返回 27 位 token,后续主流程会触发反查)
    elif url:
        record_id = extract_record_id(url, config)

    return {
        "line_idx": line_idx,           # 在文件中的行号(0-based,用于回写)
        "raw_line": line,                # 原始行(便于精确替换)
        "status_char": status_char,      # [ ] / [x] / [/] / [-]
        "title": title,
        "url": url,
        "record_id": record_id,
        "done_date": done_date,
        "created_date": created_date,
        "canceled_date": canceled_date,
        "priority": priority,
        "deliveries_inline": deliveries_inline,   # A 路径产物列表
        "deliveries_callout": deliveries_callout, # B 路径产物列表
        "delivery_callout_text": delivery_callout_text,  # B 路径原始文本(老代码兼容/未来回退)
        "journal_date": journal_date,    # 所属日志日期(YYYY-MM-DD),用于复盘字段
    }


def parse_journal(file_path: Path) -> list[dict]:
    """解析整个日志文件,返回所有 task 的结构化列表"""
    if not file_path.exists():
        print(f"❌ 文件不存在: {file_path}", file=sys.stderr)
        sys.exit(1)
    content = file_path.read_text(encoding="utf-8")
    # 从文件名抽日期(假设文件名是 YYYY-MM-DD.md)
    journal_date = file_path.stem  # 例如 "2026-05-16"
    if not re.match(r"\d{4}-\d{2}-\d{2}", journal_date):
        print(f"⚠️  文件名不是 YYYY-MM-DD 格式,复盘字段无法自动填: {file_path}", file=sys.stderr)
        journal_date = ""

    config = load_config()
    tasks = []
    lines = content.split("\n")
    for idx, line in enumerate(lines):
        task = parse_task_line(line, idx, content, journal_date, config)
        if task:
            tasks.append(task)
    return tasks


# ============================================================
# task md 模式:解析 task md frontmatter + 正文(2026-05-25 上线)
# 设计参考 rules/feishu-project-sync.md「task md 化架构」section
# ============================================================

def parse_task_md(md_path: Path, config: dict) -> Optional[dict]:
    """解析 task md 文件,返回结构化字典(供 build_fields_payload 用)

    Returns: task dict(和 parse_task_line 同结构 + task md 专属字段 `_task_md_mode=True`)
    或 None(如果文件不是合法的 task md)
    """
    if not md_path.exists():
        print(f"❌ 文件不存在: {md_path}", file=sys.stderr)
        return None

    text = md_path.read_text(encoding="utf-8")
    fm, _, body = parse_frontmatter(text)
    if fm is None:
        print(f"❌ 文件无 frontmatter,不是合法 task md: {md_path}", file=sys.stderr)
        return None

    # 抽标题:优先 H1,fallback 文件名(去掉 YYYY-MM-DD- 前缀)
    title = None
    h1_m = re.search(r'^# +(.+?)$', body, re.MULTILINE)
    if h1_m:
        candidate = h1_m.group(1).strip()
        # 跳过 "<task 标题>" 这种占位符
        if not (candidate.startswith("<") and candidate.endswith(">")):
            title = candidate
    if not title:
        stem = md_path.stem
        m_prefix = re.match(r'^\d{4}-\d{2}-\d{2}-(.+)$', stem)
        title = m_prefix.group(1) if m_prefix else stem

    # status enum → OB checkbox char(供 build_fields_payload 的 status_cfg.map 使用)
    status_map = {
        "todo": " ", "doing": "/", "done": "x", "block": "-", "cancel": "-",
    }
    status_str = fm.get("status") or "todo"
    status_char = status_map.get(status_str, " ")

    # priority enum → OB emoji(用于 dry-run 显示)
    priority_map = {"P0": "🔺", "P1": "⏫", "P2": "🔼", "P3": "🔽"}
    priority_emoji = priority_map.get(fm.get("priority"))

    def _date_str(v):
        """yaml 解析的 datetime/date 对象 → 'YYYY-MM-DD' str"""
        if not v:
            return None
        if isinstance(v, str):
            return v.split("T")[0] if "T" in v else v
        return v.isoformat() if hasattr(v, 'isoformat') else str(v)

    done_date = _date_str(fm.get("done_date"))
    created_date = _date_str(fm.get("created"))

    def extract_section(body_text: str, h2_pattern: str) -> Optional[str]:
        """抽 ## <pattern> 段内容(到下一个 ## 之前),去除 HTML 注释"""
        m = re.search(
            rf'^## +{re.escape(h2_pattern)}.*?\n(.*?)(?=\n## +|\Z)',
            body_text, re.MULTILINE | re.DOTALL,
        )
        if not m:
            return None
        content = m.group(1).strip()
        content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL).strip()
        return content if content else None

    execution_summary = extract_section(body, "📝 执行概述")
    acceptance = extract_section(body, "✅ 验收条件")
    thinking = extract_section(body, "💡 执行思路")
    resources = extract_section(body, "🔗 相关资料")
    retrospective_text = extract_section(body, "🪞 复盘")

    feishu_record = fm.get("feishu_record")
    if feishu_record and not isinstance(feishu_record, str):
        feishu_record = str(feishu_record)

    return {
        # journal task dict 同款字段(给 build_fields_payload 用)
        "line_idx": 0,
        "raw_line": "",
        "status_char": status_char,
        "title": title,
        "url": fm.get("feishu_url"),
        "record_id": feishu_record if feishu_record else None,
        "done_date": done_date,
        "created_date": created_date,
        "canceled_date": None,
        "priority": priority_emoji,
        "deliveries_inline": [],
        "deliveries_callout": [],
        "delivery_callout_text": None,
        "journal_date": created_date,
        # task md 模式专属字段(build_fields_payload 通过 _task_md_mode 标记识别)
        "_task_md_mode": True,
        "_task_md_path": md_path,
        # priority_str 直接传 P0/P1/P2/P3 字符串到飞书"价值优先级"
        # (priority 字段保留 emoji 形态供 journal 兼容 + dry-run 显示)
        "priority_str": fm.get("priority"),
        "category": fm.get("category"),
        "subcategory": fm.get("subcategory"),
        "adhd_priority": fm.get("adhd_priority"),
        "estimate_hours": fm.get("estimate_hours"),
        "efficiency": fm.get("efficiency"),
        "acceptance": acceptance,
        "thinking": thinking,
        "resources": resources,
        "retrospective_text": retrospective_text,
        "execution_summary": execution_summary,
        "due": _date_str(fm.get("due")),
    }


# ============================================================
# 飞书侧:cli 封装
# ============================================================

def parse_cli_output(stdout: str) -> dict:
    """鲁棒解析 cli stdout —— 兼容混合输出(progress 文本 + 末尾 JSON)。

    背景:`doc import` 等长任务的 cli 会先打 "已创建文档..." / "阶段 1/3 ..." 等进度,
    最后才输出 JSON 结果。直接 json.loads(stdout) 会失败。

    算法:
    1. 先试直接解析(纯 JSON 输出场景)
    2. 失败 → 从末尾找最后一个 `}`,回溯到配对的 `{`,解析这段
    3. 还失败 → 返回 {"_raw": stdout}
    """
    try:
        return json.loads(stdout.strip())
    except json.JSONDecodeError:
        pass
    stripped = stdout.rstrip()
    if not stripped.endswith('}'):
        return {"_raw": stdout}
    # 从末尾倒着算 { 和 } 直到平衡(找到最后一个完整 JSON 对象的起点)
    depth = 0
    start = -1
    for i in range(len(stripped) - 1, -1, -1):
        ch = stripped[i]
        if ch == '}':
            depth += 1
        elif ch == '{':
            depth -= 1
            if depth == 0:
                start = i
                break
    if start == -1:
        return {"_raw": stdout}
    try:
        return json.loads(stripped[start:])
    except json.JSONDecodeError:
        return {"_raw": stdout}


def run_cli(args: list[str], stdin: Optional[str] = None) -> dict:
    """统一调用 feishu-cli,返回解析后的 JSON。失败抛异常"""
    cmd = ["feishu-cli"] + args
    proc = subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"cli 失败:\n  命令: {' '.join(cmd)}\n  stderr: {proc.stderr}\n  stdout: {proc.stdout}")
    parsed = parse_cli_output(proc.stdout)
    if "_raw" not in parsed:
        return parsed
    # 进入老 fallback 逻辑(无 JSON 的纯文本输出)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        # 不是 JSON(可能是纯文本输出),返回 raw
        return {"_raw": proc.stdout}


# 模块级:同会话内 enum 匹配缓存,key = (field_id, query) → matched_option_name 或 None
# 2026-05-18 加入(配合 best_match_enum) - 避免对同一 (字段, 候选词) 重复调 cli
_ENUM_MATCH_CACHE: dict[tuple[str, str], Optional[str]] = {}


def best_match_enum(field_id: str, query: str, config: dict) -> Optional[str]:
    """调 feishu-cli field search-options 模糊匹配单/多选字段的 enum 选项

    Args:
        field_id: 飞书字段 id(如 fld4dy5MJj,从 feishu-cli bitable field list 拿)
        query: 候选词(如 "26W20")
        config: 全局配置(用 feishu.base_token / table_id)

    Returns:
        匹配到的 option name 完整字符串(可直接写入 fields payload)
        或 None(未匹配,调用方应跳过此字段写入)

    关键算法(2026-05-18 实证):
        cli 返回的 options 顺序**不保证 best match 优先**(query="26W20" 第 0 个可能是 26W21)
        所以必须遍历所有 options, 找第一个 `query in option.name` 的(子串校验防误匹)

    边界:
        - cli 失败 → 不阻断主流程(对齐 behavior.fail_fast=false), 返回 None
        - 同 (field_id, query) 在同会话内复用 cache, O(1) 命中
    """
    cache_key = (field_id, query)
    if cache_key in _ENUM_MATCH_CACHE:
        return _ENUM_MATCH_CACHE[cache_key]

    try:
        result = run_cli([
            "bitable", "field", "search-options",
            "--base-token", config["feishu"]["base_token"],
            "--table-id", config["feishu"]["table_id"],
            "--field-id", field_id,
            "--query", query,
            "--limit", "10",
        ])
        options = result.get("options", [])
        # 遍历找第一个 query 是 option name 子串的(cli 不保证排序顺序)
        matched: Optional[str] = None
        for opt in options:
            name = opt.get("name", "")
            if query in name:
                matched = name
                break
        _ENUM_MATCH_CACHE[cache_key] = matched
        return matched
    except Exception as e:
        # cli 失败不阻断 sync 主流程(对齐 behavior.fail_fast=false)
        print(f"⚠️  cli search-options 失败 field_id={field_id} query={query}: {e}")
        _ENUM_MATCH_CACHE[cache_key] = None
        return None


def feishu_search_by_short_link(short_link_or_title: str, config: dict) -> Optional[str]:
    """按 task 标题反查飞书 record_id (Phase 2.3 上线 2026-05-18)

    Args:
        short_link_or_title: task 标题字符串(短链 token 不可计算, 飞书无 API 反查,
                              只能用 task 标题作为反查关键字)
        config: 全局配置

    Returns:
        rec_id (rec 开头) 或 None (没找到 / 有歧义)

    实现:
        - 复用 build_records_title_index 的 lazy cache (单次 sync 仅调 1 次 cli)
        - 标题精确匹配 → 单一匹配返回 rec_id
        - 同名多条 → 警告 + 返回 None (歧义, 让用户人工决策)
    """
    title = short_link_or_title.strip() if short_link_or_title else ""
    if not title:
        return None
    title_index = build_records_title_index(config)
    candidates = title_index.get(title, [])
    if len(candidates) == 1:
        return candidates[0]
    elif len(candidates) > 1:
        print(f"    ⚠️  标题 '{title[:40]}' 在飞书有 {len(candidates)} 条同名 record (歧义), 无法自动反查")
        return None
    else:
        return None  # 没找到


def inject_rec_comment_into_line(journal_path: Path, line_idx: int, rec_id: str) -> bool:
    """在 task 行末尾注入 <!-- rec=recXXX --> 注释 cache (Phase 2.3 上线)

    目的: 下次 sync 不再反查, 直接从注释读 rec_id (parse_task_line 内置识别)

    位置: 行末换行符之前
    幂等: 如果行内已有该 rec_id 注释, 不重复添加

    Returns True 表示注入成功 / 已存在
    """
    if not journal_path.exists():
        return False
    with open(journal_path, encoding="utf-8") as f:
        lines = f.readlines()
    if line_idx < 0 or line_idx >= len(lines):
        return False
    line = lines[line_idx]
    # 幂等检查
    if re.search(r'<!--\s*rec=' + re.escape(rec_id) + r'\s*-->', line):
        return True
    # 在行末换行符之前注入
    if line.endswith('\n'):
        new_line = f"{line[:-1]} <!-- rec={rec_id} -->\n"
    else:
        new_line = f"{line} <!-- rec={rec_id} -->"
    lines[line_idx] = new_line
    with open(journal_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return True


def feishu_get_record(record_id: str, config: dict) -> Optional[dict]:
    """读取一条 record 的所有字段值"""
    base_token = config["feishu"]["base_token"]
    table_id = config["feishu"]["table_id"]
    try:
        result = run_cli([
            "bitable", "record", "get",
            "--base-token", base_token,
            "--table-id", table_id,
            "--record-id", record_id,
        ])
        return result
    except RuntimeError as e:
        print(f"⚠️  read record {record_id} 失败: {e}", file=sys.stderr)
        return None


def feishu_upsert_record(record_id: Optional[str], fields: dict, config: dict, dry_run: bool = True) -> dict:
    """创建/更新 record。
    - record_id=None → 创建
    - record_id="rec..." → 更新
    返回 {action, record_id, payload}(dry_run 时不调 cli)
    """
    action = "update" if record_id else "create"
    payload = {"fields": fields}

    if dry_run:
        return {"action": action, "record_id": record_id, "payload": payload, "_dry_run": True}

    base_token = config["feishu"]["base_token"]
    table_id = config["feishu"]["table_id"]
    cli_args = [
        "bitable", "record", "upsert",
        "--base-token", base_token,
        "--table-id", table_id,
        "--config", json.dumps(payload, ensure_ascii=False),
    ]
    if record_id:
        cli_args.extend(["--record-id", record_id])
    result = run_cli(cli_args)
    # cli 返回的 record_id(create 场景拿新 ID)
    # 实测 v3 API 返回平行数组结构:{"data": [["值"]], "record_id_list": ["rec..."], ...}
    new_id = None
    record_id_list = result.get("record_id_list", [])
    if record_id_list:
        new_id = record_id_list[0]
    return {"action": action, "record_id": new_id or record_id, "payload": payload, "result": result}


# ============================================================
# 字段映射:OB 信号 → 飞书 fields
# ============================================================

def build_fields_payload(task: dict, config: dict, vault_root: Path, existing_delivery: str = "") -> dict:
    """根据 task 字典 + config 映射,构造飞书 fields payload

    Args:
        task: parse_task_line 返回的字典
        config: 全局配置
        vault_root: vault 根目录(用于 C 路径反向扫描)
        existing_delivery: 飞书侧现有 delivery 字段值(用于手工保护;新建时传 "")
    """
    fields_cfg = config["fields"]
    out = {}

    # 标题(必填)
    out[fields_cfg["title"]] = task["title"]

    # 执行状态(单选 wrapped in list,飞书多选字段要 array)
    status_cfg = fields_cfg.get("status", {})
    if status_cfg:
        mapped = status_cfg["map"].get(f"[{task['status_char']}]")
        if mapped:
            out[status_cfg["field_name"]] = [mapped]

    # 完成时间(飞书 datetime 字段需要毫秒时间戳)
    done_cfg = fields_cfg.get("done_date", {})
    if done_cfg and task["done_date"]:
        out[done_cfg["field_name"]] = date_to_ms(task["done_date"])

    # 🆕 执行迭代周(单选 enum, 基于完成日 ✅ 反推 ISO 周 → cli best match → 未命中跳过)
    # 2026-05-18 加 - 涉及周看板必填字段(用户截图反馈)
    iter_week_cfg = fields_cfg.get("iteration_week", {})
    if iter_week_cfg and iter_week_cfg.get("field_name") and task["done_date"]:
        candidate = derive_iteration_week_candidate(
            task["done_date"], iter_week_cfg["derive_template"]
        )
        matched = best_match_enum(iter_week_cfg["field_id"], candidate, config)
        if matched:
            out[iter_week_cfg["field_name"]] = [matched]
        # 未命中: 静默跳过(behavior.auto_create_enum=false 同款)

    # 🆕 执行迭代月(同理, 基于完成日 → "{YY} 年 {M} 月" 候选词)
    iter_month_cfg = fields_cfg.get("iteration_month", {})
    if iter_month_cfg and iter_month_cfg.get("field_name") and task["done_date"]:
        candidate = derive_iteration_month_candidate(
            task["done_date"], iter_month_cfg["derive_template"]
        )
        matched = best_match_enum(iter_month_cfg["field_id"], candidate, config)
        if matched:
            out[iter_month_cfg["field_name"]] = [matched]

    # 优先级(只在 field_name 显式配置时才写)
    prio_cfg = fields_cfg.get("priority", {})
    if prio_cfg and prio_cfg.get("field_name") and task["priority"]:
        mapped = prio_cfg["emoji_map"].get(task["priority"])
        if mapped:
            out[prio_cfg["field_name"]] = mapped

    # === 交付物 D 混合 ===
    # 仅对已完成 task 同步交付(用户决策:未完产物不进飞书)
    if task["status_char"] == "x":
        delivery_cfg = fields_cfg.get("delivery", {})
        if delivery_cfg:
            # A 路径(同行)
            inline = task.get("deliveries_inline", [])
            # B 路径(callout)
            callout = task.get("deliveries_callout", [])
            # C 路径(反向 frontmatter,仅当有 record_id 时)
            backlinks = []
            if task.get("record_id") and not is_short_record_id(task["record_id"]):
                backlinks = find_delivery_for_links(task["record_id"], vault_root, config)
            # 合并去重
            merged = merge_deliveries(inline, callout, backlinks)
            if merged:
                delivery_value = build_delivery_value(merged, existing_delivery, config)
                out[delivery_cfg["field_name"]] = delivery_value
                # 副作用:把合并后的 items 挂回 task,用于 dry-run 打印
                task["_delivery_items_merged"] = merged

    # 复盘(自动填日志 wikilink;field_name=null 时跳过 — 用户决策"留给手填")
    retro_cfg = fields_cfg.get("retrospective", {})
    if retro_cfg and retro_cfg.get("field_name") and task["journal_date"]:
        template = retro_cfg["template"]
        out[retro_cfg["field_name"]] = template.format(date=task["journal_date"])

    # === task md 模式专属字段(2026-05-25 上线)===
    # 仅当 task 由 parse_task_md 返回(带 _task_md_mode 标记)时处理
    # 新字段:category / subcategory / adhd_priority / estimate_hours /
    #         efficiency / acceptance / thinking / resources /
    #         retrospective_text / execution_summary
    if task.get("_task_md_mode"):
        task_md_cfg = config.get("task_md_fields", {})
        for ob_key, fcfg in task_md_cfg.items():
            field_name = fcfg.get("field_name")
            if not field_name:
                continue
            value = task.get(ob_key)
            if value is None or value == "":
                continue
            # select(多)字段需要 list 包裹
            if ob_key == "subcategory":
                out[field_name] = value if isinstance(value, list) else [value]
            # number 字段
            elif ob_key == "estimate_hours":
                try:
                    out[field_name] = float(value)
                except (ValueError, TypeError):
                    pass
            # 其他全部当 text / select(单) 处理
            else:
                out[field_name] = str(value)

    return out


def date_to_ms(date_str: str) -> int:
    """YYYY-MM-DD → 毫秒时间戳(UTC+8 当天 00:00:00)
    飞书 datetime 字段写入需要毫秒"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    # 假设是 UTC+8 当天 0 点
    dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
    return int(dt.timestamp() * 1000)


def derive_iteration_week_candidate(done_date_str: str, template: str) -> str:
    """基于完成日 YYYY-MM-DD 算出 ISO 周编号候选词

    例: done_date="2026-05-12", template="{YY}W{NN:02d}" → "26W20"
        (2026-05-12 落在 ISO 2026 第 20 周)

    ⚠️ ISO week 跨年边界陷阱:用 isocalendar().year 而非 dt.year
        例: 2026-01-01 在 ISO 2025 第 53 周 → "25W53"(不是 26W53)
    """
    dt = datetime.strptime(done_date_str, "%Y-%m-%d")
    iso_year, iso_week, _ = dt.isocalendar()  # Python 标准库, ISO 8601 周编号
    yy = iso_year % 100  # 26 (年后两位)
    return template.format(YY=yy, NN=iso_week)


def derive_iteration_month_candidate(done_date_str: str, template: str) -> str:
    """基于完成日算出年月候选词

    例: done_date="2026-05-12", template="{YY} 年 {M} 月" → "26 年 5 月"
    """
    dt = datetime.strptime(done_date_str, "%Y-%m-%d")
    yy = dt.year % 100  # 26
    return template.format(YY=yy, M=dt.month)


# ============================================================
# 主流程:Phase 1 OB → 飞书
# ============================================================

def push_journal(file_path: Path, apply: bool = False, only_completed: bool = False) -> None:
    """主入口:扫日志 + 同步到飞书

    Args:
        file_path: 日志文件路径
        apply: True=真写, False=dry-run
        only_completed: True=只同步 [x] / [-] task, False=全部同步
    """
    print(f"\n{'='*60}")
    print(f"📝 扫描日志: {file_path}")
    if only_completed:
        print(f"📌 模式: 只同步已完成 task ([x] / [-])")
    print(f"{'='*60}\n")

    tasks = parse_journal(file_path)
    if not tasks:
        print("⚠️  未找到任何 task 行")
        return

    # 过滤:只同步已完成 task(如果开关打开)
    if only_completed:
        before_count = len(tasks)
        tasks = [t for t in tasks if t["status_char"] in ("x", "-")]
        skipped = before_count - len(tasks)
        if skipped > 0:
            print(f"⏭  跳过 {skipped} 条未完成 task([ ] 或 [/])\n")

    # 过滤:跳过带 <!-- feishu:skip --> 标记的 task
    tasks = [t for t in tasks if "<!-- feishu:skip -->" not in t["raw_line"]]

    config = load_config()
    print(f"找到 {len(tasks)} 条待处理 task,逐条分析...\n")

    actions = []  # 待执行动作清单
    for i, task in enumerate(tasks, 1):
        print(f"--- Task {i}: {task['title'][:50]}{'...' if len(task['title'])>50 else ''}")
        print(f"    状态: [{task['status_char']}]  优先级: {task['priority'] or '-'}  "
              f"完成日: {task['done_date'] or '-'}  创建日: {task['created_date'] or '-'}")

        # 判断动作
        if not task["url"] or not task["record_id"]:
            # 无链接 → CREATE
            action_type = "CREATE"
            target_record_id = None
            print(f"    🆕 无飞书链接 → 将创建新 record")
            # === 查重(2026-05-17 加,避免同名 record 重复创建)===
            title_index = build_records_title_index(config)
            same_title_records = title_index.get(task["title"].strip(), [])
            if same_title_records:
                print(f"    ⚠️  警告:飞书已有 {len(same_title_records)} 条同名 record:")
                for rid in same_title_records:
                    print(f"       - {rid}  (打开:https://{config['feishu']['tenant_domain']}/base/{config['feishu']['base_token']}?table={config['feishu']['table_id']}&record={rid})")
                print(f"    💡 apply 前你可选:")
                print(f"       ① 取消 sync → 复制飞书 record 长链贴到 OB task 行 → 重跑(走 UPDATE)")
                print(f"       ② 接受 CREATE(飞书将出现 {len(same_title_records) + 1} 条同名 record)")
        else:
            target_record_id = task["record_id"]
            if is_short_record_id(target_record_id):
                # 短链 → 自动按 task 标题反查 rec_id (Phase 2.3 上线 2026-05-18)
                print(f"    🔍 检测到短链 {target_record_id[:15]}..., 按标题反查飞书 record_id...")
                real_rec_id = feishu_search_by_short_link(task["title"], config)
                if not real_rec_id:
                    print(f"    ⏭  反查失败(未找到或歧义), 跳过此 task")
                    continue
                print(f"    ✅ 反查到 {real_rec_id}, apply 后将写入 <!-- rec=... --> 注释 cache")
                target_record_id = real_rec_id
                # 标记: apply 阶段写 rec 注释到 task 行, 下次 sync 不再反查
                task["_inject_rec_comment"] = real_rec_id
            action_type = "UPDATE"
            print(f"    🔄 已有 record {target_record_id} → 将更新字段")

        # 构造 payload(UPDATE 路径先读飞书侧现有 delivery 做手工保护)
        existing_delivery = ""
        if action_type == "UPDATE" and target_record_id:
            existing_delivery = fetch_existing_delivery(target_record_id, config)

        fields_payload = build_fields_payload(task, config, VAULT_ROOT, existing_delivery)

        # dry-run 显示交付物预览(用户决策的核心场景:能看到交付物预览才放心)
        merged = task.get("_delivery_items_merged", [])
        if merged:
            print(f"    📎 交付物 ({len(merged)} 个):")
            for item in merged:
                note = f" — {item.get('note', '')}" if item.get('note') else ""
                print(f"      - [[{item['path']}]]{note}")
            if existing_delivery and not WIKILINK_RE.search(existing_delivery):
                print(f"    🔒 飞书侧已有手工值(无 wikilink) → 走追加模式保留原话")

        print(f"    Payload: {json.dumps(fields_payload, ensure_ascii=False, indent=6)[:500]}")
        print()

        actions.append({
            "type": action_type,
            "task": task,
            "record_id": target_record_id,
            "payload": fields_payload,
        })

    # 汇总报告
    print(f"\n{'='*60}")
    print(f"📊 dry-run 汇总: 共 {len(actions)} 个动作")
    print(f"    🆕 CREATE: {sum(1 for a in actions if a['type'] == 'CREATE')} 条")
    print(f"    🔄 UPDATE: {sum(1 for a in actions if a['type'] == 'UPDATE')} 条")
    print(f"{'='*60}\n")

    if not apply:
        print("📌 这是 dry-run。如需真写,请加 --apply 参数。")
        print("⚠️  写之前必须由用户审核此 dry-run 输出!")
        return

    # === 真写阶段 ===
    print("🚀 开始 apply...\n")
    success = []
    failures = []
    file_content = file_path.read_text(encoding="utf-8")
    lines = file_content.split("\n")

    for i, action in enumerate(actions, 1):
        print(f"--- ({i}/{len(actions)}) {action['type']}: {action['task']['title'][:50]}")
        try:
            result = feishu_upsert_record(
                record_id=action["record_id"],
                fields=action["payload"],
                config=config,
                dry_run=False,
            )
            print(f"    ✅ {action['type']} 成功, record_id={result['record_id']}")

            # 如果是 CREATE, 回写链接到 OB
            if action["type"] == "CREATE" and result["record_id"]:
                new_url = build_record_url(result["record_id"], config)
                old_line = action["task"]["raw_line"]
                new_line = inject_url_into_line(old_line, action["task"], new_url)
                if old_line in file_content:
                    file_content = file_content.replace(old_line, new_line, 1)
                    print(f"    🔗 回写链接到 OB: {new_url[:80]}...")
                else:
                    print(f"    ⚠️  无法在文件中找到原 task 行(可能已被修改),跳过回写")

            # Phase 2.3: UPDATE 且 task 标记了"短链反查"→ 写 <!-- rec=... --> 注释 cache
            # 让下次 sync 不再反查飞书表 (parse_task_line 优先读注释里的 rec_id)
            inject_rec = action["task"].get("_inject_rec_comment")
            if action["type"] == "UPDATE" and inject_rec:
                old_line = action["task"]["raw_line"]
                # 在行末插入注释 (保留 emoji 元数据)
                if old_line.endswith('\n'):
                    new_line = f"{old_line[:-1]} <!-- rec={inject_rec} -->\n"
                else:
                    new_line = f"{old_line} <!-- rec={inject_rec} -->"
                if old_line in file_content:
                    file_content = file_content.replace(old_line, new_line, 1)
                    print(f"    💾 写入 <!-- rec={inject_rec} --> 注释 cache (下次免反查)")
                else:
                    print(f"    ⚠️  无法在文件找到 task 行, 注释 cache 未写(下次仍会反查)")

            success.append(action)
        except Exception as e:
            print(f"    ❌ 失败: {e}")
            failures.append((action, str(e)))

    # 写回 OB(CREATE 或 UPDATE 短链反查 cache 都需要写文件)
    needs_writeback = any(
        a["type"] == "CREATE" or a["task"].get("_inject_rec_comment")
        for a in success
    )
    if needs_writeback:
        file_path.write_text(file_content, encoding="utf-8")
        print(f"\n💾 已回写 {file_path}")

    print(f"\n{'='*60}")
    print(f"📊 apply 完成: 成功 {len(success)} / 失败 {len(failures)} / 总 {len(actions)}")
    if failures:
        print(f"\n❌ 失败详情:")
        for action, err in failures:
            print(f"  - {action['task']['title'][:50]}: {err}")
    print(f"{'='*60}\n")


def push_task_md(md_path: Path, apply: bool = False) -> None:
    """单 task md 推送到飞书(CREATE/UPDATE) — 2026-05-25 上线

    用法:python3 sync.py --task-md path/to/task.md [--apply]

    流程:
    1. parse_task_md 抽 frontmatter + 正文 H2 段
    2. build_fields_payload 转飞书 payload(走 _task_md_mode 分支)
    3. feishu_upsert_record CREATE/UPDATE
    4. 成功后回写 feishu_record + feishu_url 到 task md frontmatter

    铁律 #1 例外(rules/feishu-project-sync.md):
    - 仅"单条 CREATE 新 task"自动跑(空白记录新建,无覆盖风险)
    - UPDATE 仍需 dry-run + 用户审核(由调用方决定是否 --apply)
    """
    config = load_config()

    print(f"\n{'=' * 60}")
    print(f"📝 task md 模式: {md_path}")
    if not apply:
        print(f"📌 dry-run(--apply 才真写)")
    print(f"{'=' * 60}\n")

    task = parse_task_md(md_path, config)
    if task is None:
        sys.exit(1)

    is_create = not task.get("record_id")
    action = "CREATE" if is_create else "UPDATE"

    print(f"--- {action}: {task['title']}")
    print(f"    优先级: {task.get('priority') or '(无)'}")
    print(f"    状态: [{task['status_char']}]")
    if task.get("done_date"):
        print(f"    完成日: {task['done_date']}")
    if task.get("category"):
        print(f"    大类: {task['category']}")
    if task.get("subcategory"):
        print(f"    小类: {task['subcategory']}")
    if task.get("adhd_priority"):
        print(f"    ADHD: {task['adhd_priority']}")
    if task.get("estimate_hours"):
        print(f"    估时: {task['estimate_hours']}h")

    fields = build_fields_payload(task, config, VAULT_ROOT, existing_delivery="")
    print(f"\n    Payload: {json.dumps(fields, ensure_ascii=False, indent=6)[:800]}")

    if not apply:
        print(f"\n📌 dry-run 完成。--apply 真写飞书 + 回写 feishu_record/url 到 task md")
        return

    print(f"\n🚀 开始 {action}...")
    try:
        result = feishu_upsert_record(
            record_id=task.get("record_id"),
            fields=fields,
            config=config,
            dry_run=False,
        )
    except Exception as e:
        print(f"\n❌ {action} 失败: {e}")
        sys.exit(1)

    record_id = result.get("record_id")
    if not record_id:
        print(f"\n❌ {action} 成功但未返回 record_id: {result}")
        sys.exit(1)

    record_url = build_record_url(record_id, config)

    print(f"\n✅ {action} 成功")
    print(f"    record_id: {record_id}")
    print(f"    URL: {record_url[:100]}...")

    updates = {
        "feishu_record": record_id,
        "feishu_url": record_url,
    }
    if update_md_frontmatter(md_path, updates):
        print(f"💾 已回写 feishu_record / feishu_url 到 {md_path.name}")
    else:
        print(f"⚠️  回写 frontmatter 失败,请手动加 feishu_record: {record_id}")


def build_record_url(record_id: str, config: dict) -> str:
    """构造 record 的 markdown 链接 URL(base URL 形式)

    2026-05-19 升级:从 wiki 长链改成 base URL。
    - 旧 wiki 长链:`/wiki/<node_token>?table=...&record=...` —— 走 wiki SDK + bitable SDK 嵌入
      两层 race condition,record 详情面板有时弹有时不弹(实证)
    - 新 base URL:`/base/<base_token>?table=...&record=...` —— 走 bitable SDK 单层
      record 详情面板**稳定弹出**(2026-05-19 用户三次测试验证)

    短链 cli 不支持生成,所以走长链;base URL 比 wiki 长链稳定,选 base。
    """
    cfg = config["feishu"]
    return (
        f"https://{cfg['tenant_domain']}/base/{cfg['base_token']}"
        f"?table={cfg['table_id']}&view={cfg['default_view_id']}&record={record_id}"
    )


def inject_url_into_line(old_line: str, task: dict, new_url: str) -> str:
    """把 new_url 注入到 task 行的 markdown 链接里。
    - 如果原行 `[标题]()` 空 url → 替换 url
    - 如果原行 `[标题]` 无括号 → 替换为 `[标题](new_url)`
    - 如果原行无 markdown 链接 → 在标题外包一层,**保留所有 emoji metadata 到行尾**

    2026-05-19 修复 systematic bug:
    - 原正则 `(\\s+[emoji]|$)` 只匹配第一个 emoji 前的空白,后续 `➕ 日期 ✅ 日期 🆔 ID 🔁 every Sunday` 等全部丢失
    - 改用 `(\\s*[emoji].*)?$` 匹配从第一个 metadata emoji 到行尾的所有内容
    - `\\s*`(原 `\\s+`)处理"标题尾部 emoji 无空格"边界(如 `进行同步🔼`)
    - emoji 集合加 `🔁`(recurring task 标识)
    """
    # 场景 1: [text]() 空 url
    if "]()" in old_line:
        return old_line.replace("]()", f"]({new_url})", 1)
    # 场景 2: 已有 markdown 链接(理论上 CREATE 时不会到这里,防御性)
    if MD_LINK_RE.search(old_line):
        return MD_LINK_RE.sub(lambda m: f"[{m.group('text')}]({new_url})", old_line, count=1)
    # 场景 3: 无 markdown 链接 → 把 task body 包成链接,保留所有 emoji metadata
    m = re.match(
        r"^(\s*-\s+\[[x \-/]\]\s+)(.+?)(\s*[🔺⏫🔼🔽✅➕❌🛫📅🆔🔁].*)?$",
        old_line.rstrip(),
    )
    if m:
        prefix = m.group(1)
        text = m.group(2).strip()
        metadata = m.group(3) or ""
        # 确保 text 和 metadata 之间有空格(处理"标题🔼"无空格情况)
        if metadata and not metadata.startswith(" "):
            metadata = " " + metadata
        return f"{prefix}[{text}]({new_url}){metadata}".rstrip()
    # 兜底:整个 body 包成链接
    return old_line  # 无法处理,返回原样


# ============================================================
# 主流程:Phase 2 飞书 → OB
# ============================================================

def find_vault_root() -> Path:
    """从 sync.py 文件位置 / cwd 向上找含 `.obsidian/` 的目录(vault root)

    优先级:
    1. cwd 向上(用户直接跑 sync.py 时一般 cwd 在 vault 内)
    2. sync.py 文件位置向上(用户 cd 到外面跑时)

    Raises RuntimeError 如果都找不到
    """
    # 尝试 1: cwd 向上
    for start in [Path.cwd(), Path(__file__).resolve().parent]:
        current = start
        while current != current.parent:
            if (current / ".obsidian").exists():
                return current
            current = current.parent
    raise RuntimeError("找不到 vault root (向上未找到 .obsidian/ 目录)")


def filter_today_tasks(records: list, ids: list, fields: list, config: dict) -> list:
    """从 cli list 全表里筛 "是否今日"=true(或 reverse.default_filter 配置)的 task

    Returns: [(record_id, row), ...] 命中 task 列表
    """
    field_name = config["reverse"]["default_filter"]["field_name"]
    if field_name not in fields:
        print(f"⚠️  filter 字段 '{field_name}' 不在飞书表里,跳过 filter(返回空)")
        return []
    field_idx = fields.index(field_name)
    matched = []
    for rid, row in zip(ids, records):
        val = row[field_idx] if field_idx < len(row) else None
        if val:  # Python truthy: checkbox / select / lookup 都 OK
            matched.append((rid, row))
    return matched


def find_existing_in_vault(title: str, vault_root: Path, config: dict) -> list[tuple[Path, int, str]]:
    """按标题前缀 grep 全 vault journals/ 找老 task

    Returns: [(journal_path, line_num, line_text), ...]

    匹配方式: 直接截标题前 N 字符做 grep 关键词(不去【】, 老 task 行里【】也在, 必须一致)
    例: 标题 = "【布丁开发】习惯打卡调整上线"
        关键词 = "【布丁开发】习惯打卡调"(前 10 字, 含【】)
    用 grep --fixed-strings 防止 【】 等特殊字符被当正则解析

    边界:
    - 标题过短 (< 2 字) → 返回空
    - keyword 含 ] 等会破坏 grep arg 解析的字符: --fixed-strings 已处理
    """
    prefix_chars = config["reverse"]["dedup"]["title_prefix_chars"]
    keyword = title[:prefix_chars] if title else ""
    if len(keyword.strip()) < 2:
        return []  # 标题太短, 无法可靠 grep

    journal_dir = vault_root / config["reverse"]["write_target"]["journal_dir"]
    if not journal_dir.exists():
        return []
    try:
        proc = subprocess.run(
            ["grep", "-rn", "--fixed-strings", keyword, str(journal_dir)],
            capture_output=True, text=True,
        )
    except Exception as e:
        print(f"⚠️  grep 失败 keyword={keyword}: {e}")
        return []

    matches = []
    for line in proc.stdout.splitlines():
        # 格式: /path/to/journal.md:LINENUM:行文本
        m = re.match(r'^(.+?\.md):(\d+):(.+)$', line)
        if m:
            matches.append((Path(m.group(1)), int(m.group(2)), m.group(3)))
    return matches


def upgrade_short_link_in_task(journal_path: Path, line_num: int, new_long_url: str) -> bool:
    """把指定日志某行 task 里的短链 markdown link 替换为长链

    安全检查: 替换前确认行内只有 1 个 markdown link, 且 URL 是短链格式
    保留 [text] 部分不动, 只换 ](URL) 里的 URL

    Returns True 替换成功, False 未替换(已是长链或无短链)
    """
    with open(journal_path, encoding="utf-8") as f:
        lines = f.readlines()
    if line_num < 1 or line_num > len(lines):
        return False
    old_line = lines[line_num - 1]

    # 找所有 markdown link
    link_pattern = re.compile(r'\[([^\]]+)\]\((https?://[^\)]+)\)')
    matches = list(link_pattern.finditer(old_line))
    if len(matches) != 1:
        # 安全防护: 行内多个 link 或 0 个, 不动
        return False

    m = matches[0]
    old_url = m.group(2)
    # 只在 URL 是短链格式时替换 (feishu.cn/record/<20+ 位> 不带 ?)
    if not re.search(r'feishu\.cn/record/[A-Za-z0-9]{20,}(?:[?#]|$)', old_url):
        return False  # 已是长链 / 其他格式 / 不动

    # 替换该 URL
    new_line = old_line[:m.start(2)] + new_long_url + old_line[m.end(2):]
    lines[line_num - 1] = new_line
    with open(journal_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return True


def build_ob_task_line_from_record(rid: str, row: list, fields: list, config: dict, today: str) -> tuple[str, bool, bool]:
    """从飞书 record 构造一行 OB Tasks markdown

    Returns:
        (task_line, has_priority, has_fallback_warn)
        task_line: 完整的 markdown 行
        has_priority: True → 写到「🎯 今日计划」段; False → 「🐿️ 今日非计划」段
        has_fallback_warn: True 表示飞书 Done 但完成日空, 降级为 [ ] + 应该 dry-run 报警
    """
    rev_cfg = config["reverse"]["field_to_ob"]

    title = row[fields.index(rev_cfg["title_field"])] or "(无标题)"

    # 状态映射
    status_val = row[fields.index(rev_cfg["status_field"])]
    status_str = status_val[0] if isinstance(status_val, list) and status_val else None
    status_char = rev_cfg["status_map"].get(status_str, " ")

    # 完成日(空时 fallback)
    done_raw = row[fields.index(rev_cfg["done_date_field"])]
    done_date = None
    if done_raw:
        # 飞书 datetime 字符串 "2026-05-15 00:00:00" → "2026-05-15"
        done_date = str(done_raw)[:10]

    has_fallback_warn = False
    if status_char == "x" and not done_date:
        # D7 决策: 降级为 [ ] 未完成 + 警告
        status_char = " "
        has_fallback_warn = True

    # 价值优先级 → emoji
    prio_val = row[fields.index(rev_cfg["priority_field"])]
    prio_str = prio_val[0] if isinstance(prio_val, list) and prio_val else None
    prio_emoji = rev_cfg["priority_map"].get(prio_str, "")
    has_priority = bool(prio_emoji)

    # 拼 wiki 长链(复用 build_record_url)
    url = build_record_url(rid, config)

    # 拼整行: - [s] [title](url) emoji ➕ today ✅ done?
    line = f"- [{status_char}] [{title}]({url})"
    if prio_emoji:
        line += f" {prio_emoji}"
    line += f" ➕ {today}"
    if status_char == "x" and done_date:
        line += f" ✅ {done_date}"
    line += "\n"

    return line, has_priority, has_fallback_warn


def insert_task_to_journal(journal_path: Path, task_line: str, has_priority: bool, config: dict) -> bool:
    """把 task 行插入今日日志的对应段落(在空占位 `- [ ] ` 之前)

    has_priority=True  → 插入「🎯 今日计划」段 query 块 ``` 之后
    has_priority=False → 插入「🐿️ 今日非计划」段 H2 之后

    简化算法: 找段落标题 → 找段落内**第一个**空占位 `- [ ] \n` → 在它之前插入

    Returns True 插入成功
    """
    write_cfg = config["reverse"]["write_target"]
    section_heading = write_cfg["section_with_priority"] if has_priority else write_cfg["section_no_priority"]

    if not journal_path.exists():
        print(f"⚠️  today journal 不存在: {journal_path}")
        return False

    with open(journal_path, encoding="utf-8") as f:
        content = f.read()

    # 找段落起始
    section_idx = content.find(section_heading)
    if section_idx == -1:
        print(f"⚠️  日志里找不到段落: {section_heading}")
        return False

    # 在段落内找下一个 H2(段落边界) 或文件末尾
    next_h2_idx = content.find("\n## ", section_idx + len(section_heading))
    section_end = next_h2_idx if next_h2_idx != -1 else len(content)
    section_body = content[section_idx:section_end]

    # 在段落内找第一个空占位 `- [ ] \n`(含 trailing space)
    placeholder_match = re.search(r'\n- \[ \] *\n', section_body)
    if placeholder_match:
        # 在空占位行**之前**插入新 task 行
        insert_pos_in_section = placeholder_match.start() + 1  # +1 跳过开头的 \n
        absolute_insert_pos = section_idx + insert_pos_in_section
        new_content = content[:absolute_insert_pos] + task_line + content[absolute_insert_pos:]
    else:
        # 没空占位: 追加到段落末尾(下一个 H2 之前)
        new_content = content[:section_end] + task_line + content[section_end:]

    with open(journal_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return True


def pull_from_feishu(since_date: Optional[str] = None, apply: bool = False) -> None:
    """反向同步: 飞书 → OB(Phase 2.2 重写, 2026-05-18)

    简单版(D8 决策):
      - 默认 filter = 「是否今日」=true 全部(不支持 cli flag override)
      - 写到 today journal (不支持 --target-journal)
      - since_date 参数保留兼容但忽略(本 Phase 不用)

    流程:
      1. cli 拉全表 record(client-side filter)
      2. 筛 "是否今日"=true
      3. 对每条 candidate:
         - 按标题 grep 全 vault 查重(rule 坑 #8 教训)
         - 命中老 task → 升级老链(D6),不写新
         - 未命中 → 构造新 task 行(含 fallback 处理 D7)
      4. dry-run 输出: N 新写 / M 升级 / K fallback 警告
      5. apply: 真写入 today + 修改老日志的短链
    """
    config = load_config()
    vault_root = find_vault_root()  # 关键: 找含 .obsidian/ 的目录, 不依赖 cwd
    today = datetime.now().strftime(config["reverse"]["write_target"]["date_format"])
    today_journal = vault_root / config["reverse"]["write_target"]["journal_dir"] / f"{today}.md"

    print(f"\n{'='*60}")
    print(f"📥 反向 pull: 飞书 → {today_journal}")
    print(f"📌 默认 filter: 「{config['reverse']['default_filter']['field_name']}」= truthy")
    print(f"{'='*60}\n")

    # Step 1: cli 拉全表 (复用 list,自动分页扫到 400+)
    print("⏳ cli 拉全表 record...")
    all_records, all_ids = [], []
    fields_meta = None
    offset = 0
    while True:
        result = run_cli([
            "bitable", "record", "list",
            "--base-token", config["feishu"]["base_token"],
            "--table-id", config["feishu"]["table_id"],
            "--limit", "200",
            "--offset", str(offset),
        ])
        page_records = result.get("data", [])
        page_ids = result.get("record_id_list", [])
        if fields_meta is None:
            fields_meta = result.get("fields", [])
        if not page_records:
            break
        all_records.extend(page_records)
        all_ids.extend(page_ids)
        if len(page_records) < 200:
            break
        offset += 200
    print(f"✅ 共 {len(all_records)} 条 record")

    # Step 2: client-side filter
    candidates = filter_today_tasks(all_records, all_ids, fields_meta, config)
    print(f"🔍 client-side filter: 命中 {len(candidates)} 条\n")

    if not candidates:
        print("✅ 无候选 task,vault 与飞书已同步")
        return

    # Step 3: 逐条分析 (查重 / 构造 / fallback)
    plan_new = []         # 未命中查重, 需要新写
    plan_upgrade = []     # 命中查重, 需要升级老链
    plan_warn = []        # fallback 警告 (Done 但完成日空)
    print("逐条分析...\n")
    for i, (rid, row) in enumerate(candidates, 1):
        title = row[fields_meta.index(config["reverse"]["field_to_ob"]["title_field"])] or "(无标题)"
        print(f"--- ({i}/{len(candidates)}) {rid}: {title[:60]}")

        existing = find_existing_in_vault(title, vault_root, config)
        # 分类: 命中今日 vs 命中其他日志
        in_today = [m for m in existing if m[0].resolve() == today_journal.resolve()]
        in_other = [m for m in existing if m[0].resolve() != today_journal.resolve()]

        if in_today:
            # 已经在今日 journal, 跳过(避免重复)— 不论是手动添加还是上次 pull 写的
            print(f"    ⏭  已在今日 journal (line {in_today[0][1]}), 跳过")
        elif in_other:
            print(f"    🔗 查重命中 {len(in_other)} 处其他日志, 将升级短链:")
            for p, ln, txt in in_other[:3]:
                print(f"       📍 {p.name}:{ln}  {txt[:70]}")
            plan_upgrade.append((rid, title, in_other))
        else:
            task_line, has_priority, has_warn = build_ob_task_line_from_record(rid, row, fields_meta, config, today)
            section = "🎯 今日计划" if has_priority else "🐿️ 今日非计划"
            print(f"    🆕 将新写到「{section}」段")
            if has_warn:
                print(f"    ⚠️  fallback: Done 但完成日空, 降级为 [ ] 未完成 (去飞书补完成日)")
                plan_warn.append((rid, title))
            plan_new.append((rid, title, task_line, has_priority))
        print()

    # Step 4: 汇总
    print(f"{'='*60}")
    print(f"📊 dry-run 汇总:")
    print(f"  🆕 新写到 today journal: {len(plan_new)} 条")
    print(f"  🔗 升级老链: {len(plan_upgrade)} 条")
    print(f"  ⚠️  fallback 警告: {len(plan_warn)} 条(去飞书补完成日)")
    print(f"{'='*60}\n")

    if not apply:
        print("📌 这是 dry-run。如需真写,加 --apply 参数。")
        print("⚠️  apply 前必须由用户审核此 dry-run 输出!")
        return

    # Step 5: apply
    print("🚀 开始 apply...\n")
    new_count, upgrade_count = 0, 0
    for rid, title, task_line, has_priority in plan_new:
        if insert_task_to_journal(today_journal, task_line, has_priority, config):
            new_count += 1
            print(f"  ✅ 新写: {title[:60]}")
        else:
            print(f"  ❌ 新写失败: {title[:60]}")

    for rid, title, existing in plan_upgrade:
        new_url = build_record_url(rid, config)
        upgraded_here = 0
        for p, ln, _ in existing:
            if upgrade_short_link_in_task(p, ln, new_url):
                upgraded_here += 1
                print(f"  🔗 升级: {p.name}:{ln}  ({title[:40]})")
        if upgraded_here:
            upgrade_count += 1

    print(f"\n{'='*60}")
    print(f"📊 apply 完成: 新写 {new_count} / 升级 {upgrade_count}")
    print(f"{'='*60}\n")


def scan_vault_record_ids(config: dict) -> set:
    """grep 全 vault 找所有出现过的飞书 record_id / 短链"""
    existing = set()
    vault_root = Path(".")
    # 用 ripgrep 或 fallback 到 Python 遍历
    # 2026-05-19: 加 base/ 路径识别 (wiki 长链已弃用,但保留向后兼容历史 task)
    pattern = re.compile(r"feishu\.cn/(?:record/(\w+)|(?:wiki|base)/[^?]+\?[^)\s]*record=(rec\w+))")
    for md_file in vault_root.rglob("*.md"):
        # 跳过 .obsidian 和 .git
        if any(part.startswith(".") for part in md_file.parts):
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
            for m in pattern.finditer(text):
                rid = m.group(1) or m.group(2)
                if rid:
                    existing.add(rid)
        except Exception:
            pass
    return existing


# ============================================================
# Pull-today 模式(2026-05-26 上线)
# 飞书侧「是否今日」=true → OB task md frontmatter today=true
# 双向对齐 - 飞书 false 时 OB 也跟着 set false
# 配套 rules/feishu-project-sync.md「今日 todo 双层架构」section
# ============================================================

def _fetch_all_records_from_feishu(config: dict) -> tuple:
    """拉飞书全表 record,自动分页(200/页)。

    Returns: (records: list, ids: list, fields_meta: list)
    复用 pull_from_feishu 里同样的拉取逻辑,但抽出为独立函数便于复用。
    """
    all_records, all_ids = [], []
    fields_meta = None
    offset = 0
    while True:
        result = run_cli([
            "bitable", "record", "list",
            "--base-token", config["feishu"]["base_token"],
            "--table-id", config["feishu"]["table_id"],
            "--limit", "200",
            "--offset", str(offset),
        ])
        page_records = result.get("data", [])
        page_ids = result.get("record_id_list", [])
        if fields_meta is None:
            fields_meta = result.get("fields", [])
        if not page_records:
            break
        all_records.extend(page_records)
        all_ids.extend(page_ids)
        if len(page_records) < 200:
            break
        offset += 200
    return all_records, all_ids, fields_meta


def _scan_ob_task_md_by_feishu_record(task_dir: Path) -> dict:
    """扫 04 Inbox/task/ 下所有 .md,按 feishu_record 字段建索引。

    Returns: {rec_id: {"path": Path, "today": bool, "status": str}}
    跳过没 feishu_record 字段的 task md(=本地新建未 sync 飞书的)
    跳过 _ 开头的 _task.base / _说明.md 等
    """
    index = {}
    for md_path in task_dir.rglob("*.md"):
        if md_path.name.startswith("_"):
            continue
        try:
            text = md_path.read_text(encoding="utf-8")
        except Exception:
            continue

        # 简单 frontmatter parse(只读不动)
        m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.DOTALL)
        if not m:
            continue
        fm_text = m.group(1)

        rec_id = None
        today_val = False
        status_val = "todo"
        for line in fm_text.split("\n"):
            line = line.rstrip()
            if line.startswith("feishu_record:"):
                val = line.split(":", 1)[1].strip().strip("'\"")
                # 跳过空值 / 注释
                if val and not val.startswith("#"):
                    rec_id = val
            elif line.startswith("today:"):
                v = line.split(":", 1)[1].strip().strip("'\"").lower()
                today_val = v in ("true", "yes", "1")
            elif line.startswith("status:"):
                v = line.split(":", 1)[1].strip().strip("'\"").lower()
                if v and not v.startswith("#"):
                    status_val = v

        if rec_id:
            index[rec_id] = {"path": md_path, "today": today_val, "status": status_val}

    return index


def pull_today_from_feishu(apply: bool = False) -> None:
    """拉飞书「是否今日」=true 的 record,同步更新 OB task md frontmatter today 字段。

    范围(双向对齐):
    - 飞书 today=true,OB task md today=false → 改 OB today=true(plan_set_true)
    - 飞书 today=false,OB task md today=true → 改 OB today=false(plan_set_false)
    - 飞书 today=true,OB 无对应 task md → 报告(不自动建,提示用户手动建)
    - 飞书 today=true,OB 已 today=true → 跳过(无操作)

    设计决策:
    - 不自动建 task md(避免反向映射 priority/category 等多字段易出错)
    - 用户工作流:飞书 app 勾「是否今日」=true → 跑此命令 → OB today 同步
    - "飞书有 OB 无"场景:用户可在 OB 端 Cmd+P「📝 快记任务」手动建,或不管

    跨日清理策略(rules/feishu-project-sync.md「今日 todo」section):
    - 每日早上**手动**在飞书 app 清掉昨天的「是否今日」标记 + 重新挑(ADHD friendly)
    - 跑此命令时,OB today=true 但飞书 false 的会自动 set false
    """
    config = load_config()
    vault_root = find_vault_root()
    task_dir = vault_root / "04 Inbox" / "task"

    print(f"\n{'='*60}")
    print(f"📥 pull-today: 飞书「是否今日」=true → OB task md today=true")
    print(f"{'='*60}\n")

    if not task_dir.exists():
        print(f"❌ task 目录不存在: {task_dir}")
        return

    # Step 1: 拉飞书全表
    print("⏳ 拉飞书全表 record...")
    all_records, all_ids, fields_meta = _fetch_all_records_from_feishu(config)
    print(f"✅ 飞书共 {len(all_records)} 条 record\n")

    # Step 2: 筛「是否今日」=true 的 candidates
    today_candidates = filter_today_tasks(all_records, all_ids, fields_meta, config)
    today_record_ids = {rid for rid, _ in today_candidates}
    print(f"🔍 飞书「是否今日」=true: {len(today_record_ids)} 条")

    # Step 3: 扫 OB 端 task md 建索引
    print("⏳ 扫 OB task md(按 feishu_record 建索引)...")
    ob_index = _scan_ob_task_md_by_feishu_record(task_dir)
    print(f"✅ OB 共 {len(ob_index)} 个 task md(有 feishu_record 关联的)\n")

    # Step 4: 分类计划
    plan_set_true = []    # 飞书=true, OB 有 today=false → set true
    plan_set_false = []   # 飞书=false, OB 有 today=true → set false
    plan_missing = []     # 飞书=true, OB 无对应 task md → 报告
    plan_skip = []        # 飞书=true, OB 已 today=true → 跳

    title_field_name = config["reverse"]["field_to_ob"]["title_field"]
    title_idx = fields_meta.index(title_field_name) if title_field_name in fields_meta else 0

    for rid, row in today_candidates:
        title = (row[title_idx] if title_idx < len(row) else "") or "(无标题)"
        if rid in ob_index:
            entry = ob_index[rid]
            if entry["today"]:
                plan_skip.append((rid, title, entry["path"]))
            else:
                plan_set_true.append((rid, title, entry["path"]))
        else:
            plan_missing.append((rid, title))

    for rid, entry in ob_index.items():
        if entry["today"] and rid not in today_record_ids:
            plan_set_false.append((rid, entry["path"]))

    # Step 5: 打印计划摘要
    print(f"📋 计划摘要:")
    print(f"  ➡️  设 today=true:    {len(plan_set_true)} 条")
    print(f"  ⬅️  设 today=false:   {len(plan_set_false)} 条")
    print(f"  ⏭️  已是 today,跳过: {len(plan_skip)} 条")
    print(f"  ⚠️  飞书有 OB 无:    {len(plan_missing)} 条")

    if plan_set_true:
        print(f"\n--- 设 today=true({len(plan_set_true)} 条)---")
        for rid, title, p in plan_set_true:
            print(f"  ✅ {p.name[:55]}  ← {rid}")

    if plan_set_false:
        print(f"\n--- 设 today=false({len(plan_set_false)} 条)---")
        for rid, p in plan_set_false:
            print(f"  ⬜ {p.name[:55]}")

    if plan_skip:
        print(f"\n--- 已是 today,跳过({len(plan_skip)} 条)---")
        for rid, title, p in plan_skip[:5]:
            print(f"  ⏭  {p.name[:55]}")
        if len(plan_skip) > 5:
            print(f"  ... 还有 {len(plan_skip) - 5} 条")

    if plan_missing:
        print(f"\n--- ⚠️ 飞书「是否今日」=true 但 OB 无对应 task md({len(plan_missing)} 条)---")
        print(f"    建议:Cmd+P「📝 快记任务」在 OB 端手建,或忽略(下次需要再建)")
        for rid, title in plan_missing[:10]:
            print(f"  🆕 {title[:55]}  rid={rid}")
        if len(plan_missing) > 10:
            print(f"  ... 还有 {len(plan_missing) - 10} 条")

    if not (plan_set_true or plan_set_false):
        print(f"\n✅ OB ↔ 飞书 today 状态已对齐,无需更新")
        return

    if not apply:
        print(f"\n📌 dry-run 完成。--apply 真写 frontmatter")
        return

    # Step 6: apply
    print(f"\n🚀 开始 apply...")
    success_count = 0
    fail_count = 0
    for rid, title, p in plan_set_true:
        if update_md_frontmatter(p, {"today": True}):
            print(f"  ✅ {p.name}: today → true")
            success_count += 1
        else:
            print(f"  ❌ {p.name}: 更新失败")
            fail_count += 1

    for rid, p in plan_set_false:
        if update_md_frontmatter(p, {"today": False}):
            print(f"  ✅ {p.name}: today → false")
            success_count += 1
        else:
            print(f"  ❌ {p.name}: 更新失败")
            fail_count += 1

    print(f"\n✅ pull-today 完成({success_count} 成功 / {fail_count} 失败)")


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="飞书项目同步 - OB ↔ 飞书项目管理多维表",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("path", nargs="?", help="日志文件路径(push 模式必填)")
    parser.add_argument("--apply", action="store_true", help="真写(默认 dry-run)")
    parser.add_argument("--pull", action="store_true", help="反向同步:从飞书拉到 OB(老:写 journal inline)")
    parser.add_argument("--pull-today", action="store_true",
                        help="2026-05-26 上线:飞书「是否今日」=true → OB task md frontmatter today=true(双向对齐)")
    parser.add_argument("--since", help="--pull 模式的起始日期(YYYY-MM-DD)")
    parser.add_argument("--only-completed", action="store_true",
                        help="只同步已完成 task ([x] / [-]),跳过未完成的")
    parser.add_argument("--task-md", help="task md 模式:单 task md 推送到飞书(CREATE/UPDATE)")
    args = parser.parse_args()

    if args.pull_today:
        pull_today_from_feishu(apply=args.apply)
    elif args.pull:
        pull_from_feishu(since_date=args.since, apply=args.apply)
    elif args.task_md:
        push_task_md(Path(args.task_md), apply=args.apply)
    elif args.path:
        push_journal(Path(args.path), apply=args.apply, only_completed=args.only_completed)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
