#!/usr/bin/env python3
"""auto_collect_today.py — 自动统计今日工作的数据采集层(场景 ③ Step 1)

输出 JSON 结构化数据给 Claudian 读,**只采集不归纳**(归纳由 LLM 做)。

用法:
    python3 auto_collect_today.py              # 北京时间今天
    python3 auto_collect_today.py 2026-05-25   # 指定日期(YYYY-MM-DD)

输出 JSON 结构:
    {
        "date": "2026-05-26",
        "git_commits": [
            {"repo": "zhixing-game", "hash": "abc1234", "message": "...", "timestamp": "..."}, ...
        ],
        "vault_modified_files": [
            {"path": "01 Project/...", "mtime": "...", "size_kb": 12.3}, ...
        ],
        "today_journal_path": "journals/2026-05-26.md",
        "today_journal_exists": true,
        "week_report_path": "journals/周报/2026年第22 周（5月 25 日-5 月 31 日）.md",
        "week_report_exists": true
    }

参考 rules/feishu-project-sync.md「场景 ③ 自动统计今日工作 SOP」。
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


# 用户工程仓库列表(可扩展)
GIT_REPOS = [
    "/Users/aim5/Documents/CodingProject/zhixing-game",
    "/Users/aim5/Documents/CodingProject/feishukanban-ob-sync",
    "/Users/aim5/Documents/CodingProject/tools/macmini-nas",
    # OB 自身(obsidian-git auto-commit)
    "/Users/aim5/Documents/OB",
]

VAULT_ROOT = Path("/Users/aim5/Documents/OB")

# vault 内文件扫描时跳过的目录(噪音)
# 注意:.claude/rules/ 不跳过 — rules 改动是工作产出(SOP 升级 / 事故记录)
# 注意:.agents 也不跳过 — Codex CLI 配置改动是工作产出
SKIP_DIRS = {
    ".obsidian/workspace",  # 仅跳 workspace 状态(不跳整个 .obsidian — 但插件 data.json 改动算工作)
    ".git", ".trash",
    "journals",  # journal 文件自身不算"工作产出"(journal 改动靠 today journal 本身体现)
    "04 Inbox/cubox", "04 Inbox/Clippings",  # 第三方导入,不算工作
    "03 Resources/素材库/微信读书同步",  # 同步,不算
    ".obsidian.bak", ".obsidian.bak-",  # 备份
}


def get_beijing_today() -> str:
    """北京时间今天的 YYYY-MM-DD"""
    bj = datetime.utcnow() + timedelta(hours=8)
    return bj.strftime("%Y-%m-%d")


def collect_git_commits(date_str: str) -> list:
    """从所有项目仓库扫今日 commit"""
    commits = []
    # date_str 是北京日期,但 git log --since 用本地时间(可能 PDT)
    # 走"今天 0 点北京 = 昨天 16 点 PDT"的换算 → 直接用 git log --since=midnight 不准
    # 简化:用 "1 day ago" 拉最近 24h,然后用 commit timestamp 过滤
    since = f"1 day ago"

    for repo_path in GIT_REPOS:
        repo = Path(repo_path)
        if not repo.exists():
            continue
        try:
            # 拉最近 24h commit(本地用户 author),只取 short hash + subject + iso date
            result = subprocess.run(
                ["git", "-C", str(repo), "log",
                 f"--since={since}",
                 "--pretty=format:%h|%s|%aI",
                 "--no-merges"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode != 0:
                continue
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|", 2)
                if len(parts) != 3:
                    continue
                hash_, msg, ts = parts
                # 过滤:commit 日期(ISO 8601)的日期部分必须是目标日期(按北京时区)
                # ts 如 "2026-05-26T10:30:00+08:00"
                # 简化:按 ts 前 10 位字符串比较(假设 ts 是北京时区或转过)
                # 实际:不同仓库的 commit timezone 不一定一致,但通常作者 commit 用本地时区
                # 如果 ts 含 +08:00,前 10 位就是北京日期;含 -07:00,前 10 位是 PDT 日期需调
                ts_date = ts[:10]
                # 简化对齐:用 ts 第一个 10 位 = 目标日期 OR 目标日期前一天(跨时区缓冲)
                yesterday_str = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
                if ts_date not in (date_str, yesterday_str):
                    continue
                commits.append({
                    "repo": repo.name,
                    "hash": hash_,
                    "message": msg,
                    "timestamp": ts,
                })
        except subprocess.TimeoutExpired:
            continue
        except Exception as e:
            print(f"⚠️ git log 失败 ({repo}): {e}", file=sys.stderr)
    return commits


def collect_vault_modified_files(date_str: str) -> list:
    """扫 vault 内今日 mtime 改的 .md 文件"""
    files = []
    target_dt = datetime.strptime(date_str, "%Y-%m-%d")
    # 北京日期 00:00 = UTC 前一天 16:00 = Mac PDT 前一天 09:00(若 PDT = UTC-7)
    # 简化:用本地系统时区的 0:00 ~ 23:59 当作"今天",可能差几小时但能用
    day_start = target_dt.timestamp()
    day_end = day_start + 86400

    # 扩展扫描扩展名:不只 .md,还包括 .py/.js/.css/.json/.yaml/.sh 等代码 + 配置
    # 但跳过二进制类(.png/.jpg/.mp4 等)
    SCAN_EXTS = {".md", ".py", ".js", ".css", ".json", ".yaml", ".yml", ".sh", ".ts", ".tsx", ".html"}

    # 改用 white-list:特定隐藏目录跳过(.git / .trash / .obsidian.bak/),其余隐藏目录保留(.claude / .agents 是工作产出)
    HIDDEN_SKIP = {".git", ".trash", ".obsidian.bak"}
    for md_path in VAULT_ROOT.rglob("*"):
        if md_path.suffix.lower() not in SCAN_EXTS:
            continue
        if not md_path.is_file():
            continue
        rel_path = md_path.relative_to(VAULT_ROOT)
        rel_str = str(rel_path)
        parts = rel_path.parts
        skip = False
        # 隐藏目录(. 开头)— 只跳 HIDDEN_SKIP 里的,其他 .claude / .agents 保留
        for p in parts:
            if p.startswith(".") and p in HIDDEN_SKIP:
                skip = True
                break
        if skip:
            continue
        # .obsidian/* 排除部分 system 文件(workspace 状态等)— 但 settings.json / plugins 配置改动算工作
        if parts[0] == ".obsidian":
            EXCLUDE_OBSIDIAN_FILES = {
                "workspace.json", "workspace-mobile.json",
                "workspaces.json", "graph.json",
                "core-plugins.json",  # auto-generated
            }
            if len(parts) >= 2 and parts[-1] in EXCLUDE_OBSIDIAN_FILES:
                continue
        # SKIP_DIRS 子串匹配
        for skip_pattern in SKIP_DIRS:
            if skip_pattern in rel_str:
                skip = True
                break
        if skip:
            continue

        try:
            stat = md_path.stat()
            mtime = stat.st_mtime
            if day_start <= mtime < day_end:
                files.append({
                    "path": str(md_path.relative_to(VAULT_ROOT)),
                    "mtime": datetime.fromtimestamp(mtime).isoformat(timespec="seconds"),
                    "size_kb": round(stat.st_size / 1024, 1),
                })
        except Exception:
            continue

    # 按 mtime 倒序(最新 → 最旧)
    files.sort(key=lambda x: x["mtime"], reverse=True)
    return files


def find_week_report(date_str: str) -> tuple:
    """找本周周报文件(by ISO week)"""
    target_dt = datetime.strptime(date_str, "%Y-%m-%d")
    iso_year, iso_week, _ = target_dt.isocalendar()
    # 周报命名格式参考:`journals/周报/2026年第22 周（5月 25 日-5 月 31 日）.md`
    week_dir = VAULT_ROOT / "journals" / "周报"
    if not week_dir.exists():
        return None, False
    for md_path in week_dir.rglob("*.md"):
        name = md_path.name
        if f"{iso_year}年第{iso_week} 周" in name or f"{iso_year} 年第{iso_week} 周" in name:
            return str(md_path.relative_to(VAULT_ROOT)), True
    return None, False


def main():
    # 解析参数
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            print(f"❌ 日期格式错: {date_str},应为 YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)
    else:
        date_str = get_beijing_today()

    print(f"# 采集 {date_str} 工作数据...", file=sys.stderr)

    git_commits = collect_git_commits(date_str)
    vault_files = collect_vault_modified_files(date_str)
    today_journal = f"journals/{date_str}.md"
    today_journal_exists = (VAULT_ROOT / today_journal).exists()
    week_report, week_report_exists = find_week_report(date_str)

    output = {
        "date": date_str,
        "git_commits": git_commits,
        "git_commits_count": len(git_commits),
        "vault_modified_files": vault_files,
        "vault_modified_count": len(vault_files),
        "today_journal_path": today_journal,
        "today_journal_exists": today_journal_exists,
        "week_report_path": week_report,
        "week_report_exists": week_report_exists,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))

    print(
        f"\n# 摘要(stderr): {len(git_commits)} commits / "
        f"{len(vault_files)} files modified / "
        f"today_journal: {'✅' if today_journal_exists else '❌'} / "
        f"week_report: {'✅' if week_report_exists else '❌'}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
