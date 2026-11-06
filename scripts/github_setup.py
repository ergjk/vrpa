"""一次配置 GitHub 仓库 About/Topics 与标签（需已 gh auth login）。

用法：
    python scripts/github_setup.py --dry-run
    python scripts/github_setup.py
    python scripts/github_setup.py --gh data/tools/gh/bin/gh.exe
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "ergjk/vrpa"
DESCRIPTION = (
    "微信 PC 4.x 拟人化 RPA Agent（vrpa 框架）：框选+剪贴板采集、去重、LLM 回复、"
    "三重校验与 dry_run 安全执行；默认不真实发送。"
)
TOPICS = [
    "wechat",
    "wechat-bot",
    "wechat4",
    "rpa",
    "desktop-automation",
    "pywinauto",
    "pyautogui",
    "llm",
    "deepseek",
    "chatbot",
    "agent",
    "python",
    "windows",
    "dry-run",
    "human-in-the-loop",
]


def _find_gh(explicit: str | None) -> str:
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return str(path)
        raise SystemExit(f"gh 不存在：{explicit}")
    candidate = ROOT / "data" / "tools" / "gh" / "bin" / "gh.exe"
    if candidate.is_file():
        return str(candidate)
    return "gh"


def _run(gh: str, args: list[str], *, dry_run: bool) -> subprocess.CompletedProcess[str] | None:
    command = [gh, *args]
    if dry_run:
        print("DRY-RUN:", " ".join(command))
        return None
    return subprocess.run(command, check=True, text=True, capture_output=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="配置 GitHub About/Topics 与 labels")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--gh", default=None, help="gh.exe 路径（默认仓库内便携版）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    gh = _find_gh(args.gh)
    print(f"repo : {args.repo}")
    print(f"gh   : {gh}")
    print(f"desc : {DESCRIPTION}")

    edit = [gh, "repo", "edit", args.repo, "--description", DESCRIPTION]
    for topic in TOPICS:
        edit += ["--add-topic", topic]
    _run(gh, edit[1:], dry_run=args.dry_run)

    labels_path = ROOT / ".github" / "labels.yml"
    labels = yaml.safe_load(labels_path.read_text(encoding="utf-8"))
    if not isinstance(labels, list):
        raise SystemExit(".github/labels.yml 必须是标签数组")
    existing: set[str] = set()
    if not args.dry_run:
        listed = _run(
            gh,
            ["label", "list", "--repo", args.repo, "--limit", "100", "--json", "name"],
            dry_run=False,
        )
        if listed is not None and listed.stdout.strip():
            existing = {str(item["name"]) for item in json.loads(listed.stdout)}
    for item in labels:
        name = str(item["name"])
        color = str(item["color"])
        description = str(item.get("description", ""))
        if name in existing:
            label_args = ["label", "edit", name, "--color", color, "--description", description]
        else:
            label_args = ["label", "create", name, "--color", color, "--description", description]
        label_args += ["--repo", args.repo]
        _run(gh, label_args, dry_run=args.dry_run)
    print(f"topics : {len(TOPICS)} 个")
    print(f"labels : {len(labels)} 个")

    if not args.dry_run:
        result = _run(
            gh,
            ["repo", "view", args.repo, "--json", "description,repositoryTopics"],
            dry_run=False,
        )
        if result is not None and result.stdout.strip():
            try:
                print("verify :", json.dumps(json.loads(result.stdout), ensure_ascii=False))
            except json.JSONDecodeError:
                print("verify : 输出非 JSON，跳过")
        else:
            print("verify : gh 未返回 JSON，跳过（可用 gh repo view 手动核对）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
