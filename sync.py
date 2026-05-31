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
  - 脚本会自己找到 vault 根目录,两种方式(任选其一):
    1. 显式传 `--vault /path/to/OB`(推荐,适合 Claude Code 等不便 cd 的场景)
    2. 从 vault 内某级目录跑(脚本自动向上找 `.obsidian/`)
  - 配置文件 config.yaml 在脚本同目录
"""

import argparse                  # 命令行参数解析
import json                      # 调 cli 时构造 payload
import os                        # chdir 到 vault(--vault 参数)
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
# v0.3.2 修复:旧版用 `SCRIPT_DIR.parents[4]` 假设 sync.py 在固定深度的 vault 子目录,
# 但 sync.py 通常是 symlink → Path(__file__).resolve() 跟符号链接跳到仓库真实位置,
# parents[4] 不再是 vault 根而是 `/Users/<u>/` 之类,导致 line 797 backlinks 找错路径。
# 新版:初始 = cwd,main() 处理 --vault 后会刷新为 vault_path(用 global 声明)
VAULT_ROOT = Path.cwd()

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


def _now_with_tz(config: Optional[dict] = None) -> datetime:
    """v0.5.4(2026-05-30)根治:统一拿带时区的"现在",**默认 Asia/Shanghai**

    决策(v0.5.4):**默认改为 Asia/Shanghai**(不再 'local')
    - 用户跨时区工作场景下,mac TZ 可能是 PDT 等异地时区,但飞书 +
      Obsidian Daily Notes 都按北京时间 → sync.py 算"今天"必须跟它们对齐
    - v0.5.1 default 'local' 假设"mac TZ = 工作时区"导致跨时区错位 bug
    - v0.5.4 default 'Asia/Shanghai' = 老 v0.3.3→v0.5.0 行为的回归

    config.behavior.timezone 可选值:
    - 'Asia/Shanghai'(默认 v0.5.4+): 强制北京时间
    - 'local': mac 系统本地时区(只在确实想跟 mac 系统对齐时显式设)
    - 其他 IANA 时区名 / UTC±N offset
    """
    if config is None:
        return datetime.now(timezone(timedelta(hours=8)))
    tz_name = (config.get("behavior") or {}).get("timezone", "Asia/Shanghai")
    if tz_name == "Asia/Shanghai":
        return datetime.now(timezone(timedelta(hours=8)))
    if tz_name == "local":
        return datetime.now().astimezone()
    # IANA 时区(zoneinfo,Python 3.9+)
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        # 解析失败 → fallback Asia/Shanghai + 打 warning
        print(f"⚠️  config.behavior.timezone='{tz_name}' 无法解析,fallback Asia/Shanghai", file=sys.stderr)
        return datetime.now(timezone(timedelta(hours=8)))


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
        if not text.startswith("---"):
            continue
        # v0.6.2(2026-05-30):走 parse_frontmatter 统一 YAML 解析。
        # 内部已经只截 frontmatter 段(不 parse 全文),性能 OK,
        # 自带 v0.5.4 损坏抢救 fallback(防御 list 字段被 inline + 孤立 block 混存)
        fm, _, _ = parse_frontmatter(text)
        if not fm:
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


def _repair_corrupted_block_list_yaml(body: str) -> str:
    """v0.5.4(2026-05-30)Bug B 配套:从损坏的 YAML body 抢救 inline + 孤立 block list 数据

    场景:历史上 update_md_frontmatter regex bug 导致下面这种损坏:
        today_history: [2026-05-30]
          - 2026-05-27
          - 2026-05-28
        (下一个 key)

    inline `[2026-05-30]` close 了字段,后续 `  - x` 在 YAML 语法层面无 parent → parse error
    抢救:把 inline 元素 + 孤立 block 子项 union(去重保序),重写为 inline 单行

    Returns: 修复后的 body 字符串(可能 == 原 body 如果没检测到损坏)
    """
    lines = body.split("\n")
    repaired = []
    i = 0
    # `key: [a, b, c]` 形式(inline flow list)
    inline_re = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*\[(.*?)\]\s*$")
    # `  - x` 形式(缩进 block list 子项)
    block_item_re = re.compile(r"^[ \t]+-\s*(.+?)\s*$")
    while i < len(lines):
        line = lines[i]
        m = inline_re.match(line)
        if not m:
            repaired.append(line)
            i += 1
            continue
        # 检测后续是否有"孤立"block list 子项(损坏标志)
        j = i + 1
        block_items: list = []
        while j < len(lines):
            bm = block_item_re.match(lines[j])
            if not bm:
                break
            block_items.append(bm.group(1))
            j += 1
        if not block_items:
            # 干净的 inline list,不动
            repaired.append(line)
            i += 1
            continue
        # 损坏命中:合并 inline 元素 + block 元素,去重保序
        key = m.group(1)
        inline_str = m.group(2).strip()
        inline_items = []
        if inline_str:
            inline_items = [x.strip() for x in inline_str.split(",") if x.strip()]
        seen = set()
        merged = []
        for v in inline_items + block_items:
            if v not in seen:
                seen.add(v)
                merged.append(v)
        repaired.append(f"{key}: [{', '.join(merged)}]")
        i = j  # 跳过孤立 block 子项
    return "\n".join(repaired)


def parse_frontmatter(text: str) -> tuple[Optional[dict], str, str]:
    """解析 .md 文件的 frontmatter。

    返回: (frontmatter_dict 或 None, 原 frontmatter 字符串(含 ---), 正文部分)
    无 frontmatter → (None, "", 原文)

    v0.5.4(2026-05-30)Bug B 根治:yaml.safe_load 失败时,先调
    _repair_corrupted_block_list_yaml 抢救历史损坏(inline + 孤立 block list 混存),
    再 parse。这样 today_history 不会因为一次损坏永远只剩"今天"那 1 个元素。
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
        # v0.5.4 抢救:合并 inline + 孤立 block list 后再 parse
        try:
            repaired_body = _repair_corrupted_block_list_yaml(body)
            fm = yaml.safe_load(repaired_body)
            body = repaired_body  # 下游写回时是治好的版本
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
    - list → inline YAML `[a, b, c]`(元素递归格式化,2026-05-26 v0.3.0 加,for today_history)
    - 非字符串(数字等) → str()
    """
    # ⚠️ bool 必须在 isinstance(int) 之前 check (Python 里 True is int)
    if isinstance(value, bool):
        return "true" if value else "false"
    # list → inline YAML(2026-05-26 v0.3.0 加,for today_history 事件流)
    # v0.4.0+ Step 3(2026-05-29)反转决策:回到 unquoted ISO date —
    # console 诊断证明 unquoted YAML date → dataview luxon DateTime → contains 比较正确工作
    # quoted string 反而被 dataview 当 string,跟 this.file.day(DateTime)类型不匹配
    if isinstance(value, list):
        items = [_format_yaml_value(v) for v in value]
        return "[" + ", ".join(items) + "]"
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
    # v0.3.7: Obsidian wikilink 形态(`[[xxx]]`)用双引号包裹,跟 OB 端约定一致
    # (parent_project / 日志 等字段都走这条路径)
    if value.startswith("[[") and value.endswith("]]"):
        return f'"{value}"'
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
        # v0.3.6: 空字符串特例 → 写 `key:`(纯空,无引号无值)
        # 否则 _format_yaml_value("") 返回 `''`,dataview 把 `''` 当 truthy 漏过滤
        if value == "":
            new_line = f"{key}:"
        else:
            value_str = _format_yaml_value(value)
            new_line = f"{key}: {value_str}"
        # v0.5.4(2026-05-30)Bug A 根治:匹配 key 行 + **连续缩进行**(YAML block list 子项 / 多行值)
        # 旧 regex `^{key}:[^\n]*$` 只匹配 key 那一行,block list 子项 `  - x` 不被吞 →
        # 替换后 inline 新值跟孤立 block 子项混存 → PyYAML 解析失败 → today_history 损坏死循环
        # 新 regex 吞掉 key 行 + 紧跟的所有 `[ \t]+...` 缩进行(不缩进的下一个 key 行不吞)
        key_block_re = re.compile(
            rf"^{re.escape(key)}:[^\n]*(?:\n[ \t]+[^\n]*)*",
            re.MULTILINE,
        )
        if key_block_re.search(body):
            body = key_block_re.sub(new_line, body, count=1)
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


def inject_completion_link(md_path: Path, title: str, record_url: str) -> bool:
    """task md「## ✅ 完成标记」段下的裸 `- [ ] <title>` 行 → 替换为带 URL 的 markdown link
    `- [ ] [<title>](record_url)`,让 dataview TASK 渲染时变成可点击链接(直达飞书 record)

    2026-05-26 v0.2.4 加 — 修 userscript 模板里说"sync 后自动改 link"但 sync.py 没实现的 bug

    幂等:
    - 行已经是 markdown link 形式([text](url))→ 不动,返回 False
    - 找不到匹配的 checkbox 行 → 返回 False(不报错,不影响主流程)
    - 成功改写 → 返回 True

    匹配规则:
    - 找「## ✅ 完成标记」段标题(或包含该字符串的 H2 标题)
    - 该段之后第一个 `- [ ]` / `- [x]` 等 checkbox 行
    - 跳过 `<!-- -->` HTML 注释 / 空行
    - 行 body 已是 `[text](url)` → 视为已处理,不动
    """
    try:
        text = md_path.read_text(encoding="utf-8")
        lines = text.split("\n")
    except Exception as e:
        print(f"⚠️  inject_completion_link 读文件失败: {e}", file=sys.stderr)
        return False

    # 1. 定位「## ✅ 完成标记」段标题行
    marker_idx = None
    for i, line in enumerate(lines):
        if line.startswith("## ") and "完成标记" in line:
            marker_idx = i
            break
    if marker_idx is None:
        return False

    # 2. 在该段(到下一个 H2 之前)找第一个 checkbox 行
    checkbox_re = re.compile(r"^(?P<prefix>\s*-\s+\[[ x\-/]\]\s+)(?P<body>.+)$")
    link_re = re.compile(r"^\[.+?\]\(.+?\)\s*$")  # 已是 [text](url) 形式
    for i in range(marker_idx + 1, len(lines)):
        line = lines[i]
        if line.startswith("## "):  # 进入下一段,停止
            break
        stripped = line.rstrip()
        m = checkbox_re.match(stripped)
        if not m:
            continue
        body = m.group("body").strip()
        if link_re.match(body):
            return False  # 已经是 markdown link,不重复改
        # 改写:- [ ] <body> → - [ ] [<body>](url)
        # 注意:用 body 作为 link text(而非 title 参数),避免 title 含特殊字符不匹配
        lines[i] = f'{m.group("prefix")}[{body}]({record_url})'
        try:
            md_path.write_text("\n".join(lines), encoding="utf-8")
            return True
        except Exception as e:
            print(f"⚠️  inject_completion_link 写文件失败: {e}", file=sys.stderr)
            return False

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
            # v0.5.1: 走 _now_with_tz 尊重 config.behavior.timezone
            "feishu_doc_synced_at": _now_with_tz(config).strftime("%Y-%m-%dT%H:%M:%S"),
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
    # v0.5.1: 走 _now_with_tz 尊重 config.behavior.timezone
    sync_date = _now_with_tz(config).strftime("%Y-%m-%d")

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

# v0.6.0(2026-05-29):执行明细 key=val 简写 → 内部 key
# v0.6.7(2026-05-30):key 中文化(用户反馈"中文更容易识别"),英文 alias 保留向后兼容
# OB 端写「计划=... / 估时=2 / 用时=1.5 / 完成度=标准完成 / 复盘=...」
# 老 task md 含英文 key(plan/est/act/done/review)仍能解析,下次 push 自动 rewrite 为中文
_DETAIL_KEY_ALIASES = {
    # 中文 key(v0.6.7 主用,写入侧统一输出这套)
    "计划": "plan",
    "估时": "estimate_hours",
    "用时": "actual_hours",
    "完成度": "completion",
    "复盘": "review",
    # 英文 key(v0.6.0~v0.6.6 老数据 + 程序员习惯,解析向后兼容)
    "plan": "plan",
    "review": "review",
    "est": "estimate_hours",
    "act": "actual_hours",
    "done": "completion",
}
_DETAIL_NUMERIC_KEYS = {"estimate_hours", "actual_hours"}

# v0.6.7(2026-05-30):明细段渲染去 emoji,纯文本易编辑
# 用户反馈:明细段是要事后**手动修改**的(不是一次性写入),emoji 会被 Obsidian 渲染成
# checkbox/icon 阻碍编辑;改纯首字母大写英文(Todo/Done/Doing/SubDone/Block/Cancel/Idea)
# 解析端依然容忍 emoji+纯文本+小写多种历史写法 → _normalize_status 抽英文字母 lowercase
# 老 task md 含 emoji 的明细段下次 push 时自动 normalize(_render_detail_line rewrite)
_STATUS_DISPLAY = {
    "todo": "Todo",
    "doing": "Doing",
    "subdone": "SubDone",
    "done": "Done",
    "block": "Block",
    "cancel": "Cancel",
    "idea": "Idea",
}
_STATUS_INTERNAL_VALID = set(_STATUS_DISPLAY.keys())


def _normalize_status(raw: str) -> str:
    """任意状态值(含 emoji/大小写)→ OB 内部小写 enum。
    容忍输入:"todo" / "Todo" / "⬜ Todo" / "TODO" 都归到 "todo"。
    未识别 → "todo" fallback(防御性)。
    """
    if not raw:
        return "todo"
    letters = re.sub(r'[^a-zA-Z]', '', raw).lower()
    return letters if letters in _STATUS_INTERNAL_VALID else "todo"


def parse_execution_details(body_text: str) -> list[dict]:
    """抽 task md「## 📈 执行明细」段,解析每行为 dict。

    v0.6.0(2026-05-29)加 — daily execution log 子表数据源。

    格式(每行,v0.6.7 起 key 中文化,解析仍兼容英文):
        - YYYY-MM-DD | 状态 | 计划=... / 估时=2 / 用时=1.5 / 完成度=标准完成 / 复盘=...

    Returns: [{date, status, plan?, review?, estimate_hours?, actual_hours?, completion?}, ...]
             按日期升序排列。同日多行 → 后者覆盖前者(OB 端最新意图为准)。

    边界:
    - 段缺失 / 空 → []
    - 行不符合格式(缺日期 / 日期格式错 / 缺状态)→ 跳过
    - key=val 中未知 key → 忽略(向后兼容,未来加 key 不报错)
    - 数值字段转 float 失败 → 跳过该 key
    """
    m = re.search(
        r'^## +📈 +执行明细.*?\n(.*?)(?=\n## +|\Z)',
        body_text, re.MULTILINE | re.DOTALL,
    )
    if not m:
        return []
    section = re.sub(r'<!--.*?-->', '', m.group(1), flags=re.DOTALL)

    details_by_date: dict[str, dict] = {}
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("-"):
            continue
        line = line[1:].strip()  # 去 "- "
        parts = [p.strip() for p in line.split("|", 2)]
        if len(parts) < 2:
            continue
        date_str = parts[0]
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
            continue
        # v0.6.1: status 容忍 emoji/大小写,归一为内部小写 enum
        status_str = _normalize_status(parts[1])
        item = {"date": date_str, "status": status_str}
        # 第 3 段:key=val 列表,/ 分隔
        if len(parts) == 3 and parts[2]:
            for kv in parts[2].split("/"):
                kv = kv.strip()
                if "=" not in kv:
                    continue
                key, val = kv.split("=", 1)
                key, val = key.strip().lower(), val.strip()
                if not val or key not in _DETAIL_KEY_ALIASES:
                    continue
                internal = _DETAIL_KEY_ALIASES[key]
                if internal in _DETAIL_NUMERIC_KEYS:
                    try:
                        item[internal] = float(val)
                    except ValueError:
                        pass
                else:
                    item[internal] = val
        details_by_date[date_str] = item

    return [details_by_date[d] for d in sorted(details_by_date)]


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
    # v0.3.5(2026-05-27):加 subdone/idea — inline checkbox 4 字符表达不出 7 态,
    # subdone 视觉同 doing,idea 视觉同 todo,frontmatter.status 才是真相源
    # (build_fields_payload 通过 fm_status 直接 7 态映射,这里只服务 inline 兼容层)
    status_map = {
        "todo": " ", "doing": "/", "subdone": "/",
        "done": "x", "block": "-", "cancel": "-",
        "idea": " ",
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

    def _coerce_bool(v):
        """frontmatter bool 字段值 → Python bool 或 None
        - YAML 已解析的 bool → 直接返回
        - 字符串 "true"/"false"/"yes"/"no"/"1"/"0" → 转 bool
        - None / "" → None(表示字段未设置,sync.py 跳过同步)
        """
        if v is None or v == "":
            return None
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        if s in ("true", "yes", "1"):
            return True
        if s in ("false", "no", "0"):
            return False
        return None

    def _strip_wikilink(v):
        """frontmatter wikilink 字段值 → 纯名字
        例:'[[06 小工具开发]]' → '06 小工具开发'
            '06 小工具开发' → '06 小工具开发'(无 wikilink 直接返回)
            None / '' → None
        """
        if not v:
            return None
        s = str(v).strip()
        m = re.match(r'^\[\[([^\]|]+)(?:\|[^\]]*)?\]\]$', s)
        return m.group(1).strip() if m else s

    def _ensure_list(v):
        """frontmatter list 字段值 → list[str]
        - YAML 解析的 list → 直接转 str list
        - 单 str → 包成 1-elem list
        - None / '' → 空 list
        v0.3.5 加,用于 iteration_month / iteration_week 多选支持
        """
        if v is None or v == "":
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if x is not None and str(x).strip()]
        s = str(v).strip()
        return [s] if s else []

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
    # v0.4.0(2026-05-28):5 字段补全 — 新加 H2 段 + 3 frontmatter
    delivery_text = extract_section(body, "📦 交付")
    user_story_text = extract_section(body, "👥 用户故事")

    feishu_record = fm.get("feishu_record")
    if feishu_record and not isinstance(feishu_record, str):
        feishu_record = str(feishu_record)

    return {
        # journal task dict 同款字段(给 build_fields_payload 用)
        "line_idx": 0,
        "raw_line": "",
        "status_char": status_char,
        # v0.3.5(2026-05-27):带出 frontmatter.status 原值,build_fields_payload 优先用此 7 态直接映射
        "fm_status": status_str,
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
        # v0.3.8: project_minor(项目小类,task 表 multi-select)— 任务内容细分类型
        # frontmatter 写 list,sync.py 推飞书「项目小类」字段;Cmd+P 快记任务弹最近 5 条
        "project_minor": _ensure_list(fm.get("project_minor")),
        "adhd_priority": fm.get("adhd_priority"),
        "estimate_hours": fm.get("estimate_hours"),
        # v0.4.0(2026-05-28): actual_hours / quality / parent_task / delivery / user_story
        "actual_hours": fm.get("actual_hours"),
        "efficiency": fm.get("efficiency"),
        "quality": fm.get("quality"),
        "acceptance": acceptance,
        "thinking": thinking,
        "resources": resources,
        "retrospective_text": retrospective_text,
        "execution_summary": execution_summary,
        "delivery": delivery_text,
        "user_story": user_story_text,
        # parent_task: "[[2026-05-20-XXX]]" → "2026-05-20-XXX"(裸 stem)
        # build_fields_payload 时再做 vault 查 record_id 解析
        "parent_task": _strip_wikilink(fm.get("parent_task")),
        "due": _date_str(fm.get("due")),
        # parent_project: 2026-05-26 v0.2.2 加 — task 关联到具体大项目
        # frontmatter 形如 `parent_project: "[[<项目名>]]"` → 抽出项目名(去掉 [[]])
        "parent_project": _strip_wikilink(fm.get("parent_project")),
        # parent_subproject: v0.3.5 加,小类(配合 Cmd+P 快记任务新菜单)
        "parent_subproject": _strip_wikilink(fm.get("parent_subproject")),
        # iteration_*: v0.3.5 加,允许在 CREATE 时主动写(而非只在完成时 derive)
        # YAML inline list 或单 str 都兼容;build_fields_payload 优先用此值
        "iteration_month": _ensure_list(fm.get("iteration_month")),
        "iteration_week": _ensure_list(fm.get("iteration_week")),
        # today_flag: 2026-05-26 v0.2.4 加 — 是否今日
        # YAML 已解析为 bool;但用户手写 "true"/"false" 字符串也兼容
        "today_flag": _coerce_bool(fm.get("today")),
        # v0.6.0(2026-05-29):执行明细 — daily 子表数据源
        # list of dict,sync.py push 时跟飞书子表 diff 后补差异
        "execution_details": parse_execution_details(body),
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


# 模块级:link 关联表的 名字→record_id 索引缓存,key=link_table_id
# v0.2.3 加入(配合 parent_project link 字段)— 同进程内只拉一次关联表,避免重复 API 调用
_LINK_TABLE_INDEX_CACHE: dict[str, dict[str, str]] = {}


def build_link_table_index(link_table_id: str, name_field: str, config: dict) -> dict[str, str]:
    """拉关联表所有 record,建 {项目名: record_id} 索引(模块级缓存)

    Args:
        link_table_id: 被关联表 table_id(如「产品项目表」tblZ5Zu8v6m5AUx0)
        name_field: 关联表里项目名所在字段(如「产品项目名」)
        config: 全局 config(用 feishu.base_token)

    Returns: {项目名: record_id} 映射;失败返回空 dict(不阻断主流程)

    实现细节:
        飞书 v3 record list 返回平行数组结构:
            {"data": [["项目1名", ...], ["项目2名", ...]], "fields": [...], "record_id_list": [...]}
        通过 fields.index(name_field) 找列号,zip data 和 record_id_list。
    """
    if link_table_id in _LINK_TABLE_INDEX_CACHE:
        return _LINK_TABLE_INDEX_CACHE[link_table_id]

    base_token = config["feishu"]["base_token"]
    try:
        result = run_cli([
            "bitable", "record", "list",
            "--base-token", base_token,
            "--table-id", link_table_id,
        ])
    except Exception as e:
        print(f"⚠️  拉 link 关联表 {link_table_id} 失败,parent_project 同步跳过: {e}")
        _LINK_TABLE_INDEX_CACHE[link_table_id] = {}
        return {}

    fields = result.get("fields", [])
    rows = result.get("data", [])
    ids = result.get("record_id_list", [])

    if name_field not in fields:
        print(f"⚠️  关联表 {link_table_id} 没有字段「{name_field}」,parent_project 同步跳过")
        _LINK_TABLE_INDEX_CACHE[link_table_id] = {}
        return {}

    name_idx = fields.index(name_field)
    index: dict[str, str] = {}
    for i, row in enumerate(rows):
        if i >= len(ids):
            break
        name = row[name_idx] if name_idx < len(row) else None
        # name 一般是字符串;防御性跳过 dict/list 等异常类型
        if isinstance(name, str) and name.strip():
            index[name.strip()] = ids[i]

    _LINK_TABLE_INDEX_CACHE[link_table_id] = index
    return index


def resolve_link_record_id(
    ob_value: str,
    link_table_id: str,
    name_field: str,
    strip_prefix_regex: str,
    config: dict,
    override_map: Optional[dict] = None,
) -> Optional[str]:
    """把 OB 端名字(可能含「00 」「01 」等数字前缀)解析为飞书关联表 record_id

    流程:
    0. override_map 命中 → 替换为目标名(用于 OB 名 ≠ 飞书 record 名 / 强制 link 到二级)
    1. 用 strip_prefix_regex 去 OB 名字前缀(如 "00 布丁" → "布丁";留空字符串则不去)
    2. 在 link 关联表索引里精确匹配(先去前缀版本,再原值)
    3. 失败 → 打 warning + 返回 None,调用方跳过该字段

    Args:
        ob_value: OB frontmatter 抽出的名字(已去 wikilink 括号,如 "00 布丁")
        link_table_id: 关联表 table_id
        name_field: 关联表里项目名字段
        strip_prefix_regex: 去前缀正则(可空字符串 = 禁用)
        config: 全局 config
        override_map: OB 名 → 飞书 record name 的直接映射(如 zhixinggame → 布丁开发)

    Returns: 匹配到的 record_id,或 None
    """
    if not ob_value:
        return None

    # 优先级 0: override_map(支持 OB 端原名或去前缀后的名字)
    if override_map:
        if ob_value in override_map:
            ob_value = override_map[ob_value]
        else:
            stripped_for_override = re.sub(strip_prefix_regex, "", ob_value).strip() if strip_prefix_regex else ob_value
            if stripped_for_override in override_map:
                ob_value = override_map[stripped_for_override]

    index = build_link_table_index(link_table_id, name_field, config)
    if not index:
        return None  # build_link_table_index 已打 warning

    # 优先级 1: 去前缀后精确匹配("00 布丁" → "布丁")
    stripped = re.sub(strip_prefix_regex, "", ob_value).strip() if strip_prefix_regex else ob_value.strip()
    if stripped in index:
        return index[stripped]

    # 优先级 2: 原值精确匹配(防御:用户可能直接写无前缀名 / override 命中后的目标值)
    if ob_value.strip() in index:
        return index[ob_value.strip()]

    print(f"⚠️  「{ob_value}」(去前缀「{stripped}」)在飞书关联表里找不到,parent_project 此条跳过")
    print(f"    可用项目: {', '.join(sorted(index.keys())[:10])}{'...' if len(index) > 10 else ''}")
    return None


def resolve_parent_task_record_id(parent_task_name: str, vault_root: Path) -> Optional[str]:
    """v0.4.0(2026-05-28):把 OB task md wikilink 名解析为飞书「父任务」link 字段需要的 record_id

    "父任务"字段在飞书侧是 link 类型自关联到本表(项目管理表),需要传 record_id 数组。
    本函数 vault 内查同名 task md → 读其 frontmatter.feishu_record → 返回。

    Args:
        parent_task_name: 已去 [[ ]] 的 task md stem(如 "2026-05-20-test1")
        vault_root: vault 根目录(用于查 04 Inbox/task/<name>.md)

    Returns:
        飞书 record_id(已 sync 的父 task)或 None(找不到 / 未 sync,调用方应跳过)

    匹配优先级:
        1. vault_root / "04 Inbox/task" / f"{name}.md"(直接路径,O(1))
        2. fallback:vault_root / "04 Inbox/task" 内 rglob f"{name}.md"(防御性,处理子目录)
    """
    if not parent_task_name:
        return None

    task_dir = vault_root / "04 Inbox" / "task"
    if not task_dir.exists():
        print(f"⚠️  parent_task 查找失败:vault 内 {task_dir} 不存在")
        return None

    candidates = []
    direct = task_dir / f"{parent_task_name}.md"
    if direct.exists():
        candidates.append(direct)
    else:
        candidates = list(task_dir.rglob(f"{parent_task_name}.md"))

    if not candidates:
        print(f"⚠️  parent_task 找不到 vault 内对应 task md: [[{parent_task_name}]] → 跳过该字段")
        return None

    for p in candidates:
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        fm, _, _ = parse_frontmatter(text)
        if fm:
            rec_id = fm.get("feishu_record")
            if rec_id and isinstance(rec_id, str) and rec_id.strip() and not rec_id.startswith("#"):
                return rec_id.strip()

    print(f"⚠️  parent_task `[[{parent_task_name}]]` 在 vault 找到 task md 但无 feishu_record(未 sync)→ 跳过该字段")
    return None


def query_subprojects_by_parent(
    parent_record_id: str,
    link_table_id: str,
    name_field: str,
    parent_field_name: str,
    config: dict,
) -> list[dict]:
    """查飞书关联表里指定父 record_id 的所有子 records

    用于 userscript 二级菜单:userscript 选完一级 → 调 sync.py --resolve-project →
    sync.py 在此函数查飞书表「父产品」字段 link 到指定一级的所有子 → userscript 弹二级 suggester

    Args:
        parent_record_id: 父 record_id(如「布丁」recvjm91DZgp2I)
        link_table_id: 关联表 table_id
        name_field: 子 record 名字字段(如「产品项目名」)
        parent_field_name: 父字段名(如「父产品」)
        config: 全局 config

    Returns: [{"name": "布丁开发", "record_id": "recv..."}, ...](顺序 = 表里的存储顺序)
    """
    base_token = config["feishu"]["base_token"]
    try:
        result = run_cli([
            "bitable", "record", "list",
            "--base-token", base_token,
            "--table-id", link_table_id,
        ])
    except Exception as e:
        print(f"⚠️  查子 record 失败: {e}", file=sys.stderr)
        return []

    fields = result.get("fields", [])
    rows = result.get("data", [])
    ids = result.get("record_id_list", [])

    if name_field not in fields or parent_field_name not in fields:
        return []

    name_idx = fields.index(name_field)
    parent_idx = fields.index(parent_field_name)

    children = []
    for i, row in enumerate(rows):
        if i >= len(ids):
            break
        parent_val = row[parent_idx] if parent_idx < len(row) else None
        # 父字段格式:list of {"id": "rec..."}(可能为空)
        if not isinstance(parent_val, list) or not parent_val:
            continue
        parent_ids = [p.get("id") for p in parent_val if isinstance(p, dict)]
        if parent_record_id not in parent_ids:
            continue
        name_val = row[name_idx] if name_idx < len(row) else None
        if isinstance(name_val, str) and name_val.strip():
            children.append({"name": name_val.strip(), "record_id": ids[i]})

    return children


def resolve_project_for_userscript(ob_name: str, config: dict) -> dict:
    """给 userscript 用的"一站式"项目解析(查 override + 一级 record_id + 二级清单)

    Args:
        ob_name: OB 端项目文件名(含前缀,如 "00 布丁" / "zhixinggame")
        config: 全局 config

    Returns: JSON-serializable dict
        {
            "ob_name": 原 OB 名字,
            "effective_name": override 后或原名(用于标题前缀),
            "override_hit": True/False,
            "parent_record_id": 一级 record_id 或 None,
            "subprojects": [{"name": "...", "record_id": "..."}, ...]
        }
    """
    cfg = config.get("task_md_fields", {}).get("parent_project", {})
    link_table_id = cfg.get("link_table_id")
    name_field = cfg.get("link_table_name_field", "产品项目名")
    parent_field = cfg.get("link_table_parent_field", "父产品")
    strip_regex = cfg.get("strip_prefix_regex", r"^\d+\s+")
    override_map = cfg.get("override_map") or {}

    result = {
        "ob_name": ob_name,
        "effective_name": ob_name,
        "override_hit": False,
        "parent_record_id": None,
        "subprojects": [],
    }

    if not link_table_id:
        return result

    # 1. override 命中检查(原名 or 去前缀后)
    effective_name = ob_name
    if ob_name in override_map:
        effective_name = override_map[ob_name]
        result["override_hit"] = True
    else:
        stripped_for_override = re.sub(strip_regex, "", ob_name).strip() if strip_regex else ob_name
        if stripped_for_override in override_map:
            effective_name = override_map[stripped_for_override]
            result["override_hit"] = True
    result["effective_name"] = effective_name

    # 2. 解析 effective_name → record_id
    rec_id = resolve_link_record_id(effective_name, link_table_id, name_field, strip_regex, config)
    result["parent_record_id"] = rec_id

    # 3. override 命中时不查二级(已直接定位到具体 record)
    if result["override_hit"]:
        return result

    # 4. 查该一级的子 records
    if rec_id:
        result["subprojects"] = query_subprojects_by_parent(
            rec_id, link_table_id, name_field, parent_field, config
        )

    return result


# ============================================================
# v0.3.5: quickadd-options batch 接口
# ============================================================
# Cmd+P「📝 快记任务」启动一次 Python 进程 ~1s,要拉 大类 / 小类 / 月 / 周 共 4 类信息,
# 各自起一个进程 4 × 1s 太慢 → 一次性 batch 拉完,userscript 单进程获取 JSON

def _extract_link_table_records(
    link_table_id: str,
    name_field: str,
    parent_field: str,
    active_field: Optional[str],
    config: dict,
) -> list[dict]:
    """拉关联表(产品项目表)全部 record,返回 enrich 后的 list

    Returns: [{"name": "布丁", "record_id": "rec...", "active": True, "parent_ids": ["rec..."]}, ...]
        - active: 若 active_field 未配 → 默认 True(不过滤)
        - parent_ids: 父字段 link list 解析的 record_id list,空 list 表示是顶层
    """
    try:
        # limit=200 是飞书 cli 单次上限,产品项目表通常 <100 条够用
        result = run_cli([
            "bitable", "record", "list",
            "--base-token", config["feishu"]["base_token"],
            "--table-id", link_table_id,
            "--limit", "200",
        ])
    except Exception as e:
        print(f"⚠️  关联表 record list 失败: {e}", file=sys.stderr)
        return []

    fields = result.get("fields", [])
    rows = result.get("data", [])
    ids = result.get("record_id_list", [])

    if name_field not in fields:
        return []

    name_idx = fields.index(name_field)
    parent_idx = fields.index(parent_field) if parent_field in fields else -1
    active_idx = fields.index(active_field) if (active_field and active_field in fields) else -1

    records: list[dict] = []
    for i, row in enumerate(rows):
        if i >= len(ids):
            break
        name_val = row[name_idx] if name_idx < len(row) else None
        if not isinstance(name_val, str) or not name_val.strip():
            continue

        # 父字段:link 字段格式 list of {"id":"rec..."},空/None 表示顶层
        parent_ids: list[str] = []
        if parent_idx >= 0 and parent_idx < len(row):
            parent_val = row[parent_idx]
            if isinstance(parent_val, list):
                parent_ids = [p.get("id") for p in parent_val if isinstance(p, dict) and p.get("id")]

        # active 字段:checkbox 格式 bool / "true" / 1 都算 truthy;未配 active_field → 默认 True
        if active_idx >= 0:
            active_val = row[active_idx] if active_idx < len(row) else None
            active = bool(active_val) and str(active_val).lower() not in ("false", "0", "")
        else:
            active = True

        records.append({
            "name": name_val.strip(),
            "record_id": ids[i],
            "active": active,
            "parent_ids": parent_ids,
        })

    return records


# v0.3.5: 前缀匹配,允许飞书侧 option name 带额外尾部说明
# 例:`26W22(5月25日-5月31日)` 匹配为 yy=26 ww=22
# 例:`26 年 5 月(5月起)` 匹配为 yy=26 mm=5
# 不带 `$` 的正则锁定 ISO 周编号 / 年月格式前缀;无关老格式如 `S1(25 年第 46 周)...` 不匹配
_ITER_WEEK_RE = re.compile(r"^(\d{2})W(\d{1,2})")
_ITER_MONTH_RE = re.compile(r"^(\d{2})\s*年\s*(\d{1,2})\s*月")


def _iter_week_sort_key(s: str) -> int:
    """26W22 → 26*53+22 = 1400(用于 DESC 排序;不匹配格式返回 -1)"""
    m = _ITER_WEEK_RE.match(s.strip())
    if not m:
        return -1
    yy, ww = int(m.group(1)), int(m.group(2))
    return yy * 53 + ww


def _iter_month_sort_key(s: str) -> int:
    """26 年 5 月 → 26*12+5 = 317(用于 DESC 排序;不匹配格式返回 -1)"""
    m = _ITER_MONTH_RE.match(s.strip())
    if not m:
        return -1
    yy, mm = int(m.group(1)), int(m.group(2))
    return yy * 12 + mm


def get_recent_iteration_options(
    table_id: str,
    field_name: str,
    sort_key_fn,
    top_n: int,
    config: dict,
    view_id: Optional[str] = None,
) -> list[str]:
    """拉主表 record,扫指定 enum/多选字段,distinct + sort_key_fn DESC + top N

    v0.3.8: 函数虽叫 iteration,实际是通用 "scan field distinct values + sort + top N"
    - sort_key_fn=None → 不排序,按 distinct 顺序(set 遍历)取前 N(适合无自然排序的 enum,如 project_minor)
    - sort_key_fn=fn → 按 fn DESC 取前 N(适合 iteration_week / iteration_month)

    Args:
        view_id: 用 view 过滤(cli `--view-id`),通常用 default_view_id 拿"日常活跃"那批 record
                 留空 None → 拉全表(按创建时间 ASC),可能拉到老 record 漏新 enum 值

    返回 [str, ...](飞书侧字符串值,直接可写 frontmatter)
    """
    cli_args = [
        "bitable", "record", "list",
        "--base-token", config["feishu"]["base_token"],
        "--table-id", table_id,
        "--limit", "200",
    ]
    if view_id:
        cli_args += ["--view-id", view_id]
    try:
        result = run_cli(cli_args)
    except Exception as e:
        print(f"⚠️  主表 record list 失败({field_name}): {e}", file=sys.stderr)
        return []

    fields = result.get("fields", [])
    rows = result.get("data", [])

    if field_name not in fields:
        return []
    idx = fields.index(field_name)

    seen: set[str] = set()
    for row in rows:
        if idx >= len(row):
            continue
        val = row[idx]
        # 单选 enum:cli 返回 str;多选 enum:cli 返回 list[str];都正交处理
        if isinstance(val, str) and val.strip():
            seen.add(val.strip())
        elif isinstance(val, list):
            for v in val:
                if isinstance(v, str) and v.strip():
                    seen.add(v.strip())

    # v0.3.8: sort_key_fn=None → 不排序不过滤,按 set 遍历顺序取 top N
    if sort_key_fn is None:
        return list(seen)[:top_n]
    valid = [s for s in seen if sort_key_fn(s) >= 0]
    valid.sort(key=sort_key_fn, reverse=True)
    return valid[:top_n]


def cmd_quickadd_options(config: dict) -> dict:
    """v0.3.5: Cmd+P 快记任务启动时一次性拉 大类 / 小类 / 月 / 周 所有选项

    Returns JSON-serializable dict:
        {
          "active_top_level": [{"name":"布丁","record_id":"rec..."}, ...],
          "subprojects_by_parent": {"rec...": [{"name":"布丁开发","record_id":"rec..."}], ...},
          "recent_months": ["26 年 6 月","26 年 5 月",...],
          "recent_weeks":  ["26W23","26W22",...]
        }

    任一子查询失败 → 对应字段返回空 list/dict(不阻断 userscript,鲁棒降级)
    """
    pp_cfg = config.get("task_md_fields", {}).get("parent_project", {})
    link_table_id = pp_cfg.get("link_table_id")
    name_field = pp_cfg.get("link_table_name_field", "产品项目名")
    parent_field = pp_cfg.get("link_table_parent_field", "父产品")
    active_field = pp_cfg.get("link_table_active_field")  # v0.3.5 新加,留空则不过滤

    result: dict = {
        "active_top_level": [],
        "subprojects_by_parent": {},
        "recent_months": [],
        "recent_weeks": [],
        "recent_project_minor": [],   # v0.3.8 加,任务内容细分类型最近 5 条 distinct
    }

    # ---- 大类 / 小类(产品项目表)----
    if link_table_id:
        records = _extract_link_table_records(
            link_table_id, name_field, parent_field, active_field, config
        )
        # v0.3.9 修:"大类"扁平化展示所有 active=true(不再按"父=空"过滤)
        # 原因:飞书产品项目表里很多活跃叶子项目(如「内容工厂」「AiCoding训练营」)
        # 挂在 inactive 父下面 — 用户视角它们就是"可选项目",不应该被过滤掉
        # 用户选完后,userscript Step 4 用 subprojects_by_parent[record_id] 查有无子级
        # 有就弹二级菜单,无(叶子)就直接跳过
        result["active_top_level"] = [
            {"name": r["name"], "record_id": r["record_id"]}
            for r in records
            if r["active"]
        ]
        # 小类:活跃,按 parent_id groupby
        sub_by_parent: dict[str, list[dict]] = {}
        for r in records:
            if not r["active"]:
                continue
            for pid in r["parent_ids"]:
                sub_by_parent.setdefault(pid, []).append(
                    {"name": r["name"], "record_id": r["record_id"]}
                )
        result["subprojects_by_parent"] = sub_by_parent

    # ---- 最近 5 个执行月 / 周(主表 record 扫,distinct+sort+top 5)----
    # 用 default_view_id 拉 — 飞书侧的"主视图"通常只含活跃 record,容易拿到最新 iteration 值
    # 不传 view_id 会拉全表按创建时间 ASC,前 200 条多是老 record 漏新格式
    fields_cfg = config.get("fields", {})
    main_table_id = config["feishu"]["table_id"]
    default_view_id = config["feishu"].get("default_view_id")
    iter_month_cfg = fields_cfg.get("iteration_month", {})
    iter_week_cfg = fields_cfg.get("iteration_week", {})

    if iter_month_cfg.get("field_name"):
        result["recent_months"] = get_recent_iteration_options(
            main_table_id, iter_month_cfg["field_name"], _iter_month_sort_key, 5, config,
            view_id=default_view_id,
        )
    if iter_week_cfg.get("field_name"):
        result["recent_weeks"] = get_recent_iteration_options(
            main_table_id, iter_week_cfg["field_name"], _iter_week_sort_key, 5, config,
            view_id=default_view_id,
        )

    # v0.3.8: project_minor(项目小类)— 无自然排序,sort_key_fn=None 按 set 顺序取前 5
    task_md_cfg = config.get("task_md_fields", {})
    project_minor_cfg = task_md_cfg.get("project_minor", {})
    if project_minor_cfg.get("field_name"):
        result["recent_project_minor"] = get_recent_iteration_options(
            main_table_id, project_minor_cfg["field_name"], None, 5, config,
            view_id=default_view_id,
        )

    return result


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


def feishu_upsert_record(record_id: Optional[str], fields: dict, config: dict, dry_run: bool = True,
                         table_id: Optional[str] = None) -> dict:
    """创建/更新 record。
    - record_id=None → 创建
    - record_id="rec..." → 更新
    - table_id(v0.6.0):可选,指定子表 table_id;None 时走 config["feishu"]["table_id"] 主表
    返回 {action, record_id, payload}(dry_run 时不调 cli)
    """
    action = "update" if record_id else "create"
    payload = {"fields": fields}

    if dry_run:
        return {"action": action, "record_id": record_id, "payload": payload, "_dry_run": True}

    base_token = config["feishu"]["base_token"]
    table_id = table_id or config["feishu"]["table_id"]
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
    # v0.3.5(2026-05-27):task md 模式优先用 frontmatter.status 直接 7 态映射,
    # 避免 inline 4 字符表达不出 subdone/idea;journal 模式无 fm_status,fallback 老 inline char 映射
    status_cfg = fields_cfg.get("status", {})
    if status_cfg:
        fm_status = task.get("fm_status")
        mapped = None
        if fm_status and "task_md_map" in status_cfg:
            mapped = status_cfg["task_md_map"].get(fm_status)
        if not mapped:
            mapped = status_cfg["map"].get(f"[{task['status_char']}]")
        if mapped:
            out[status_cfg["field_name"]] = [mapped]

    # 完成时间(飞书 datetime 字段需要毫秒时间戳)
    done_cfg = fields_cfg.get("done_date", {})
    if done_cfg and task["done_date"]:
        out[done_cfg["field_name"]] = date_to_ms(task["done_date"])

    # 🆕 执行迭代周(多选 enum,飞书侧字段类型 MultiSelect)
    # 2026-05-18 加(基于 done_date 反推 ISO 周);
    # v0.3.5 升级:优先用 frontmatter `iteration_week` list(Cmd+P 创建时主动选);
    #   frontmatter 空 + 有 done_date → fallback 走老 derive 算法(完成 task 补录历史)
    iter_week_cfg = fields_cfg.get("iteration_week", {})
    if iter_week_cfg and iter_week_cfg.get("field_name"):
        fm_weeks = task.get("iteration_week") or []
        if fm_weeks:
            # frontmatter 显式值 → 直接写(多选 list)
            out[iter_week_cfg["field_name"]] = fm_weeks
        elif task["done_date"]:
            # fallback:用 done_date derive,走 cli best-match enum 选项
            candidate = derive_iteration_week_candidate(
                task["done_date"], iter_week_cfg["derive_template"]
            )
            matched = best_match_enum(iter_week_cfg["field_id"], candidate, config)
            if matched:
                out[iter_week_cfg["field_name"]] = [matched]

    # 🆕 执行迭代月(同理多选 enum)
    iter_month_cfg = fields_cfg.get("iteration_month", {})
    if iter_month_cfg and iter_month_cfg.get("field_name"):
        fm_months = task.get("iteration_month") or []
        if fm_months:
            out[iter_month_cfg["field_name"]] = fm_months
        elif task["done_date"]:
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
            # 飞书侧所有 select 字段(单/多选)都要 list 包裹(v0.3.9 实证:cli list 返回 ['P0'] 这种格式)
            # 历史 record 验证:价值优先级 ['P0'] / 执行状态 ['Todo'] / 项目小类 ['claudecode'] 全是 list
            # OB frontmatter 写单 str 也兼容(自动包 list),写 list 也兼容(直接用)
            # v0.3.8: subcategory / project_minor;v0.3.9 补:priority_str / category / adhd_priority / efficiency
            # v0.4.0(2026-05-28):quality(高/中/低 单选)
            if ob_key in ("subcategory", "project_minor", "adhd_priority",
                          "priority_str", "category", "efficiency", "quality"):
                out[field_name] = value if isinstance(value, list) else [value]
            # number 字段
            # v0.4.0(2026-05-28):actual_hours(用时,跟 estimate_hours 同 float)
            elif ob_key in ("estimate_hours", "actual_hours"):
                try:
                    out[field_name] = float(value)
                except (ValueError, TypeError):
                    pass
            # checkbox(bool)字段 — today_flag → 飞书「是否今日」
            elif ob_key == "today_flag":
                out[field_name] = bool(value)
            # v0.4.0(2026-05-28):parent_task 自关联 link 字段
            # frontmatter `parent_task: "[[<父 task 文件名>]]"` → vault 查 stem → 取 feishu_record
            # 找不到 / 父 task 未 sync → resolve_parent_task_record_id 已打 warning,这里跳过(不阻断其他字段)
            elif ob_key == "parent_task":
                rec_id = resolve_parent_task_record_id(str(value), vault_root)
                if rec_id:
                    out[field_name] = [rec_id]
            # parent_project:可能是 link 类型(配 link_table_id)或 select 类型(只配 field_name)
            # link 类型需要查关联表拿 record_id,select 类型按字符串处理
            elif ob_key == "parent_project":
                link_table_id = fcfg.get("link_table_id")
                if link_table_id:
                    name_field = fcfg.get("link_table_name_field", "产品项目名")
                    strip_regex = fcfg.get("strip_prefix_regex", r"^\d+\s+")
                    override_map = fcfg.get("override_map") or {}
                    rec_id = resolve_link_record_id(
                        str(value), link_table_id, name_field, strip_regex, config,
                        override_map=override_map,
                    )
                    if rec_id:
                        out[field_name] = [rec_id]
                    # 找不到时 resolve_link_record_id 已打 warning,这里不写 → 跳过该字段
                else:
                    # 老 select 模式(向后兼容):按字符串写
                    out[field_name] = str(value)
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


def ms_to_date_str(val) -> Optional[str]:
    """飞书 datetime 字段值 → YYYY-MM-DD(UTC+8)。失败返回 None。

    支持两种输入(cli 实测):
    - 整数 / 数字字符串:毫秒时间戳(写入用)
    - "YYYY-MM-DD HH:MM:SS" 字符串(cli list 返回格式)
    """
    if val is None or val == "":
        return None
    # 字符串先试 "YYYY-MM-DD HH:MM:SS" / "YYYY-MM-DD" 直读
    if isinstance(val, str):
        m = re.match(r'^(\d{4}-\d{2}-\d{2})', val)
        if m:
            return m.group(1)
    # fallback:毫秒时间戳
    try:
        ms_int = int(val)
    except (ValueError, TypeError):
        return None
    dt = datetime.fromtimestamp(ms_int / 1000, tz=timezone(timedelta(hours=8)))
    return dt.strftime("%Y-%m-%d")


# ============================================================
# v0.6.0(2026-05-29):执行明细子表(daily execution log)推送
# ============================================================

def _extract_link_record_ids(link_val) -> list[str]:
    """cli list 返回的 link 字段值 → record_id list。
    可能的格式:[{'id': 'recXXX'}, ...] / ['recXXX', ...] / 'recXXX' / None
    """
    if not link_val:
        return []
    if isinstance(link_val, str):
        return [link_val]
    if isinstance(link_val, list):
        out = []
        for item in link_val:
            if isinstance(item, dict) and "id" in item:
                out.append(item["id"])
            elif isinstance(item, str):
                out.append(item)
        return out
    return []


def _detail_values_equal(new_val, old_val) -> bool:
    """判断两个 fields 值是否"实质相等",用于 diff 检测。
    覆盖 None / list / number 精度 / link 字段 (record_id 集合相等)。
    """
    if new_val is None and old_val is None:
        return True
    if new_val is None or old_val is None:
        return False
    # link 字段:list of dict({id}) or list of str
    if isinstance(new_val, list) and isinstance(old_val, list):
        new_rids = _extract_link_record_ids(new_val)
        old_rids = _extract_link_record_ids(old_val)
        if new_rids or old_rids:
            return sorted(new_rids) == sorted(old_rids)
        return new_val == old_val
    # 数字精度容忍
    if isinstance(new_val, (int, float)) and isinstance(old_val, (int, float)):
        return abs(new_val - old_val) < 0.001
    return str(new_val).strip() == str(old_val).strip()


def _fetch_detail_records_for_task(task_record_id: str, config: dict) -> list[tuple[str, dict]]:
    """拉子表里关联到指定 task 的 record。

    Returns: [(detail_record_id, fields_dict), ...]
            fields_dict 形如 {field_name: value, ...}
    实现:cli list 全表 → client-side filter link_back 字段含 task_record_id。
    性能:子表 record 量级几百到几千,200/页 list 几页搞定。
    """
    detail_cfg = config.get("execution_detail")
    if not detail_cfg or not detail_cfg.get("table_id"):
        return []
    link_field = detail_cfg["fields"]["link_back"]["field_name"]

    all_records, all_ids = [], []
    fields_meta = None
    offset = 0
    while True:
        result = run_cli([
            "bitable", "record", "list",
            "--base-token", config["feishu"]["base_token"],
            "--table-id", detail_cfg["table_id"],
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

    if not fields_meta or link_field not in fields_meta:
        return []
    link_idx = fields_meta.index(link_field)

    matched = []
    for rid, row in zip(all_ids, all_records):
        link_val = row[link_idx] if link_idx < len(row) else None
        if task_record_id in _extract_link_record_ids(link_val):
            fields_dict = {fields_meta[i]: (row[i] if i < len(row) else None)
                           for i in range(len(fields_meta))}
            matched.append((rid, fields_dict))
    return matched


def _build_detail_fields_payload(detail: dict, task_record_id: str, config: dict) -> dict:
    """OB 端单条明细 dict → 飞书子表 record fields payload。

    detail 形如 {date, status, plan?, review?, estimate_hours?, actual_hours?, completion?}
    空字段不写(跟主字段映射"空字段不清空"策略一致)。
    """
    detail_cfg = config["execution_detail"]
    fmap = detail_cfg["fields"]
    out = {}

    # 日期(必填,毫秒时间戳)
    date_field = fmap["date"]["field_name"]
    out[date_field] = date_to_ms(detail["date"])

    # 执行状态(select,OB 小写 → 飞书首字母大写,list 包裹以对齐 cli list 返回格式)
    status_cfg = fmap.get("status", {})
    status_field = status_cfg.get("field_name")
    if status_field and detail.get("status"):
        feishu_status = status_cfg.get("map", {}).get(detail["status"])
        if feishu_status:
            out[status_field] = [feishu_status]

    # 文本字段
    for ob_key in ("plan", "review"):
        fcfg = fmap.get(ob_key, {})
        fname = fcfg.get("field_name")
        if fname and detail.get(ob_key):
            out[fname] = detail[ob_key]

    # 数字字段
    for ob_key in ("estimate_hours", "actual_hours"):
        fcfg = fmap.get(ob_key, {})
        fname = fcfg.get("field_name")
        val = detail.get(ob_key)
        if fname and val is not None:
            try:
                out[fname] = float(val)
            except (ValueError, TypeError):
                pass

    # 完成度(select,list 包裹对齐 cli list 返回格式)
    comp_cfg = fmap.get("completion", {})
    comp_field = comp_cfg.get("field_name")
    if comp_field and detail.get("completion"):
        out[comp_field] = [detail["completion"]]

    # link_back(关联回主 task)
    link_field = fmap["link_back"]["field_name"]
    out[link_field] = [task_record_id]

    return out


def push_execution_details(task_record_id: str, ob_details: list[dict],
                           config: dict, apply: bool = False) -> dict:
    """推 OB 明细段到飞书子表(v0.6.0)。

    diff 策略:
      - OB 有 飞书无(按日期 key)→ CREATE
      - OB 有 飞书有同日 → 字段 diff → UPDATE(只更新有差异的字段)
      - OB 无 飞书有 → 暂不删(空字段保护,跟主字段映射策略一致)
      - 同日 OB 多行 → parse_execution_details 已去重为最后一行

    禁用条件:
      - config 无 execution_detail 段 / table_id 空 → 整段跳过(返回 _disabled)
      - task 还没 record_id(CREATE 主表中)→ 跳过(主 record_id 拿到后下次 push 再推明细)
      - OB 无明细行 → 跳过(不强制每个 task 都有明细)

    Returns: {creates: [...], updates: [...], skipped: [...], errors: [...]}
    """
    detail_cfg = config.get("execution_detail")
    if not detail_cfg or not detail_cfg.get("table_id"):
        return {"_disabled": True, "creates": [], "updates": [], "skipped": [], "errors": []}
    if not task_record_id or not ob_details:
        return {"creates": [], "updates": [], "skipped": [], "errors": []}

    date_field = detail_cfg["fields"]["date"]["field_name"]

    # 拉飞书已有 → 按日期 index
    existing_by_date: dict[str, tuple[str, dict]] = {}
    try:
        for det_rid, fdict in _fetch_detail_records_for_task(task_record_id, config):
            date_iso = ms_to_date_str(fdict.get(date_field))
            if date_iso:
                existing_by_date[date_iso] = (det_rid, fdict)
    except Exception as e:
        return {"creates": [], "updates": [], "skipped": [], "errors": [f"拉飞书子表失败: {e}"]}

    plan = {"creates": [], "updates": [], "skipped": [], "errors": []}

    for ob_detail in ob_details:
        date_iso = ob_detail["date"]
        new_fields = _build_detail_fields_payload(ob_detail, task_record_id, config)
        if date_iso not in existing_by_date:
            plan["creates"].append({"date": date_iso, "fields": new_fields})
            continue
        existing_rid, existing_fields = existing_by_date[date_iso]
        # diff:跳过 date / link_back 两个"识别字段"
        # - date 已用作 dict key 匹配,飞书 cli list 返回 "YYYY-MM-DD HH:MM:SS" 跟 OB 端毫秒整数对不上
        # - link_back 已是 task_record_id 反查的结果,飞书侧 [{id}] 格式跟 [rid] list 对不上
        # 这两个字段格式差异不算业务 diff,跳过避免误判
        date_field = detail_cfg["fields"]["date"]["field_name"]
        link_field = detail_cfg["fields"]["link_back"]["field_name"]
        diff = {}
        for fname, new_val in new_fields.items():
            if fname in (date_field, link_field):
                continue
            if not _detail_values_equal(new_val, existing_fields.get(fname)):
                diff[fname] = new_val
        if diff:
            plan["updates"].append({"date": date_iso, "record_id": existing_rid, "fields": diff})
        else:
            plan["skipped"].append({"date": date_iso, "record_id": existing_rid})

    if not apply:
        return plan

    # 真推
    table_id = detail_cfg["table_id"]
    for c in plan["creates"]:
        try:
            result = feishu_upsert_record(
                record_id=None, fields=c["fields"], config=config,
                dry_run=False, table_id=table_id,
            )
            c["record_id"] = result.get("record_id")
        except Exception as e:
            plan["errors"].append({"date": c["date"], "op": "CREATE", "error": str(e)})
    for u in plan["updates"]:
        try:
            feishu_upsert_record(
                record_id=u["record_id"], fields=u["fields"], config=config,
                dry_run=False, table_id=table_id,
            )
        except Exception as e:
            plan["errors"].append({"date": u["date"], "op": "UPDATE", "error": str(e)})

    return plan


def _feishu_detail_row_to_ob_dict(fdict: dict, config: dict) -> Optional[dict]:
    """飞书子表一条 record(fields dict)→ OB 端 detail dict。
    用于 pull-today 反向 sync(飞书 → OB)。
    """
    detail_cfg = config["execution_detail"]
    fmap = detail_cfg["fields"]

    date_field = fmap["date"]["field_name"]
    date_iso = ms_to_date_str(fdict.get(date_field))
    if not date_iso:
        return None

    item = {"date": date_iso, "status": "todo"}

    # 执行状态:飞书 → OB 小写(反向 map)
    status_cfg = fmap.get("status", {})
    sfield = status_cfg.get("field_name")
    if sfield:
        raw = fdict.get(sfield)
        if isinstance(raw, list) and raw:
            raw = raw[0]
        if raw:
            inverse_map = {v: k for k, v in status_cfg.get("map", {}).items()}
            item["status"] = inverse_map.get(str(raw), "todo")

    # 文本字段
    for ob_key in ("plan", "review"):
        fname = fmap.get(ob_key, {}).get("field_name")
        if fname:
            val = fdict.get(fname)
            if val:
                item[ob_key] = str(val).strip()

    # 数字字段
    for ob_key in ("estimate_hours", "actual_hours"):
        fname = fmap.get(ob_key, {}).get("field_name")
        if fname:
            val = fdict.get(fname)
            if val is not None and val != "":
                try:
                    item[ob_key] = float(val)
                except (ValueError, TypeError):
                    pass

    # 完成度(select)
    cfield = fmap.get("completion", {}).get("field_name")
    if cfield:
        raw = fdict.get(cfield)
        if isinstance(raw, list) and raw:
            raw = raw[0]
        if raw:
            item["completion"] = str(raw).strip()

    return item


def _render_detail_line(detail: dict) -> str:
    """OB detail dict → markdown 行 `- YYYY-MM-DD | 状态 | 计划=val / 估时=val / ...`。
    key 顺序对齐飞书子表 schema(计划 → 估时 → 用时 → 完成度 → 复盘),空字段不显示。
    数字字段整数化(2.0 → 2)。

    v0.6.7(2026-05-30):
    - review 从第 2 位挪到末尾 — 飞书子表实际顺序是
        执行状态 → 计划&策略 → 估时 → 用时 → 完成度 → 执行&复盘
        语义对齐"事前 → 事中事后 → 文字复盘"
    - key 中文化(用户反馈"中文更容易识别")—— 渲染输出中文 key,
        解析端依然兼容英文 key(plan/est/act/done/review)+ 中文 key 双向写法
        老 task md 含英文 key 的明细段下次 push 自动 normalize 为中文
    """
    KEY_ORDER = [
        ("plan", "计划"),
        ("estimate_hours", "估时"),
        ("actual_hours", "用时"),
        ("completion", "完成度"),
        ("review", "复盘"),
    ]
    parts = []
    for internal, short in KEY_ORDER:
        val = detail.get(internal)
        if val is None or val == "":
            continue
        if internal in ("estimate_hours", "actual_hours"):
            val_str = str(int(val)) if isinstance(val, (int, float)) and val == int(val) else str(val)
        else:
            val_str = str(val).strip()
        parts.append(f"{short}={val_str}")
    kv_str = " / ".join(parts)
    # v0.6.7:状态纯文本(首字母大写),去 emoji 易编辑
    status_internal = detail.get("status", "todo")
    status_display = _STATUS_DISPLAY.get(status_internal, status_internal)
    base = f"- {detail['date']} | {status_display}"
    return f"{base} | {kv_str}" if kv_str else base


def _fetch_all_detail_records_grouped(config: dict) -> dict:
    """拉飞书子表全表,按 link_back(任务 record_id)分组。

    用于批量场景(pull_today_from_feishu)避免每个 task 单独 list 子表。
    单 task 单条 push 仍走 _fetch_detail_records_for_task 不需要 prefetch。

    Returns: {task_rid: [(det_rid, fields_dict), ...]}
    """
    detail_cfg = config.get("execution_detail")
    if not detail_cfg or not detail_cfg.get("table_id"):
        return {}
    link_field = detail_cfg["fields"]["link_back"]["field_name"]

    all_records, all_ids = [], []
    fields_meta = None
    offset = 0
    while True:
        result = run_cli([
            "bitable", "record", "list",
            "--base-token", config["feishu"]["base_token"],
            "--table-id", detail_cfg["table_id"],
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

    if not fields_meta or link_field not in fields_meta:
        return {}
    link_idx = fields_meta.index(link_field)

    grouped: dict = {}
    for rid, row in zip(all_ids, all_records):
        link_val = row[link_idx] if link_idx < len(row) else None
        fields_dict = {fields_meta[i]: (row[i] if i < len(row) else None)
                       for i in range(len(fields_meta))}
        for trid in _extract_link_record_ids(link_val):
            grouped.setdefault(trid, []).append((rid, fields_dict))
    return grouped


def pull_execution_details_for_task(task_record_id: str, md_path: Path,
                                     config: dict, apply: bool = False,
                                     prefetched_records: Optional[list] = None) -> dict:
    """拉飞书子表 → 写 OB 端「## 📈 执行明细」段(merge 模式)。

    merge 策略(飞书 → OB):
      - 飞书有同日 → 覆盖 OB 同日(pull 方向)
      - 飞书有新日期 → 加进 OB 段
      - OB 有 飞书没有 → 保留 OB(可能是 OB 端最新加但还没 push)

    禁用条件:
      - config.execution_detail.table_id 空 → _disabled
      - task_record_id 为空 → skipped

    prefetched_records:可选,批量场景从 _fetch_all_detail_records_grouped 拿,避免反复 cli list。
                       格式跟 _fetch_detail_records_for_task 返回一致。

    Returns: {changed, added, updated, kept_ob_only, dry_run?, _disabled?, error?}
    """
    detail_cfg = config.get("execution_detail")
    if not detail_cfg or not detail_cfg.get("table_id"):
        return {"_disabled": True, "changed": False}
    if not task_record_id:
        return {"changed": False, "reason": "no_record_id"}

    # 1. 拉飞书子表 records(关联到此 task)
    if prefetched_records is not None:
        feishu_records = prefetched_records
    else:
        try:
            feishu_records = _fetch_detail_records_for_task(task_record_id, config)
        except Exception as e:
            return {"changed": False, "error": f"拉飞书子表失败: {e}"}

    # 2. 飞书 record → OB dict by date
    feishu_by_date: dict[str, dict] = {}
    for _, fdict in feishu_records:
        ob_d = _feishu_detail_row_to_ob_dict(fdict, config)
        if ob_d:
            feishu_by_date[ob_d["date"]] = ob_d

    # 3. 读 OB 当前段
    try:
        body = md_path.read_text(encoding="utf-8")
    except Exception as e:
        return {"changed": False, "error": f"读 task md 失败: {e}"}
    ob_by_date = {d["date"]: d for d in parse_execution_details(body)}

    # 4. merge:飞书优先,OB 独有保留
    merged = dict(ob_by_date)
    added = updated = 0
    for date, fd in feishu_by_date.items():
        if date not in merged:
            added += 1
            merged[date] = fd
        elif merged[date] != fd:
            updated += 1
            merged[date] = fd
    kept_ob_only = sum(1 for d in ob_by_date if d not in feishu_by_date)

    if not merged:
        return {"changed": False, "added": 0, "updated": 0, "kept_ob_only": 0}

    # 5. 渲染新段
    new_section = "\n" + "\n".join(_render_detail_line(merged[d]) for d in sorted(merged)) + "\n"

    # v0.6.1:对比 task md 原文段(未经 parse-render)vs 新渲染,捕捉显示层升级
    # 仅 dict 相等不够 — OB 原文可能写小写 "doing",飞书拉回 parse 后也是 "doing"
    # dict 相等,但渲染出 "🔄 Doing" 跟原文 "doing" 不同 → 需要 rewrite
    m_old = re.search(r'^## +📈 +执行明细\s*\n(.*?)(?=\n## +|\Z)', body, re.MULTILINE | re.DOTALL)
    old_data_lines = []
    if m_old:
        for line in m_old.group(1).splitlines():
            s = line.strip()
            if s and not s.startswith("<!--") and s.startswith("-"):
                old_data_lines.append(s)
    new_data_lines = [_render_detail_line(merged[d]) for d in sorted(merged)]
    if added == 0 and updated == 0 and old_data_lines == new_data_lines:
        return {"changed": False, "added": 0, "updated": 0, "kept_ob_only": kept_ob_only}

    if not apply:
        return {"changed": True, "added": added, "updated": updated,
                "kept_ob_only": kept_ob_only, "dry_run": True}

    # 6. 写文件
    if update_h2_section_in_task_md(md_path, "## 📈 执行明细", new_section):
        return {"changed": True, "added": added, "updated": updated, "kept_ob_only": kept_ob_only}
    return {"changed": False, "reason": "write_failed"}


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


def push_task_md(md_path: Path, apply: bool = False, _silent_fail: bool = False) -> Optional[dict]:
    """单 task md 推送到飞书(CREATE/UPDATE) — 2026-05-25 上线

    用法:python3 sync.py --task-md path/to/task.md [--apply]

    流程:
    1. (v0.4.0+ 2026-05-28)路径不存在 → vault 内 rglob 同名 fallback
       解决:Cmd+P 创建 task md 后,Obsidian Auto Note Mover 等插件可能根据
       关键词自动移动文件,userscript 传的原路径会找不到
    2. parse_task_md 抽 frontmatter + 正文 H2 段
    3. build_fields_payload 转飞书 payload(走 _task_md_mode 分支)
    4. feishu_upsert_record CREATE/UPDATE
    5. 成功后回写 feishu_record + feishu_url 到 task md frontmatter

    铁律 #1 例外(rules/feishu-project-sync.md):
    - 仅"单条 CREATE 新 task"自动跑(空白记录新建,无覆盖风险)
    - UPDATE 仍需 dry-run + 用户审核(由调用方决定是否 --apply)

    v0.4.0+ Step 3(2026-05-28):加 _silent_fail 参数支持批量调用
    - False(默认,CLI 模式):失败 sys.exit(1) — 兼容原行为
    - True(批量调用):返回 dict {success, action, record_id, error, path},
      不 sys.exit,让批量循环继续处理下一条

    Returns: dict 当 _silent_fail=True,None 当 _silent_fail=False(走 sys.exit)
    """
    def _fail(msg: str, action: str = "?") -> Optional[dict]:
        """统一失败出口"""
        if _silent_fail:
            return {"success": False, "action": action, "error": msg, "path": str(md_path)}
        print(f"\n❌ {msg}", file=sys.stderr)
        sys.exit(1)

    config = load_config()

    print(f"\n{'=' * 60}")
    print(f"📝 task md 模式: {md_path}")
    if not apply:
        print(f"📌 dry-run(--apply 才真写)")
    print(f"{'=' * 60}\n")

    # v0.4.0+(2026-05-28):路径不存在 fallback — vault 内 rglob 同名文件
    # 触发场景:Obsidian Auto Note Mover 等插件在 userscript 创建文件后自动移走,
    # 导致 userscript 传给 sync.py 的原路径已失效。本 fallback 让 sync.py 自动找到新位置
    if not md_path.exists():
        print(f"⚠️  路径不存在: {md_path}")
        print(f"    可能 Obsidian Auto Note Mover 等插件移动了文件,vault 内 rglob 同名查找...")
        vault_root = None
        try:
            vault_root = find_vault_root()
        except Exception:
            pass
        if vault_root:
            # 排除 .obsidian / .trash / .git 等隐藏 / 系统目录(避免误命中备份)
            candidates = [
                p for p in vault_root.rglob(md_path.name)
                if not any(part.startswith(".") for part in p.parts)
            ]
            # 优先:04 Inbox/task 内的(用户主流位置)
            inbox_matches = [c for c in candidates if "04 Inbox" in c.parts and "task" in c.parts]
            if inbox_matches:
                md_path = inbox_matches[0]
            elif candidates:
                md_path = candidates[0]
            else:
                return _fail(f"vault 内未找到 {md_path.name}")
            print(f"    ✅ 找到实际位置: {md_path.relative_to(vault_root)}")
        else:
            return _fail("无 vault root,无法 fallback")

    task = parse_task_md(md_path, config)
    if task is None:
        return _fail(f"parse_task_md 失败: {md_path}")

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
    # v0.4.0(2026-05-28): 5 字段补全 — task md「完成质量 / 用时 / 父任务 / 交付 / 用户故事」
    if task.get("actual_hours"):
        print(f"    用时: {task['actual_hours']}h")
    if task.get("quality"):
        print(f"    完成质量: {task['quality']}")
    if task.get("parent_task"):
        print(f"    父任务: [[{task['parent_task']}]]")
    if task.get("delivery"):
        prev = task["delivery"].replace("\n", " ")[:60]
        print(f"    📦 交付: {prev}{'...' if len(task['delivery']) > 60 else ''}")
    if task.get("user_story"):
        prev = task["user_story"].replace("\n", " ")[:60]
        print(f"    👥 用户故事: {prev}{'...' if len(task['user_story']) > 60 else ''}")

    fields = build_fields_payload(task, config, VAULT_ROOT, existing_delivery="")
    print(f"\n    Payload: {json.dumps(fields, ensure_ascii=False, indent=6)[:800]}")

    # v0.6.0(2026-05-29):执行明细预览(dry-run + apply 都打)
    ob_details = task.get("execution_details", [])
    if ob_details:
        print(f"\n    📈 执行明细({len(ob_details)} 条):")
        for d in ob_details:
            preview = []
            for k in ("plan", "review", "estimate_hours", "actual_hours", "completion"):
                if d.get(k) is not None:
                    short = str(d[k])[:30] + ("..." if len(str(d[k])) > 30 else "")
                    preview.append(f"{k}={short}")
            print(f"      - {d['date']} | {d['status']} | {' / '.join(preview) or '(无 key)'}")

    if not apply:
        # v0.6.0:dry-run 也跑明细 plan(纯本地 diff,不调 cli 写;但要拉一次飞书子表)
        if ob_details and task.get("record_id"):
            print(f"\n    📈 执行明细 dry-run plan(拉飞书子表对比):")
            try:
                plan = push_execution_details(task["record_id"], ob_details, config, apply=False)
                if plan.get("_disabled"):
                    print(f"      ⏭  config.execution_detail.table_id 未配置,跳过")
                else:
                    print(f"      ➕ CREATE: {len(plan['creates'])} 条 / 🔄 UPDATE: {len(plan['updates'])} 条 / ⏭  SKIP: {len(plan['skipped'])} 条")
                    for c in plan["creates"]:
                        print(f"        ➕ {c['date']}: {list(c['fields'].keys())}")
                    for u in plan["updates"]:
                        print(f"        🔄 {u['date']} ({u['record_id']}): diff fields = {list(u['fields'].keys())}")
            except Exception as e:
                print(f"      ⚠️  明细 plan 失败: {e}")
        elif ob_details and not task.get("record_id"):
            print(f"      ⏭  主 task 还没 CREATE(无 record_id),明细要等主 CREATE 后下次 push 才推")
        print(f"\n📌 dry-run 完成。--apply 真写飞书 + 回写 feishu_record/url 到 task md")
        return {"success": True, "action": action, "record_id": task.get("record_id"), "path": str(md_path), "dry_run": True} if _silent_fail else None

    print(f"\n🚀 开始 {action}...")
    try:
        result = feishu_upsert_record(
            record_id=task.get("record_id"),
            fields=fields,
            config=config,
            dry_run=False,
        )
    except Exception as e:
        return _fail(f"{action} 失败: {e}", action=action)

    record_id = result.get("record_id")
    if not record_id:
        return _fail(f"{action} 成功但未返回 record_id: {result}", action=action)

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

    # v0.2.4 加:CREATE 时回写「## ✅ 完成标记」段裸 checkbox 行 → 带 URL 的 markdown link
    # 给 dataview TASK 渲染时呈现可点击链接(直达飞书 record)
    # UPDATE 时不动(行可能已经有 link 或被用户手改过)
    if is_create:
        if inject_completion_link(md_path, task["title"], record_url):
            print(f"🔗 已把「## ✅ 完成标记」段 checkbox 行改为带链接的 markdown link")

    # v0.6.0(2026-05-29):主 task push 完后推执行明细子表
    if ob_details:
        print(f"\n📈 推送执行明细子表({len(ob_details)} 条 OB 端明细)...")
        try:
            detail_plan = push_execution_details(record_id, ob_details, config, apply=True)
            if detail_plan.get("_disabled"):
                print(f"   ⏭  config.execution_detail.table_id 未配置,跳过明细推送")
            else:
                c, u, s, e = (len(detail_plan["creates"]), len(detail_plan["updates"]),
                              len(detail_plan["skipped"]), len(detail_plan["errors"]))
                print(f"   ✅ CREATE {c} / UPDATE {u} / SKIP {s} / ERROR {e}")
                for err in detail_plan["errors"]:
                    print(f"      ❌ {err}")
        except Exception as e:
            print(f"   ⚠️  明细推送异常: {e}(主 task push 已成功,不影响)")

    return {"success": True, "action": action, "record_id": record_id, "path": str(md_path)} if _silent_fail else None


def pull_task_from_feishu(input_path_or_rid: str, apply: bool = False) -> None:
    """v0.5.3(2026-05-29):单条拉 — 飞书指定 record → OB task md(对称 push_task_md)

    用法:
        python3 sync.py --pull-task /path/to/task.md       # dry-run(从 task md 读 feishu_record)
        python3 sync.py --pull-task recXXX --apply          # 直接传 record_id

    场景(用户原话"和 git 一样,只提交一条也不容易覆盖其他的"):
    - 只想同步关心的 1 条 task,不动其他 21 条 today task
    - 早上拉今日批量后,白天偶尔在飞书改某条字段,只拉这条回 OB

    流程:
    1. 解析输入(task md 路径或 record_id)→ 拿 record_id + path
    2. 拉飞书 record → 跟 OB 端 frontmatter / H2 段做 diff
    3. dry-run 显示 diff;apply 写 OB(同 pull-today 单条逻辑)

    冲突策略对齐 pull-today:飞书覆盖 OB(PRESERVE_OB_IF_FS_EMPTY 防误清)
    """
    config = load_config()
    vault_root = find_vault_root()

    print(f"\n{'='*60}")
    print(f"📥 pull-task: 单条拉 飞书 → OB")
    if not apply:
        print(f"📌 dry-run(--apply 才真写)")
    print(f"{'='*60}\n")

    # Step 1: 解析输入
    target_rid = None
    md_path = None
    if input_path_or_rid.startswith("rec") and "/" not in input_path_or_rid:
        # 直接是 record_id
        target_rid = input_path_or_rid
    else:
        # task md 路径
        p = Path(input_path_or_rid)
        if not p.exists():
            # 用 push_task_md 一样的 vault fallback
            print(f"⚠️  路径不存在: {p},vault rglob 同名查找...")
            candidates = [
                c for c in vault_root.rglob(p.name)
                if not any(part.startswith(".") for part in c.parts)
            ]
            if not candidates:
                print(f"❌ vault 内未找到 {p.name}", file=sys.stderr)
                sys.exit(1)
            inbox_matches = [c for c in candidates if "04 Inbox" in c.parts]
            p = inbox_matches[0] if inbox_matches else candidates[0]
            print(f"✅ 找到: {p.relative_to(vault_root)}")
        md_path = p
        # 读 frontmatter 拿 feishu_record
        try:
            fm, _, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
            target_rid = fm.get("feishu_record") if fm else None
        except Exception as e:
            print(f"❌ 读 task md 失败: {e}", file=sys.stderr)
            sys.exit(1)
        if not target_rid:
            print(f"❌ task md 无 feishu_record 字段(可能未 sync 飞书),无法 pull", file=sys.stderr)
            sys.exit(1)

    print(f"🎯 目标 record_id: {target_rid}")
    if md_path:
        print(f"📍 OB task md: {md_path.relative_to(vault_root)}")

    # Step 2: 拉飞书 record
    print(f"\n⏳ 拉飞书 record...")
    record_result = feishu_get_record(target_rid, config)
    if not record_result:
        print(f"❌ 飞书 record 拉取失败", file=sys.stderr)
        sys.exit(1)
    record = record_result.get("record", {})
    if not record:
        print(f"❌ 飞书 record 为空", file=sys.stderr)
        sys.exit(1)

    # 构造 fields_meta + row(对齐 pull-today 的格式)
    fields_meta = list(record.keys())
    row = [record[f] for f in fields_meta]

    # Step 3: 找 OB 对应 task md(如果输入是 record_id,扫 vault)
    if md_path is None:
        ob_index = _scan_ob_task_md_by_feishu_record(vault_root)
        if target_rid in ob_index:
            md_path = ob_index[target_rid]["path"]
            print(f"📍 OB 端 task md: {md_path.relative_to(vault_root)}")
        else:
            print(f"\n⚠️  飞书有 OB 无,自动建 task md...")
            ob_index_for_create = _scan_ob_task_md_by_feishu_record(vault_root)
            if apply:
                created = _create_task_md_from_feishu_record(
                    target_rid, row, fields_meta, config, vault_root, ob_index=ob_index_for_create
                )
                if created:
                    print(f"✅ 建: {created.relative_to(vault_root)}")
                else:
                    print(f"⚠️  跳过(已存在或同名冲突)")
            else:
                print(f"📌 dry-run: --apply 才真建")
            return

    # Step 4: 计算 diff(对齐 pull-today 的 _compute_field_diff)
    ob_index_for_diff = _scan_ob_task_md_by_feishu_record(vault_root)
    fs_fields = _extract_fields_from_feishu_row(row, fields_meta, config, ob_index=ob_index_for_diff)
    fm_updates, fm_summary = _diff_frontmatter_with_feishu(md_path, fs_fields)
    h2_updates, h2_summary = _diff_h2_sections_with_feishu(md_path, fs_fields)

    # today_history compute(对齐 pull-today plan_skip)
    today_iso = _now_with_tz(config).strftime("%Y-%m-%d")
    history_diff = None
    try:
        fm_cur, _, _ = parse_frontmatter(md_path.read_text(encoding="utf-8"))
        history = fm_cur.get("today_history", []) if fm_cur else []
        if not isinstance(history, list):
            history = []
        if today_iso not in [str(h) for h in history]:
            history_diff = history + [today_iso]
    except Exception:
        pass

    if not fm_updates and not h2_updates and history_diff is None:
        print(f"\n✅ OB ↔ 飞书 已对齐,无需更新")
        return

    print(f"\n📋 diff:")
    if history_diff:
        print(f"  📅 today_history += {today_iso}")
    for field, ob_val, fs_val in fm_summary:
        def _short(v, limit=35):
            s = str(v).replace("\n", " / ")
            return s if len(s) <= limit else s[: limit - 3] + "..."
        print(f"  • {field}: {_short(ob_val)} → {_short(fs_val)}")
    for h2_label, ob_val, fs_val in h2_summary:
        def _short(v, limit=50):
            s = str(v).replace("\n", " / ")
            return s if len(s) <= limit else s[: limit - 3] + "..."
        print(f"  • 📑 {h2_label}: {_short(ob_val)} → {_short(fs_val)}")

    if not apply:
        print(f"\n📌 dry-run 完成。--apply 真写 OB frontmatter + H2 段")
        return

    # Step 5: apply
    print(f"\n🚀 开始 apply...")
    final_updates = dict(fm_updates)
    if history_diff:
        final_updates["today_history"] = history_diff
    if final_updates:
        if update_md_frontmatter(md_path, final_updates):
            print(f"  ✅ frontmatter 更新 {len(final_updates)} 字段")
        else:
            print(f"  ❌ frontmatter 更新失败")
    for h2_title, new_content in h2_updates.items():
        if update_h2_section_in_task_md(md_path, h2_title, new_content):
            print(f"  ✅ H2 段更新: {h2_title}")
    print(f"\n✅ pull-task 完成")


def migrate_today_history_unquoted(apply: bool = False) -> None:
    """v0.4.0+ Step 3(2026-05-29):反向 migration — quoted ISO date 改回 unquoted

    上次 migration(往 quoted 改)方向错了 — console 诊断证明 unquoted YAML date
    → dataview luxon DateTime,contains 比较工作;quoted string → dataview string,
    contains 比较 string vs DateTime 失败。

    本命令把所有 today_history 内的 quoted ISO date string 改回 unquoted。

    用法:
        python3 sync.py --migrate-today-history-unquote          # dry-run
        python3 sync.py --migrate-today-history-unquote --apply  # 真改
    """
    vault_root = find_vault_root()

    print(f"\n{'='*60}")
    print(f"🔧 migrate-today-history-unquote: quoted 改回 unquoted")
    if not apply:
        print(f"📌 dry-run(--apply 才真改)")
    print(f"{'='*60}\n")

    pattern_th = re.compile(r"^today_history:\s*\[([^\]]*?)\]\s*$", re.MULTILINE)
    pattern_quoted_date = re.compile(r"'(\d{4}-\d{2}-\d{2})'")

    candidates = []
    for md in vault_root.rglob("*.md"):
        if any(part.startswith(".") for part in md.parts):
            continue
        if md.name.startswith("_"):
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.match(r"^(---\r?\n)(.*?)(\r?\n---\r?\n)", text, re.DOTALL)
        if not m:
            continue
        fm_text = m.group(2)
        th_m = pattern_th.search(fm_text)
        if not th_m:
            continue
        inner = th_m.group(1).strip()
        if not inner or not pattern_quoted_date.search(inner):
            continue
        # 把 quoted date 改 unquoted
        new_inner = pattern_quoted_date.sub(r"\1", inner)
        new_line = f"today_history: [{new_inner}]"
        candidates.append((md, th_m.group(0), new_line))

    if not candidates:
        print(f"✅ 所有 today_history 已是 unquoted,无需 migration")
        return

    print(f"📋 找到 {len(candidates)} 条 task md 含 quoted today_history\n")

    for md, original, new_line in candidates[:10]:
        try:
            rel = md.relative_to(vault_root)
        except Exception:
            rel = md
        print(f"  📝 {rel}")
        print(f"     - {original}")
        print(f"     + {new_line}")
    if len(candidates) > 10:
        print(f"  ... 还有 {len(candidates) - 10} 条")

    if not apply:
        print(f"\n📌 dry-run 完成。--apply 真改 {len(candidates)} 条")
        return

    print(f"\n🚀 开始 apply...")
    success_count = 0
    fail_count = 0
    for md, original, new_line in candidates:
        try:
            text = md.read_text(encoding="utf-8")
            new_text = text.replace(original, new_line, 1)
            if new_text != text:
                md.write_text(new_text, encoding="utf-8")
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            print(f"  ❌ {md.name}: {e}")
            fail_count += 1

    print(f"\n{'='*60}")
    print(f"📊 unquote migrate 完成: ✅ {success_count} / ❌ {fail_count}")
    print(f"{'='*60}\n")


def migrate_today_history_quoted(apply: bool = False) -> None:
    """v0.4.0+ Step 3(2026-05-28)一次性 migration:把所有 task md 的
    `today_history: [date1, date2]` unquoted 形式改写为 `today_history: ['date1', 'date2']` quoted

    原因:Obsidian dataview 对 unquoted YAML date 解析为 DateTime 对象,
    跟 `this.file.day`(也是 DateTime)的 contains() 比较可能失败(类型转换 bug)。
    quoted string 形式跟 file.day toISODate() 比较一致,稳定显示。

    用法:
        python3 sync.py --migrate-today-history          # dry-run 看哪些会改
        python3 sync.py --migrate-today-history --apply  # 真改
    """
    vault_root = find_vault_root()

    print(f"\n{'='*60}")
    print(f"🔧 migrate-today-history: today_history 改为 quoted string")
    if not apply:
        print(f"📌 dry-run(--apply 才真改)")
    print(f"{'='*60}\n")

    # 扫全 vault task md 找 today_history 不是 quoted 的
    candidates = []
    pattern_unquoted = re.compile(r"^today_history:\s*\[([^\]]*?)\]\s*$", re.MULTILINE)
    pattern_date_in_list = re.compile(r"(?<![\'\"])(\d{4}-\d{2}-\d{2})(?![\'\"])")

    for md in vault_root.rglob("*.md"):
        if any(part.startswith(".") for part in md.parts):
            continue
        if md.name.startswith("_"):
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        # 只看 frontmatter 部分
        m = re.match(r"^(---\r?\n)(.*?)(\r?\n---\r?\n)", text, re.DOTALL)
        if not m:
            continue
        fm_text = m.group(2)
        # 找 today_history 行
        th_match = pattern_unquoted.search(fm_text)
        if not th_match:
            continue
        inner = th_match.group(1).strip()
        if not inner:
            continue  # 空 list 跳过
        # 检查是否含 unquoted date
        unquoted_dates = pattern_date_in_list.findall(inner)
        if not unquoted_dates:
            continue  # 已全部 quoted,跳过
        candidates.append((md, th_match.group(0), inner))

    if not candidates:
        print(f"✅ 所有 task md 的 today_history 已是 quoted 或空,无需 migration")
        return

    print(f"📋 找到 {len(candidates)} 条 task md 含 unquoted today_history\n")

    for md, original_line, inner in candidates[:10]:
        try:
            rel = md.relative_to(vault_root)
        except Exception:
            rel = md
        # 构造 quoted 版本
        dates = [d.strip() for d in inner.split(",") if d.strip()]
        quoted_dates = [
            f"'{d}'" if re.match(r"^\d{4}-\d{2}-\d{2}$", d) and not (d.startswith("'") or d.startswith('"')) else d
            for d in dates
        ]
        new_line = f"today_history: [{', '.join(quoted_dates)}]"
        print(f"  📝 {rel}")
        print(f"     - {original_line}")
        print(f"     + {new_line}")

    if len(candidates) > 10:
        print(f"  ... 还有 {len(candidates) - 10} 条")

    if not apply:
        print(f"\n📌 dry-run 完成。--apply 真改 {len(candidates)} 条 task md")
        return

    # apply: 逐条改
    print(f"\n🚀 开始 apply...")
    success_count = 0
    fail_count = 0
    for md, original_line, inner in candidates:
        try:
            text = md.read_text(encoding="utf-8")
            dates = [d.strip() for d in inner.split(",") if d.strip()]
            quoted_dates = [
                f"'{d}'" if re.match(r"^\d{4}-\d{2}-\d{2}$", d) and not (d.startswith("'") or d.startswith('"')) else d
                for d in dates
            ]
            new_line = f"today_history: [{', '.join(quoted_dates)}]"
            new_text = text.replace(original_line, new_line, 1)
            if new_text != text:
                md.write_text(new_text, encoding="utf-8")
                success_count += 1
            else:
                print(f"  ⚠️  {md.name} 替换无变化")
                fail_count += 1
        except Exception as e:
            print(f"  ❌ {md.name}: {e}")
            fail_count += 1

    print(f"\n{'='*60}")
    print(f"📊 migrate 完成: ✅ {success_count} / ❌ {fail_count}")
    print(f"{'='*60}\n")


def push_all_today_task_md(apply: bool = False) -> None:
    """v0.4.0+ Step 3(2026-05-28):批量推 OB today=true task md 到飞书(forward 方向)

    用法:
        python3 sync.py --push-all-today              # dry-run 看哪些会推
        python3 sync.py --push-all-today --apply      # 真推

    场景:AI 助手 / Claude Code 在 OB 端补充了多条 task md 的「## 📦 交付」/
    「## 🪞 复盘」/「## 💡 执行思路」等 H2 段后,一键把所有今日 task 的改动推到飞书看板
    (对称 pull-today 飞书 → OB 的反向操作)

    扫描范围:全 vault(对齐 v0.4.0 Step 3 `_scan_ob_task_md_by_feishu_record` 的全 vault 扫)
    过滤(v0.5.4 起 union):
      - OB today=true → 推(同步所有字段)
      - 飞书 是否今日=true 但 OB today=false → 推(同步"取消今日",把 false 写回飞书)
    旧版只筛 OB today=true,导致用户在 OB 端把 today 改成 false 时这条被过滤,
    飞书侧 是否今日 永远停留在 true。

    冲突策略:OB 覆盖飞书(对称 pull-today 的"飞书覆盖 OB")
    防御:`build_fields_payload` 内部已 handle 空字段(空字段不写),不会清空飞书侧已有数据
    """
    config = load_config()
    vault_root = find_vault_root()

    print(f"\n{'='*60}")
    print(f"🎯 push-all-today: 批量推 OB today=true task md → 飞书 forward")
    if not apply:
        print(f"📌 dry-run(--apply 才真写)")
    print(f"{'='*60}\n")

    # 扫全 vault task md 索引(按 feishu_record)
    print("⏳ 扫 OB vault task md(全 vault,按 feishu_record 建索引)...")
    ob_index = _scan_ob_task_md_by_feishu_record(vault_root)

    # v0.5.4(2026-05-28):拉飞书侧「是否今日」=true 的 record_id 列表,
    # 让"OB 把 today: true 改成 false"这种"取消今日"场景也能被推上去
    # (原版只筛 OB today=true → 改 false 的 task 被直接过滤,飞书侧永远不更新)
    print("⏳ 拉飞书侧 是否今日=true record_id 列表(为侦测取消今日)...")
    feishu_today_rids: set = set()
    try:
        all_records, all_ids, fields_meta = _fetch_all_records_from_feishu(config)
        feishu_today_rids = {rid for rid, _ in filter_today_tasks(all_records, all_ids, fields_meta, config)}
        print(f"✅ 飞书 是否今日=true: {len(feishu_today_rids)} 条")
    except Exception as e:
        print(f"⚠️  拉飞书侧 是否今日=true 列表失败({e}),只推 OB today=true(取消今日场景将漏推)")

    # 分类:
    # - ob_today_true: OB today=true → 推所有字段(原行为)
    # - cancel_today: 飞书=true 但 OB today=false / 缺失 → 推 today=false(取消今日)
    ob_today_rids = {rid for rid, entry in ob_index.items() if entry["today"]}
    cancel_today_rids = {
        rid for rid in feishu_today_rids
        if rid in ob_index and not ob_index[rid]["today"]
    }
    push_rids = ob_today_rids | cancel_today_rids
    today_entries = [(rid, ob_index[rid]) for rid in push_rids]
    print(f"✅ 待推 {len(today_entries)} 条(today=true: {len(ob_today_rids)},取消今日: {len(cancel_today_rids)})\n")

    if not today_entries:
        print("⚠️  无可推 task md(OB today=true 与 飞书 是否今日=true 均空),退出")
        return

    # 逐条 push
    success_count = 0
    fail_count = 0
    create_count = 0
    update_count = 0
    cancel_count = 0
    failures = []
    for rid, entry in today_entries:
        p = entry["path"]
        is_cancel = rid in cancel_today_rids
        print(f"\n{'─'*60}")
        try:
            print(f"📍 {p.relative_to(vault_root)}{' [取消今日]' if is_cancel else ''}")
        except Exception:
            print(f"📍 {p}{' [取消今日]' if is_cancel else ''}")
        result = push_task_md(p, apply=apply, _silent_fail=True)
        if result is None:
            # 不应该到这里(_silent_fail=True 必返 dict)
            fail_count += 1
            failures.append((p, "返回 None(_silent_fail 异常)"))
            continue
        if result.get("success"):
            success_count += 1
            if result.get("action") == "CREATE":
                create_count += 1
            elif result.get("action") == "UPDATE":
                update_count += 1
            if is_cancel:
                cancel_count += 1
        else:
            fail_count += 1
            failures.append((p, result.get("error", "未知错误")))

    print(f"\n{'='*60}")
    print(f"📊 push-all-today {'apply' if apply else 'dry-run'} 汇总:")
    print(f"  ✅ 成功: {success_count}({create_count} CREATE / {update_count} UPDATE,其中 {cancel_count} 条为取消今日)")
    print(f"  ❌ 失败: {fail_count}")
    if failures:
        print(f"\n失败详情:")
        for p, err in failures[:10]:
            print(f"  - {p.name[:50]}: {err}")
        if len(failures) > 10:
            print(f"  ... 还有 {len(failures) - 10} 条")
    print(f"{'='*60}\n")


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
    # v0.5.1: 走 _now_with_tz 尊重 config.behavior.timezone
    today = _now_with_tz(config).strftime(config["reverse"]["write_target"]["date_format"])
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


def _scan_ob_task_md_by_feishu_record(scan_root: Path) -> dict:
    """扫 scan_root 下所有 .md,按 feishu_record 字段建索引。

    v0.4.0+(2026-05-28)Step 3:scan_root 从 04 Inbox/task/ 扩展到 vault_root(全 vault 扫)—
    解决 Obsidian Auto Note Mover 等插件根据关键词自动移动 task md 后(如「炒股」→ 02 Area/08 炒股/),
    sync.py 无法关联回它,导致 pull-today 误判"飞书有 OB 无" → 重建 → Auto Note Mover 又拦 → 死循环

    Returns: {rec_id: {"path": Path, "today": bool, "status": str, "today_history": list[str]}}
    跳过:
    - 没 feishu_record 字段的 .md(=本地笔记非 task)
    - _ 开头的 _task.base / _说明.md 等
    - 隐藏目录(.obsidian / .git / .trash 等)

    Duplicate 检测:同一 rec_id 有多份 task md(Auto Note Mover 移走 + sync 重建留下重复)
    → 取**最后修改时间最新**的,打 warning 让用户清理

    v0.2.5: 加 today_history 抽取(用于 pull_today_from_feishu 防御性清理"残留"日期)
    """
    EXCLUDE_HIDDEN_PREFIX = (".",)  # 跳过 .obsidian / .git / .trash 等

    # 收集所有 candidate .md,按 mtime 倒序(最新在前)
    candidates = []
    for md_path in scan_root.rglob("*.md"):
        if any(part.startswith(EXCLUDE_HIDDEN_PREFIX) for part in md_path.parts):
            continue
        if md_path.name.startswith("_"):
            continue
        try:
            mtime = md_path.stat().st_mtime
        except Exception:
            continue
        candidates.append((mtime, md_path))
    candidates.sort(key=lambda x: x[0], reverse=True)

    index = {}
    duplicates = []  # [(rec_id, kept_path, dropped_path), ...]
    for _, md_path in candidates:
        try:
            text = md_path.read_text(encoding="utf-8")
        except Exception:
            continue

        # v0.6.2(2026-05-30)根治:改用 parse_frontmatter 统一解析(支持 inline + block list + 损坏 fallback)
        # 旧手工 line-by-line parse 只支持 inline `today_history: [a, b]`,
        # 不支持 OB linter normalize 后的 block list 形式:
        #     today_history:
        #       - 2026-05-29
        #       - 2026-05-30
        # 导致 scan 读不到 history → plan_set_false history_has_today 判断失效 →
        # 用户在飞书取消今日勾选后 sync.py 不会自动删 OB history 5/30 → daily note 仍显示
        # 改用 PyYAML 完整 parse(走 parse_frontmatter,自带 v0.5.4 损坏抢救)
        fm, _, _ = parse_frontmatter(text)
        if not fm:
            continue

        rec_id_raw = fm.get("feishu_record")
        rec_id = str(rec_id_raw).strip() if rec_id_raw else None
        if rec_id and rec_id.startswith("#"):
            rec_id = None
        today_val = bool(fm.get("today", False))
        status_val = str(fm.get("status", "todo") or "todo").lower()
        raw_hist = fm.get("today_history") or []
        # date object / str 都转 ISO 字符串(YAML 自动 parse 日期为 datetime.date)
        today_history: list[str] = [str(d) for d in raw_hist] if isinstance(raw_hist, list) else []

        if rec_id:
            if rec_id in index:
                # 重复:已有 index 是更新的(mtime sort 在前),当前是更老的 → drop 当前
                duplicates.append((rec_id, index[rec_id]["path"], md_path))
                continue
            index[rec_id] = {
                "path": md_path,
                "today": today_val,
                "status": status_val,
                "today_history": today_history,
            }

    if duplicates:
        print(f"⚠️  发现 {len(duplicates)} 条 task md 重复绑定同一 feishu_record:")
        print(f"    (可能 Auto Note Mover 移走文件后 sync.py 又重建,留下重复)")
        for rec_id, kept, dropped in duplicates[:5]:
            try:
                kept_rel = kept.relative_to(scan_root)
                dropped_rel = dropped.relative_to(scan_root)
            except Exception:
                kept_rel, dropped_rel = kept, dropped
            print(f"    🔗 {rec_id}")
            print(f"       ✅ 保留(mtime 新): {kept_rel}")
            print(f"       ⏭  跳过(mtime 旧): {dropped_rel}")
        if len(duplicates) > 5:
            print(f"    ... 还有 {len(duplicates) - 5} 条")
        print(f"    💡 建议:手动 review + 删除「跳过」的那份")

    return index


def _extract_fields_from_feishu_row(row, fields_meta, config, ob_index: Optional[dict] = None) -> dict:
    """v0.3.7: 从飞书 row 抽出 OB frontmatter 同步字段 dict

    与 _create_task_md_from_feishu_record(plan_missing 反向建)+ pull-today 反向 diff sync 共享。
    不含 today / today_history / today_source(today 逻辑独立)
    不含 feishu_record / feishu_url / created / 日志(不应反向覆盖)
    v0.4.0(2026-05-28)起含正文 H2 段(delivery / user_story);仍不含其他 H2 段
    (acceptance / thinking / resources / retrospective / execution_summary 暂保持单向 OB→飞书)

    Args:
        row, fields_meta, config: 飞书 record list 返回
        ob_index: v0.4.0 加 — _scan_ob_task_md_by_feishu_record 索引(用于 parent_task 反向 record_id → wikilink)
                  传 None → parent_task 字段空字符串(找不到对应 OB task md)

    Returns dict:
        title: str
        priority: str (P0-P3,默认 P3)
        status: str (OB 7 态:todo/doing/subdone/done/block/cancel/idea)
        category: str (空字符串 if 飞书侧无)
        subcategory: list[str]
        adhd_priority: str
        estimate_hours: str | "" (number 直接 stringify)
        due: str (YYYY-MM-DD or "")
        done_date: str (YYYY-MM-DD or "")
        parent_project: str (裸名字,如 "00 布丁";无 wikilink 包裹)
        created_iso: str | None (反向建模板用,diff sync 不用)
        # v0.4.0(2026-05-28):5 字段补全
        quality: str ("高"/"中"/"低" 或 "")
        actual_hours: str | "" (number 直接 stringify,跟 estimate_hours 同格式)
        parent_task: str ("[[<父 task stem>]]" wikilink 形态;OB 无对应或飞书侧空 → "")
        delivery: str (正文段内容,多行;飞书侧空 → "")
        user_story: str (正文段内容)
        # v0.4.0+ Step 2(2026-05-28)反向同步扩展 10 字段
        efficiency: str ("高"/"中"/"低" 或 "")
        project_minor: list[str] (multi-select)
        iteration_week: list[str] (multi-select,如 ["26W23(...)"])
        iteration_month: list[str] (multi-select,如 ["26 年 5 月"])
        parent_project (覆盖):优先「产品项目」link 字段反解析(取 link record 的 text);
                              无 link → fallback 老的"项目"启发性值;最后 fallback "00 布丁"
        execution_summary / acceptance / thinking / resources / retrospective_text: str (5 个 H2 段内容)
    """
    def _idx(field):
        return fields_meta.index(field) if field in fields_meta else -1

    def _get(field):
        i = _idx(field)
        return row[i] if 0 <= i < len(row) else None

    def _list_first(v):
        return v[0] if isinstance(v, list) and v else (v if not isinstance(v, list) else None)

    def _text_value(v):
        """飞书 text 字段值 → 纯字符串
        - string → as-is
        - list of {"text": "..."} 段 → 拼接(rich text 形态)
        - None → ""
        """
        if v is None:
            return ""
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            parts = []
            for seg in v:
                if isinstance(seg, dict) and "text" in seg:
                    parts.append(seg["text"])
                elif isinstance(seg, str):
                    parts.append(seg)
                else:
                    parts.append(str(seg))
            return "".join(parts)
        return str(v)

    def _link_first_id(v):
        """飞书 link 字段值 → 第一个 record_id
        link 字段格式:[{"id": "rec...", "text": "...", "type": "text"}, ...]
        """
        if not isinstance(v, list) or not v:
            return None
        first = v[0]
        if isinstance(first, dict):
            return first.get("id") or first.get("record_id")
        return None

    def _ms_to_date(ms):
        if not ms:
            return ""
        try:
            dt = datetime.fromtimestamp(int(ms) / 1000, tz=timezone(timedelta(hours=8)))
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return ""

    def _ms_to_iso(ms):
        if not ms:
            return None
        try:
            dt = datetime.fromtimestamp(int(ms) / 1000, tz=timezone(timedelta(hours=8)))
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            return None

    title = _get("任务标题") or "(无标题)"
    priority = _list_first(_get("价值优先级")) or "P3"
    status_fs = _list_first(_get("执行状态")) or "Todo"
    # v0.3.5: 7 态对齐飞书看板,SubDone/Idea 不再降级,补 cancel 映射
    status_map = {
        "Todo": "todo", "Doing": "doing", "Done": "done",
        "Block": "block", "SubDone": "subdone", "Idea": "idea",
        "cancel": "cancel",
    }
    status = status_map.get(status_fs, "todo")
    category = _list_first(_get("大类")) or ""
    subcategory = _get("小类") or []
    if not isinstance(subcategory, list):
        subcategory = [subcategory] if subcategory else []
    adhd_priority = _list_first(_get("ADHD优先级")) or ""
    estimate_hours_raw = _get("估时")
    estimate_hours = str(estimate_hours_raw) if estimate_hours_raw not in (None, "") else ""
    created_iso = _ms_to_iso(_get("创建时间"))
    due = _ms_to_date(_get("截止日期"))
    done_date = _ms_to_date(_get("完成时间"))

    # parent_project — v0.4.0+ Step 2(2026-05-28)重构:
    # 优先「产品项目」link 字段反解析(取 link record 的 text),无 link → 空字符串
    # 移除老的"if title startswith 【布丁 → 00 布丁"启发性 fallback —
    # 该 fallback 在完整反向同步场景下会**篡改用户实际选的子级关联**(已实测 bug)
    # 飞书侧 link 字段空 → fs_str 为空 → PRESERVE_OB_IF_FS_EMPTY 保留 OB
    parent_project = ""

    # v0.4.0(2026-05-28):5 字段补全
    # quality(完成质量):飞书 select 单选 → list 首元素或空
    quality = _list_first(_get("完成质量")) or ""
    # actual_hours(用时):飞书 number → 跟 estimate_hours 同 stringify
    actual_hours_raw = _get("用时")
    actual_hours = str(actual_hours_raw) if actual_hours_raw not in (None, "") else ""
    # parent_task(飞书侧字段名「相关任务」,2026-05-28 修):飞书 link 字段 → 取首 record_id → 反查 ob_index → wikilink
    # ob_index 无对应 record_id(可能父 task 未被 pull / 不存在)→ 留空字符串(不写注释)
    parent_task = ""
    parent_rec_id = _link_first_id(_get("相关任务"))
    if parent_rec_id and ob_index and parent_rec_id in ob_index:
        parent_path = ob_index[parent_rec_id]["path"]
        parent_task = f"[[{parent_path.stem}]]"
    # delivery / user_story:正文 H2 段,飞书 text 字段
    delivery = _text_value(_get("交付"))
    user_story = _text_value(_get("用户故事"))

    # v0.4.0+(2026-05-28)Step 2 反向同步扩展 — 10 字段补全(efficiency / project_minor /
    # iteration_* / parent_project + execution_summary / acceptance / thinking / resources / retrospective)
    # 这些字段 forward 早就支持(task_md_fields 通用分发),reverse 之前缺
    efficiency = _list_first(_get("完成效率")) or ""
    project_minor_raw = _get("项目小类") or []
    project_minor = project_minor_raw if isinstance(project_minor_raw, list) else (
        [project_minor_raw] if project_minor_raw else []
    )
    iter_week_raw = _get("执行迭代周") or []
    iteration_week = iter_week_raw if isinstance(iter_week_raw, list) else (
        [iter_week_raw] if iter_week_raw else []
    )
    iter_month_raw = _get("执行迭代月") or []
    iteration_month = iter_month_raw if isinstance(iter_month_raw, list) else (
        [iter_month_raw] if iter_month_raw else []
    )
    # parent_project(产品项目 link 字段)— 飞书 link 字段返回 [{"id": rec, "text": "...", ...}]
    # 反向解析:取 text(record 名)直接作为 wikilink target(无前缀,因为 OB 端 "00 布丁"
    # ↔ 飞书 "布丁" 差异由 strip_prefix_regex 处理,反向时仅取飞书原名 — 若用户 OB 端用前缀名,
    # 反向写回会显示无前缀名 [[布丁]],ob_index 找不到精确匹配;**这是已知 trade-off**,
    # 用户可在 OB 端给「布丁」加 alias 或手动 rename)
    parent_project_link = _get("产品项目")
    parent_project_reverse = ""
    if isinstance(parent_project_link, list) and parent_project_link:
        first = parent_project_link[0]
        if isinstance(first, dict):
            parent_project_reverse = first.get("text") or ""
    # 覆盖原先启发性 "项目" 字段判断(优先「产品项目」link 反解析)
    if parent_project_reverse:
        parent_project = parent_project_reverse

    # 正文 H2 段反向(5 个):
    execution_summary = _text_value(_get("执行概述"))
    acceptance = _text_value(_get("验收条件"))
    thinking = _text_value(_get("执行思路"))
    resources = _text_value(_get("相关资料"))
    retrospective_text = _text_value(_get("复盘"))

    return {
        "title": title,
        "priority": priority,
        "status": status,
        "category": category,
        "subcategory": subcategory,
        "adhd_priority": adhd_priority,
        "estimate_hours": estimate_hours,
        "due": due,
        "done_date": done_date,
        "parent_project": parent_project,
        "created_iso": created_iso,
        # v0.4.0(2026-05-28)5 字段补全
        "quality": quality,
        "actual_hours": actual_hours,
        "parent_task": parent_task,
        "delivery": delivery,
        "user_story": user_story,
        # v0.4.0+ Step 2(2026-05-28)反向同步 10 字段扩展
        "efficiency": efficiency,
        "project_minor": project_minor,
        "iteration_week": iteration_week,
        "iteration_month": iteration_month,
        "execution_summary": execution_summary,
        "acceptance": acceptance,
        "thinking": thinking,
        "resources": resources,
        "retrospective_text": retrospective_text,
    }


# v0.3.7 反向 diff sync 的字段白名单(从飞书覆盖 OB frontmatter 时只动这些)
# 不含 title(标题改了会改文件名,风险大)/ created / feishu_record / feishu_url / today*
# v0.4.0(2026-05-28):加 quality / actual_hours / parent_task(3 frontmatter)
# v0.4.0+ Step 2(2026-05-28)完整反向同步扩展:加 efficiency / project_minor / iteration_* / parent_project
# 现在覆盖 16 frontmatter 字段(原 8 + v0.4.0 加 3 + Step 2 加 5 = 16)
_REVERSE_SYNC_FIELD_WHITELIST = [
    "priority", "status", "category", "subcategory",
    "adhd_priority", "estimate_hours", "due", "done_date",
    "quality", "actual_hours", "parent_task",
    # v0.4.0+ Step 2 新加 5 frontmatter
    "efficiency", "project_minor",
    "iteration_week", "iteration_month",
    "parent_project",
]


# v0.4.0(2026-05-28)反向 H2 段同步白名单
# (fs_key, h2_title_full, label) — 飞书 row 字段 → task md 正文 H2 段
# 冲突策略:飞书覆盖 OB(对齐 _REVERSE_SYNC_FIELD_WHITELIST);飞书侧空 → 保留 OB(防御)
# v0.4.0+ Step 2(2026-05-28):加 5 H2 段 — execution_summary / acceptance / thinking / resources / retrospective
# (其中 thinking / resources 飞书实际有字段,OB rules 之前误标"飞书无对应"是错的)
# 现在覆盖 7 H2 段(原 2 + 5)
_REVERSE_SYNC_H2_WHITELIST = [
    ("delivery", "## 📦 交付", "交付"),
    ("user_story", "## 👥 用户故事", "用户故事"),
    # v0.4.0+ Step 2 新加 5 H2 段
    ("execution_summary", "## 📝 执行概述", "执行概述"),
    ("acceptance", "## ✅ 验收条件", "验收条件"),
    ("thinking", "## 💡 执行思路", "执行思路"),
    ("resources", "## 🔗 相关资料", "相关资料"),
    ("retrospective_text", "## 🪞 复盘", "复盘"),
]


def _read_h2_section_content(file_path: Path, h2_pattern: str) -> str:
    """读 task md 文件内 ## <h2_pattern> 段的内容(去 HTML 注释 + strip)

    h2_pattern 是去掉 "## " 前缀的标题(如 "📦 交付"),用于和 parse_task_md.extract_section 一致。
    """
    try:
        text = file_path.read_text(encoding="utf-8")
    except Exception:
        return ""
    m = re.search(
        rf"^## +{re.escape(h2_pattern)}.*?\n(.*?)(?=\n## +|\Z)",
        text, re.MULTILINE | re.DOTALL,
    )
    if not m:
        return ""
    content = m.group(1).strip()
    content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL).strip()
    return content


def update_h2_section_in_task_md(file_path: Path, h2_title: str, new_content: str) -> bool:
    """v0.4.0(2026-05-28):反向同步 H2 段 — 飞书侧值覆盖 task md 内对应 H2 段内容

    - H2 段存在 → 替换内容(保留 H2 标题行不动)
    - H2 段不存在 → 在「## ✅ 完成标记」之前插入完整新 H2 段(标题+内容+空行)
    - new_content 为空 → 不动文件(防御误清,对齐 PRESERVE_OB_IF_FS_EMPTY 策略)
    - 找不到「## ✅ 完成标记」标识 → 放弃插入(task md 不规范,返回 False)

    Args:
        h2_title: 完整 H2 标题(含前缀,如 "## 📦 交付")
        new_content: 飞书侧字段内容,可多行

    Returns: True if 改了文件,False 不变 / 跳过
    """
    if not new_content or not new_content.strip():
        return False
    try:
        text = file_path.read_text(encoding="utf-8")
    except Exception:
        return False

    # new_content 末尾 strip 避免插入多余空行(后续我们主动加分隔)
    new_content_clean = new_content.strip()

    # 段查找:^## <title>\s*$\r?\n + 内容(到下一个 ## 或文件末尾)
    pattern = re.compile(
        rf"^({re.escape(h2_title)})\s*$\r?\n(.*?)(?=\n## +|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match:
        # 段存在 → 替换段内容
        new_segment = f"{match.group(1)}\n{new_content_clean}\n"
        text_new = text[:match.start()] + new_segment + text[match.end():]
    else:
        # 段不存在 → 在 ✅ 完成标记 之前插入
        insert_marker = "## ✅ 完成标记"
        if insert_marker not in text:
            return False
        new_segment = f"{h2_title}\n{new_content_clean}\n\n"
        text_new = text.replace(insert_marker, new_segment + insert_marker, 1)

    if text_new == text:
        return False
    try:
        file_path.write_text(text_new, encoding="utf-8")
        return True
    except Exception as e:
        print(f"⚠️  写 {file_path} 失败: {e}", file=sys.stderr)
        return False


def _strip_wikilink(v) -> str:
    """剥 OB wikilink 形态 → 裸名字。
    "[[00 布丁]]" → "00 布丁"
    "[[00 布丁|别名]]" → "00 布丁"
    "00 布丁" → "00 布丁"
    None / "" → ""
    """
    if v is None:
        return ""
    s = str(v).strip()
    m = re.match(r'^\[\[([^\]|]+)(?:\|[^\]]*)?\]\]$', s)
    return m.group(1).strip() if m else s


def _diff_frontmatter_with_feishu(p, fs_fields: dict) -> tuple[dict, list]:
    """v0.3.7: 读 OB task md frontmatter,与飞书侧字段对比,返回需要 update 的 dict + diff 摘要

    冲突策略:飞书覆盖 OB(飞书是 ADHD 实时操作端,OB 是文档端)

    Args:
        p: OB task md Path
        fs_fields: _extract_fields_from_feishu_row 返回的 dict

    Returns:
        (updates_dict, diff_summary)
        updates_dict: 仅含 OB ≠ 飞书的字段,可直接传 update_md_frontmatter
        diff_summary: list[(field_name, ob_val, fs_val)] 用于 dry-run print
    """
    try:
        fm, _, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
    except Exception:
        return {}, []
    if fm is None:
        return {}, []

    updates = {}
    diff_summary = []

    def _norm_str(v) -> str:
        """规整化为 string,None / 空 list / 空 dict → 空字符串"""
        if v is None:
            return ""
        if isinstance(v, list):
            return ""  # list 走专门分支
        return str(v).strip()

    # v0.3.7 防御性策略:**飞书侧空 → 保留 OB**(避免误清 OB 端有效数据,如手填的 due)
    # 仅 status / priority 例外:它们必有值,空值是异常,飞书侧空也覆盖 OB(理论上不会触发)
    # v0.4.0(2026-05-28):加 quality / actual_hours / parent_task(完成时手填,飞书侧空不应清 OB)
    # v0.4.0+ Step 2(2026-05-28):加 efficiency / project_minor / iteration_* / parent_project
    # 所有 reverse 同步字段都加 PRESERVE 防御(逻辑:OB 端可能正在编辑,飞书侧暂空不该覆盖)
    PRESERVE_OB_IF_FS_EMPTY = {
        "category", "subcategory", "adhd_priority",
        "estimate_hours", "due", "done_date",
        "quality", "actual_hours", "parent_task",
        # v0.4.0+ Step 2 新加
        "efficiency", "project_minor",
        "iteration_week", "iteration_month",
        "parent_project",
    }

    for field in _REVERSE_SYNC_FIELD_WHITELIST:
        fs_val = fs_fields.get(field, "")
        ob_raw = fm.get(field)

        # 飞书侧空 → 大部分字段保留 OB(防御误清)
        fs_is_empty = (fs_val == "" or fs_val == [] or fs_val is None)
        if fs_is_empty and field in PRESERVE_OB_IF_FS_EMPTY:
            continue

        # v0.4.0+ Step 2(2026-05-28):multi-select 字段 list deep equal
        # subcategory(原有)+ project_minor / iteration_week / iteration_month(新加)
        if field in ("subcategory", "project_minor", "iteration_week", "iteration_month"):
            # list deep equal(顺序敏感)
            ob_list = ob_raw if isinstance(ob_raw, list) else (
                [] if not ob_raw else [str(ob_raw)]
            )
            fs_list = fs_val if isinstance(fs_val, list) else []
            if ob_list != fs_list:
                updates[field] = fs_list
                diff_summary.append((field, ob_list, fs_list))
        elif field == "parent_project":
            # parent_project: 飞书侧裸名(如 "布丁") ↔ OB 端 wikilink "[[00 布丁]]"
            # OB → 飞书:strip_prefix_regex 去前缀 + wikilink 解析
            # 飞书 → OB:反向直接用飞书名(无前缀),wrap wikilink
            # 同名比较(去 wikilink 包裹 + 比 stripped name)
            ob_norm = _strip_wikilink(ob_raw) if ob_raw else ""
            # 跟 _extract... 一样,去掉数字前缀比较(允许 OB "00 布丁" ↔ 飞书 "布丁")
            ob_norm_stripped = re.sub(r"^\d+\s+", "", ob_norm).strip()
            fs_str = _norm_str(fs_val)
            if ob_norm_stripped != fs_str and ob_norm != fs_str:
                # 不同 → 飞书覆盖。值是飞书原名(无前缀),OB 端 wikilink 包裹
                updates[field] = f"[[{fs_str}]]" if fs_str else ""
                diff_summary.append((field, ob_norm or "(空)", fs_str or "(空)"))
        else:
            # 普通字段:string 规整化后比较
            ob_str = _norm_str(ob_raw)
            fs_str = _norm_str(fs_val)
            if ob_str != fs_str:
                updates[field] = fs_str
                diff_summary.append((field, ob_str or "(空)", fs_str or "(空)"))

    return updates, diff_summary


def _diff_h2_sections_with_feishu(p: Path, fs_fields: dict) -> tuple[dict, list]:
    """v0.4.0(2026-05-28):对比 OB task md 正文 H2 段 与飞书侧字段,返回 H2 updates + diff 摘要

    冲突策略对齐 _diff_frontmatter_with_feishu:
    - 飞书侧覆盖 OB(飞书是 ADHD 实时操作端,OB 是文档端)
    - 飞书侧空 → 保留 OB(防御误清,对齐 PRESERVE_OB_IF_FS_EMPTY 思想)

    Args:
        p: OB task md Path
        fs_fields: _extract_fields_from_feishu_row 返回 dict(需含 delivery / user_story 等 key)

    Returns:
        (h2_updates_dict, h2_diff_summary)
        h2_updates_dict: {h2_title_full: new_content, ...} 仅含 OB ≠ 飞书且飞书非空的项
        h2_diff_summary: [(h2_label, ob_excerpt, fs_excerpt), ...] 用于 dry-run 打印
    """
    updates: dict = {}
    diff_summary: list = []
    for fs_key, h2_title_full, label in _REVERSE_SYNC_H2_WHITELIST:
        fs_val_raw = fs_fields.get(fs_key) or ""
        fs_val = str(fs_val_raw).strip()
        if not fs_val:
            continue  # 飞书侧空 → 保留 OB(防御误清)
        h2_pattern = h2_title_full.replace("## ", "", 1).strip()
        ob_val = _read_h2_section_content(p, h2_pattern).strip()
        if ob_val != fs_val:
            updates[h2_title_full] = fs_val
            diff_summary.append((label, ob_val or "(空)", fs_val or "(空)"))
    return updates, diff_summary


def _create_task_md_from_feishu_record(rid, row, fields_meta, config, vault_root, ob_index: Optional[dict] = None):
    """从飞书 record 反向建 OB task md(v0.2.5 加,v0.3.7 重构调 helper)

    字段映射 → 见 _extract_fields_from_feishu_row docstring

    v0.4.0(2026-05-28):支持 ob_index 反向解析 parent_task → wikilink;
    新模板含 quality / actual_hours / parent_task frontmatter + 📦 交付 / 👥 用户故事 H2 段

    Returns: 创建的 Path(成功) or None(已存在 / 跳过)
    """
    from datetime import datetime, timezone, timedelta

    fs = _extract_fields_from_feishu_row(row, fields_meta, config, ob_index=ob_index)
    title = fs["title"]
    priority = fs["priority"]
    status = fs["status"]
    category = fs["category"]
    subcategory = fs["subcategory"]
    adhd_priority = fs["adhd_priority"]
    estimate_hours = fs["estimate_hours"]
    due = fs["due"]
    done_date = fs["done_date"]
    parent_project = fs["parent_project"]
    created_iso = fs["created_iso"]
    # v0.4.0(2026-05-28):5 字段补全
    quality = fs.get("quality", "")
    actual_hours = fs.get("actual_hours", "")
    parent_task = fs.get("parent_task", "")  # "[[<stem>]]" 或 ""
    delivery = fs.get("delivery", "")
    user_story = fs.get("user_story", "")
    # v0.4.0+ Step 2(2026-05-28)反向同步 10 字段扩展
    efficiency = fs.get("efficiency", "")
    project_minor = fs.get("project_minor", []) or []
    iteration_week_list = fs.get("iteration_week", []) or []
    iteration_month_list = fs.get("iteration_month", []) or []
    execution_summary = fs.get("execution_summary", "")
    acceptance = fs.get("acceptance", "")
    thinking = fs.get("thinking", "")
    resources = fs.get("resources", "")
    retrospective_text_body = fs.get("retrospective_text", "")

    # 文件名安全
    safe_title = re.sub(r'[/\\*?"<>|]', "_", title)
    today_date = _now_with_tz(config).strftime("%Y-%m-%d")  # v0.5.1: 走 _now_with_tz

    task_dir = vault_root / "04 Inbox" / "task"
    task_dir.mkdir(parents=True, exist_ok=True)
    fpath = task_dir / f"{today_date}-{safe_title}.md"

    if fpath.exists():
        return None

    # v0.4.0+(2026-05-28)Step 3 防御:vault 内可能已有同名 task md(Auto Note Mover 移到别处),
    # 但 ob_index 因 frontmatter 损坏 / 历史原因没扫到,此时再建会造成更多 duplicate。
    # 扫全 vault 同名 `<safe_title>.md`(任意日期前缀)→ 已存在 → skip 并报警
    existing_anywhere = [
        p for p in vault_root.rglob(f"*{safe_title}.md")
        if not any(part.startswith(".") for part in p.parts)
        and not p.name.startswith("_")
    ]
    if existing_anywhere:
        print(f"    ⚠️  vault 内已有同名 task md(可能 Auto Note Mover 移到别处):{existing_anywhere[0].relative_to(vault_root)}")
        print(f"    跳过自动建,请手动 review:确认 feishu_record 字段是否对齐(应为 {rid})")
        return None

    # 拼飞书 URL
    cfg = config["feishu"]
    url = (
        f"https://{cfg['tenant_domain']}/base/{cfg['base_token']}"
        f"?table={cfg['table_id']}&view={cfg['default_view_id']}&record={rid}"
    )

    # 构造 frontmatter
    parent_project_line = (
        f'parent_project: "[[{parent_project}]]"' if parent_project else "parent_project:"
    )
    subcat_line = (
        f"subcategory: {subcategory}" if subcategory else "subcategory:"
    )
    created_line = created_iso or (today_date + "T00:00:00")
    # v0.4.0(2026-05-28):parent_task wikilink 形态(空 → 留空字段)
    parent_task_line = (
        f'parent_task: "{parent_task}"' if parent_task else "parent_task:"
    )
    # 正文 H2 段内容空字符串 → 段下方留空(对齐模板风格)
    delivery_body = delivery if delivery else ""
    user_story_body = user_story if user_story else ""

    # v0.4.0+ Step 2(2026-05-28):新加 frontmatter / H2 段反向填值
    project_minor_line = f"project_minor: {project_minor}" if project_minor else "project_minor:"
    iter_week_line = f"iteration_week: {iteration_week_list}" if iteration_week_list else "iteration_week:"
    iter_month_line = f"iteration_month: {iteration_month_list}" if iteration_month_list else "iteration_month:"
    execution_summary_body = execution_summary if execution_summary else "(从飞书拉回,详情见飞书 record)"
    acceptance_body = acceptance if acceptance else ""
    thinking_body = thinking if thinking else ""
    resources_body = resources if resources else ""
    retrospective_body = retrospective_text_body if retrospective_text_body else ""

    content = f"""---
