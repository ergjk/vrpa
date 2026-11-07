"""`validate-tree` 命令（M1-05）：严格校验假 UIA 树 profile 与锚点图。

支持离线校验：``--image`` 指定一张与 profile 同分辨率的截图，
可在无微信/无桌面的 CI 环境中复现 validate-tree。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from vrpa.errors import ProfileMismatch, TreeConfigError
from vrpa.vision.locator import ValidationReport

__all__ = ["run_validate_tree"]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m wechat_agent validate-tree",
        description="校验假 UIA 树 profile 与锚点图（M1-05）",
    )
    parser.add_argument("--config", default=None, help="配置文件路径（默认 config.yaml）")
    parser.add_argument("--image", default=None, help="离线校验截图（PNG/JPG），不传则真实截屏")
    parser.add_argument("--strict", action="store_true", help="严格模式：锚点文件必须齐全")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--activate", action="store_true", help="真实校验前先激活微信窗口（真机推荐）")
    return parser.parse_args(list(argv))


def _report_lines(report: ValidationReport) -> list[str]:
    lines = [f"checked : {', '.join(report.checked) if report.checked else '-'}"]
    if report.ok:
        lines.append("RESULT: OK")
    else:
        lines.append(f"RESULT: FAIL ({len(report.problems)} 个问题)")
        for problem in report.problems:
            lines.append(f"  - {problem}")
    return lines


def run_validate_tree(argv: Sequence[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    if args.image is not None and not Path(args.image).is_file():
        print(f"截图不存在：{args.image}", file=sys.stderr)
        return 2

    from wechat_agent.core.config import load_config
    from wechat_agent.tools.vision import build_locator

    try:
        config = load_config(args.config)
        if args.activate and args.image is None:
            from wechat_agent.perception.window import WeChatWindow

            WeChatWindow(config).ensure_foreground()
        locator = build_locator(config, image=Path(args.image) if args.image else None)
        report = locator.validate(required_ids=locator.element_ids(), check_anchor_files=True)
    except ProfileMismatch as exc:
        print(f"PROFILE MISMATCH: {exc}", file=sys.stderr)
        return 7
    except TreeConfigError as exc:
        print(f"VALIDATE ERROR: {exc}", file=sys.stderr)
        return 3

    if args.json:
        print(
            json.dumps(
                {"ok": report.ok, "checked": list(report.checked), "problems": list(report.problems)},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print("\n".join(_report_lines(report)))
    return 0 if report.ok else 3