priority: {priority}
status: {status}
today: true
today_history: [{today_date}]
today_source: planned
created: {created_line}
due: {due}
done_date: {done_date}
category: {category}
{subcat_line}
{project_minor_line}
adhd_priority: {adhd_priority}
estimate_hours: {estimate_hours}
actual_hours: {actual_hours}
efficiency: {efficiency}
quality: {quality}
{parent_project_line}
parent_subproject:
{parent_task_line}
parent_inspiration:
日志: "[[journals/{today_date}]]"
feishu_record: {rid}
feishu_url: '{url}'
{iter_week_line}
{iter_month_line}
completion_month:
tags:
  - task
  - pulled-from-feishu
---

# {title}

<!-- v0.4.0(2026-05-28)H2 段顺序对齐飞书看板视图字段顺序 -->

## 👥 用户故事
{user_story_body}

## ✅ 验收条件
{acceptance_body}

## 💡 执行思路
{thinking_body}

## 📝 执行概述
{execution_summary_body}

## 📦 交付
{delivery_body}

## 🔗 相关资料
{resources_body}

## 🪞 复盘
{retrospective_body}

## ✅ 完成标记
- [ ] [{title}]({url})
"""
    fpath.write_text(content, encoding="utf-8")
    return fpath


def pull_today_from_feishu(apply: bool = False) -> None:
    """拉飞书「是否今日」=true 的 record,同步 OB task md today 字段 + v0.3.7 反向字段 diff sync。

    范围(双向对齐):
    - 飞书 today=true,OB task md today=false → 改 OB today=true(plan_set_true)
    - 飞书 today=false,OB task md today=true → 改 OB today=false(plan_set_false)
    - 飞书 today=true,OB 无对应 task md → 自动建(plan_missing,v0.2.5+)
    - 飞书 today=true,OB 已 today=true → 字段 diff sync(plan_skip,v0.3.7+ 不再"真跳")

    v0.3.7 反向字段 diff sync:
    - 三分支(plan_set_true / plan_skip / plan_set_false)都对 OB frontmatter 做飞书字段 diff
    - 同步字段白名单:_REVERSE_SYNC_FIELD_WHITELIST(priority / status / category / subcategory /
      adhd_priority / estimate_hours / due / done_date / parent_project)
    - 冲突策略:飞书覆盖 OB(飞书是 ADHD 实时操作端,OB 是文档端)
    - dry-run 必显示每个字段 before → after,user 看清楚再 apply
    """
    config = load_config()
    vault_root = find_vault_root()
    task_dir = vault_root / "04 Inbox" / "task"

    print(f"\n{'='*60}")
    print(f"📥 pull-today: 飞书 today=true → OB today=true + 字段 diff sync(v0.3.7)")
    print(f"{'='*60}\n")

    if not task_dir.exists():
        print(f"❌ task 目录不存在: {task_dir}")
        return

    # Step 1: 拉飞书全表
    print("⏳ 拉飞书全表 record...")
    all_records, all_ids, fields_meta = _fetch_all_records_from_feishu(config)
    print(f"✅ 飞书共 {len(all_records)} 条 record\n")
    # v0.3.7: record_id → row 映射,用于 plan_set_false 也能拿到 row 做字段 diff
    rid_to_row = dict(zip(all_ids, all_records))

    # Step 2: 筛「是否今日」=true 的 candidates
    today_candidates = filter_today_tasks(all_records, all_ids, fields_meta, config)
    today_record_ids = {rid for rid, _ in today_candidates}
    print(f"🔍 飞书「是否今日」=true: {len(today_record_ids)} 条")

    # Step 3: 扫 OB 端 task md 建索引
    # v0.4.0+(2026-05-28)Step 3:扫全 vault(非仅 04 Inbox/task/)— 兼容 Auto Note Mover 等
    # 自动移动 task md 的场景。task_dir 仍是新建 task md 的主目录(plan_missing 时建在此)
    print("⏳ 扫 OB vault task md(全 vault,按 feishu_record 建索引)...")
    ob_index = _scan_ob_task_md_by_feishu_record(vault_root)
    print(f"✅ OB 共 {len(ob_index)} 个 task md(有 feishu_record 关联的)\n")

    # v0.6.0(2026-05-29):pre-fetch 子表全表,按 task 分组(执行明细反向同步)
    # 配置未开启 execution_detail 时返回空 dict,后续逻辑自动跳过
    detail_records_by_task: dict = {}
    if config.get("execution_detail", {}).get("table_id"):
        print("⏳ 拉飞书子表 record(执行明细反向 sync)...")
        try:
            detail_records_by_task = _fetch_all_detail_records_grouped(config)
            print(f"✅ 子表共 {sum(len(v) for v in detail_records_by_task.values())} 条 record,涉及 {len(detail_records_by_task)} 个 task\n")
        except Exception as e:
            print(f"⚠️  拉子表失败,本次跳过明细反向 sync: {e}\n")

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
            plan_missing.append((rid, title, row))  # ⚠️ v0.2.5:存 row 以便自动建 task md

    # v0.2.5 修:plan_set_false 触发条件加 today_history 含今日的兜底
    # 原因:journal dataview 用 contains(today_history, this.file.day) 渲染
    # 如果 today 已是 false 但 today_history 仍含今日 → 仍然显示在今日 journal → 用户期望"清理"
    today_date_for_scan = _now_with_tz(config).strftime("%Y-%m-%d")  # v0.5.1
    for rid, entry in ob_index.items():
        if rid in today_record_ids:
            continue
        history_has_today = today_date_for_scan in (entry.get("today_history") or [])
        if entry["today"] or history_has_today:
            plan_set_false.append((rid, entry["path"]))

    # v0.3.7 Step 4.5: 反向字段 diff sync 预计算
    # 对 plan_set_true / plan_skip / plan_set_false 三类全部计算飞书 → OB 字段 diff
    # field_diffs[rid] = {"path": Path, "updates": {field: new_val}, "summary": [(field, ob, fs)]}
    field_diffs: dict = {}
    field_diff_count = 0  # 有字段差异的 task md 数

    def _compute_field_diff(rid_, p_):
        row_ = rid_to_row.get(rid_)
        if row_ is None:
            return None
        # v0.4.0(2026-05-28):传 ob_index 让 parent_task 反向 record_id → wikilink
        fs_fields = _extract_fields_from_feishu_row(row_, fields_meta, config, ob_index=ob_index)
        updates_, summary_ = _diff_frontmatter_with_feishu(p_, fs_fields)
        # v0.4.0(2026-05-28):正文 H2 段反向 diff(交付 / 用户故事)
        h2_updates_, h2_summary_ = _diff_h2_sections_with_feishu(p_, fs_fields)
        if not updates_ and not h2_updates_:
            return None
        return {
            "path": p_,
            "updates": updates_,
            "summary": summary_,
            "h2_updates": h2_updates_,
            "h2_summary": h2_summary_,
        }

    for rid, _t, p in plan_set_true:
        d = _compute_field_diff(rid, p)
        if d:
            field_diffs[rid] = d
            field_diff_count += 1
    for rid, _t, p in plan_skip:
        d = _compute_field_diff(rid, p)
        if d:
            field_diffs[rid] = d
            field_diff_count += 1
    for rid, p in plan_set_false:
        d = _compute_field_diff(rid, p)
        if d:
            field_diffs[rid] = d
            field_diff_count += 1

    # v0.4.0+ Step 3(2026-05-29):预计算 plan_skip 中"today_history 缺今日"
    # 关键 bug 场景:跨天未完成 task,5/28 已 today=true,5/29 跑 pull-today → plan_skip
    # 但 today_history 只有 [..., 5/28],缺 5/29 → 5/29 journal dataview
    # contains(today_history, this.file.day) 不匹配 → 不显示
    # 修:预计算并标识,dry-run 显示 + apply 写入
    today_date_iso_for_history = _now_with_tz(config).strftime("%Y-%m-%d")  # v0.5.1
    history_diffs: dict = {}  # rid -> new today_history(含今日)
    for rid, _t, p in plan_skip:
        try:
            fm_cur, _, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
            history = fm_cur.get("today_history", []) if fm_cur else []
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []
        history_strs = [str(h) for h in history]
        if today_date_iso_for_history not in history_strs:
            history_diffs[rid] = history + [today_date_iso_for_history]

    # Step 5: 打印计划摘要
    print(f"📋 计划摘要:")
    print(f"  ➡️  设 today=true:    {len(plan_set_true)} 条")
    print(f"  ⬅️  设 today=false:   {len(plan_set_false)} 条")
    print(f"  ⏭️  已是 today:       {len(plan_skip)} 条")
    print(f"  ⚠️  飞书有 OB 无:    {len(plan_missing)} 条")
    print(f"  🔄 字段同步(v0.3.7): {field_diff_count} 条 task md 有飞书侧字段改动")
    print(f"  📅 today_history += {today_date_iso_for_history}: {len(history_diffs)} 条(plan_skip 中缺今日的)")

    if plan_set_true:
        print(f"\n--- 设 today=true({len(plan_set_true)} 条)---")
        for rid, title, p in plan_set_true:
            print(f"  ✅ {p.name[:55]}  ← {rid}")

    if plan_set_false:
        print(f"\n--- 设 today=false({len(plan_set_false)} 条)---")
        for rid, p in plan_set_false:
            print(f"  ⬜ {p.name[:55]}")

    if plan_skip:
        print(f"\n--- 已是 today,只字段同步({len(plan_skip)} 条)---")
        for rid, title, p in plan_skip[:5]:
            mark = "🔄" if rid in field_diffs else "⏭ "
            print(f"  {mark} {p.name[:55]}")
        if len(plan_skip) > 5:
            print(f"  ... 还有 {len(plan_skip) - 5} 条")

    if plan_missing:
        print(f"\n--- 🆕 飞书「是否今日」=true 但 OB 无对应 task md({len(plan_missing)} 条,v0.2.5 起 apply 时自动建)---")
        for rid, title, row in plan_missing[:10]:
            print(f"  🆕 {title[:55]}  rid={rid}")
        if len(plan_missing) > 10:
            print(f"  ... 还有 {len(plan_missing) - 10} 条")

    # v0.3.7: 字段 diff 详情(dry-run 必显示,apply 也显示让用户复核)
    # v0.4.0(2026-05-28):加 H2 段 diff 显示(交付 / 用户故事,多行截 50 字)
    if field_diffs:
        print(f"\n--- 🔄 字段同步详情(飞书 → OB,共 {field_diff_count} 条 task md)---")
        for rid, d in field_diffs.items():
            print(f"  📝 {d['path'].name[:55]}")

            def _short(v, limit=35):
                s = str(v).replace("\n", " / ")
                return s if len(s) <= limit else s[: limit - 3] + "..."

            for field, ob_val, fs_val in d["summary"]:
                print(f"     • {field}: {_short(ob_val)} → {_short(fs_val)}")
            # H2 段(交付 / 用户故事)— 截 50 字方便看长文 diff
            for h2_label, ob_val, fs_val in d.get("h2_summary", []) or []:
                print(f"     • 📑 {h2_label}: {_short(ob_val, 50)} → {_short(fs_val, 50)}")

    # v0.6.1:把 plan_skip 也算进 early-return 判断 — plan_skip 内会跑 _pull_details
    # 即使 frontmatter 全对齐,飞书子表可能加了 daily 明细 record 需要拉回 OB 段
    has_detail_sync_potential = bool(detail_records_by_task) and bool(plan_skip or plan_set_true or plan_set_false)
    if not (plan_set_true or plan_set_false or plan_missing or field_diffs or history_diffs or has_detail_sync_potential):
        print(f"\n✅ OB ↔ 飞书 today 状态 + today_history + 字段已对齐,无需更新")
        return

    if not apply:
        print(f"\n📌 dry-run 完成。--apply 真写 frontmatter + 自动建 task md + 字段同步")
        return

    # Step 6: apply
    print(f"\n🚀 开始 apply...")
    success_count = 0
    fail_count = 0
    created_count = 0
    field_sync_count = 0  # v0.3.7: 真改了字段的 task md 数
    # v0.3.0:append today_history 事件流(历史保真,见 rules/feishu-project-sync.md「今日 todo 历史保真」)
    # v0.5.1: 走 _now_with_tz 尊重 config.behavior.timezone
    today_date_iso = _now_with_tz(config).strftime("%Y-%m-%d")

    def _merge_with_field_diff(rid_, base_updates: dict) -> dict:
        """v0.3.7: base updates(today/history/source)+ 飞书字段 diff updates 合并"""
        merged = dict(base_updates)
        if rid_ in field_diffs:
            for k, v in field_diffs[rid_]["updates"].items():
                merged[k] = v
        return merged

    def _apply_h2_updates(rid_, p_) -> int:
        """v0.4.0(2026-05-28):同步飞书 H2 段(交付 / 用户故事)→ task md 正文
        Returns: 真改了的 H2 段数(0 / 1 / 2)
        """
        if rid_ not in field_diffs:
            return 0
        cnt = 0
        for h2_title, new_content in (field_diffs[rid_].get("h2_updates") or {}).items():
            if update_h2_section_in_task_md(p_, h2_title, new_content):
                cnt += 1
        return cnt

    def _pull_details(rid_, p_) -> Optional[dict]:
        """v0.6.0(2026-05-29):拉飞书子表 → 写 OB 端「## 📈 执行明细」段(merge 模式)。
        prefetched 在函数入口已批量拉,这里只做 dict lookup。
        Returns: pull_execution_details_for_task 的结果 dict,或 None(配置未启用 / 此 task 无明细)
        """
        if not detail_records_by_task and not config.get("execution_detail", {}).get("table_id"):
            return None
        prefetched = detail_records_by_task.get(rid_, [])
        return pull_execution_details_for_task(
            rid_, p_, config, apply=True, prefetched_records=prefetched,
        )

    for rid, title, p in plan_set_true:
        # 读现有 today_history,append 当日(去重)
        try:
            fm_cur, _, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
            history = fm_cur.get("today_history", []) if fm_cur else []
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []
        if today_date_iso not in history:
            history.append(today_date_iso)
        # v0.3.6: today_source 区分计划/非计划(ADHD 自觉察)
        # pull-today 触发 set today=true = 早晨规划好的拉来 → planned
        base = {
            "today": True,
            "today_history": history,
            "today_source": "planned",
        }
        # v0.3.7: 合并飞书字段 diff
        final = _merge_with_field_diff(rid, base)
        field_changed = rid in field_diffs
        if update_md_frontmatter(p, final):
            # v0.4.0(2026-05-28):H2 段同步(交付 / 用户故事)
            h2_changed = _apply_h2_updates(rid, p)
            # v0.6.0(2026-05-29):执行明细子表反向 sync
            det_res = _pull_details(rid, p)
            fm_n = len(field_diffs[rid]['summary']) if field_changed else 0
            extra_parts = []
            if fm_n:
                extra_parts.append(f"{fm_n} 字段 sync")
            if h2_changed:
                extra_parts.append(f"{h2_changed} H2 段 sync")
            if det_res and det_res.get("changed"):
                extra_parts.append(f"明细 +{det_res.get('added', 0)}/~{det_res.get('updated', 0)}")
            extra = (" + " + " + ".join(extra_parts)) if extra_parts else ""
            print(f"  ✅ {p.name}: today → true (+ today_history += {today_date_iso}){extra}")
            success_count += 1
            if field_changed or h2_changed or (det_res and det_res.get("changed")):
                field_sync_count += 1
        else:
            print(f"  ❌ {p.name}: 更新失败")
            fail_count += 1

    # v0.3.7: plan_skip 不再"真跳",对有字段 diff 的 task md 做字段 sync
    # v0.4.0(2026-05-28):加 H2 段反向同步
    # v0.4.0+ Step 3(2026-05-29)关键修:plan_skip 也维护 today_history 含今日
    # 场景:跨天未完成 task,5/28 已 today=true,5/29 跑 pull-today → plan_skip
    # 但 today_history 只有 [..., 5/28],缺 5/29 → 5/29 journal dataview 不显示
    # 修:history_diffs 在 Step 4.6 预计算,这里直接用
    for rid, title, p in plan_skip:
        has_field_diff = rid in field_diffs
        has_history_diff = rid in history_diffs

        # v0.6.0(2026-05-29):detail pull 先跑一次,看有无变化(纳入 skip 判断)
        det_res = _pull_details(rid, p)
        has_detail_change = bool(det_res and det_res.get("changed"))

        if not has_field_diff and not has_history_diff and not has_detail_change:
            continue  # 完全跳:today + today_history + 字段 + H2 段 + 明细都对齐

        updates = dict(field_diffs[rid]["updates"]) if has_field_diff else {}
        if has_history_diff:
            updates["today_history"] = history_diffs[rid]
        # frontmatter 更新
        fm_ok = True
        if updates:
            fm_ok = update_md_frontmatter(p, updates)
        if fm_ok:
            h2_changed = _apply_h2_updates(rid, p)
            fm_n = len(field_diffs[rid]['summary']) if has_field_diff else 0
            parts = []
            if has_history_diff:
                parts.append(f"today_history += {today_date_iso_for_history}")
            if fm_n:
                parts.append(f"{fm_n} 字段")
            if h2_changed:
                parts.append(f"{h2_changed} H2 段")
            if has_detail_change:
                parts.append(f"明细 +{det_res.get('added', 0)}/~{det_res.get('updated', 0)}")
            label = " + ".join(parts) if parts else "0(无变化)"
            print(f"  🔄 {p.name}: {label} sync(today 已对齐)")
            success_count += 1
            if fm_n or h2_changed or has_history_diff or has_detail_change:
                field_sync_count += 1
        else:
            print(f"  ❌ {p.name}: 字段 sync 失败")
            fail_count += 1

    for rid, p in plan_set_false:
        # v0.2.5 修:set today=false 时同步从 today_history remove 今日日期
        # 原因:journal dataview 用 `contains(today_history, this.file.day)` 判断渲染
        # 只 set today=false 而不 remove today_history → dataview 仍渲染 → unprick 不生效
        # 对称设计:plan_set_true append 今天 / plan_set_false remove 今天
        try:
            fm_cur, _, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
            history = fm_cur.get("today_history", []) if fm_cur else []
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []
        new_history = [d for d in history if str(d) != today_date_iso]
        history_changed = len(new_history) != len(history)
        base = {"today": False}
        if history_changed:
            base["today_history"] = new_history
        # v0.3.6: 对称清 today_source(不在今日 = 无来源标记)
        base["today_source"] = ""
        # v0.3.7: 合并飞书字段 diff
        final = _merge_with_field_diff(rid, base)
        field_changed = rid in field_diffs
        if update_md_frontmatter(p, final):
            # v0.4.0(2026-05-28):H2 段同步
            h2_changed = _apply_h2_updates(rid, p)
            # v0.6.0(2026-05-29):执行明细子表反向 sync(取消今日的 task 也保留历史明细)
            det_res = _pull_details(rid, p)
            suffix = f" (+ today_history -= {today_date_iso})" if history_changed else ""
            fm_n = len(field_diffs[rid]['summary']) if field_changed else 0
            extra_parts = []
            if fm_n:
                extra_parts.append(f"{fm_n} 字段 sync")
            if h2_changed:
                extra_parts.append(f"{h2_changed} H2 段 sync")
            if det_res and det_res.get("changed"):
                extra_parts.append(f"明细 +{det_res.get('added', 0)}/~{det_res.get('updated', 0)}")
            extra = (" + " + " + ".join(extra_parts)) if extra_parts else ""
            print(f"  ✅ {p.name}: today → false{suffix}{extra}")
            success_count += 1
            if field_changed or h2_changed or (det_res and det_res.get("changed")):
                field_sync_count += 1
        else:
            print(f"  ❌ {p.name}: 更新失败")
            fail_count += 1

    # ⚠️ v0.2.5 新增:自动建 task md(飞书有 OB 无)
    # v0.4.0(2026-05-28):传 ob_index 让新建 task md 的 parent_task 能反向找 wikilink
    if plan_missing:
        print(f"\n🆕 自动建 task md({len(plan_missing)} 条)...")
        for rid, title, row in plan_missing:
            created = _create_task_md_from_feishu_record(rid, row, fields_meta, config, vault_root, ob_index=ob_index)
            if created:
                print(f"  ✅ 建: {created.name}")
                created_count += 1
            else:
                print(f"  ⚠️ 跳过: {title[:55]}(可能已存在)")

    print(f"\n✅ pull-today 完成({success_count} 设 today / {created_count} 建新 task md / {field_sync_count} 字段 sync / {fail_count} 失败)")


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
    parser.add_argument("--vault", help="vault 根目录(给了就 chdir,避免外层用 `cd /OB && python3 ...`)")
    parser.add_argument("--apply", action="store_true", help="真写(默认 dry-run)")
    parser.add_argument("--pull", action="store_true", help="反向同步:从飞书拉到 OB(老:写 journal inline)")
    parser.add_argument("--pull-today", action="store_true",
                        help="2026-05-26 上线:飞书「是否今日」=true → OB task md frontmatter today=true(双向对齐)")
    parser.add_argument("--push-all-today", action="store_true",
                        help="v0.4.0+ Step 3(2026-05-28):反向方向 — 批量推 OB today=true task md 到飞书 forward")
    parser.add_argument("--pull-task",
                        help="v0.5.3(2026-05-29):单条拉 — 飞书 record → OB(类 git 单条粒度,不动其他 task)。参数:task md 路径 或 record_id")
    parser.add_argument("--migrate-today-history", action="store_true",
                        help="v0.4.0+ Step 3(2026-05-28)一次性 migration — 把 today_history unquoted 改 quoted(修 dataview 不显示 bug)")
    parser.add_argument("--migrate-today-history-unquote", action="store_true",
                        help="v0.4.0+ Step 3(2026-05-29)反向 migration — quoted 改回 unquoted(上次 quoted 方向错了)")
    parser.add_argument("--since", help="--pull 模式的起始日期(YYYY-MM-DD)")
    parser.add_argument("--only-completed", action="store_true",
                        help="只同步已完成 task ([x] / [-]),跳过未完成的")
    parser.add_argument("--task-md", help="task md 模式:单 task md 推送到飞书(CREATE/UPDATE)")
    parser.add_argument("--resolve-project",
                        help="给 userscript 用:解析 OB 项目名(如 '00 布丁')→ 输出 JSON(含 override 命中 / 一级 record_id / 二级子 records)")
    parser.add_argument("--quickadd-options", action="store_true",
                        help="v0.3.5 给 Cmd+P 快记任务用:一次性拉 大类/小类/最近5月/最近5周 → JSON")
    args = parser.parse_args()

    # --vault: 显式切到 vault 根目录,让所有相对路径(args.path / Path(".") / find_vault_root 的 cwd 起点)正确解析
    # 这样上层就可以写 `python3 /path/to/sync.py --vault /OB --pull-today`(命令开头是 python3,allowlist 友好)
    # 而不必写 `cd /OB && python3 ...`(cd 开头会绕过 Claude Code 的 allowlist 前缀匹配,引发 permission 风暴)
    if args.vault:
        vault_path = Path(args.vault).expanduser().resolve()
        if not (vault_path / ".obsidian").exists():
            print(f"❌ --vault {vault_path} 下未找到 .obsidian/ 目录,不像是 OB vault", file=sys.stderr)
            sys.exit(1)
        os.chdir(vault_path)
        # v0.3.2: 同步刷新 VAULT_ROOT,让 build_fields_payload / C 路径 backlinks 用对的 vault 根
        global VAULT_ROOT
        VAULT_ROOT = vault_path

    if args.resolve_project:
        # 静默模式:只输出 JSON,不打任何 progress 信息(给 userscript 解析)
        config = load_config()
        result = resolve_project_for_userscript(args.resolve_project, config)
        print(json.dumps(result, ensure_ascii=False))
        return

    if args.quickadd_options:
        # v0.3.5 静默模式:输出 JSON 给 userscript 解析(大类 / 小类 / 月 / 周)
        config = load_config()
        result = cmd_quickadd_options(config)
        print(json.dumps(result, ensure_ascii=False))
        return

    if args.migrate_today_history:
        migrate_today_history_quoted(apply=args.apply)
        return

    if args.migrate_today_history_unquote:
        migrate_today_history_unquoted(apply=args.apply)
        return

    if args.pull_today:
        pull_today_from_feishu(apply=args.apply)
    elif args.push_all_today:
        push_all_today_task_md(apply=args.apply)
    elif args.pull_task:
        pull_task_from_feishu(args.pull_task, apply=args.apply)
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
