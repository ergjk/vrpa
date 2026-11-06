"""`locate` 命令（M1-03）：定位单个界面元素，打印绝对坐标与匹配分数。"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from vrpa.errors import ElementNotVisible, ProfileMismatch, TreeConfigError

__all__ = ["run_locate"]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m wechat_agent locate",
        description="定位单个界面元素（M1-03/06）",
    )
    parser.add_argument("element_id", help="元素 id，如 input_box")
    parser.add_argument("--config", default=None, help="配置文件路径（默认 config.yaml）")
    parser.add_argument("--image", default=None, help="离线定位截图（PNG/JPG），不传则真实截屏")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    return parser.parse_args(list(argv))


def run_locate(argv: Sequence[str]) -> int:
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
        locator = build_locator(config, image=Path(args.image) if args.image else None)
        rect = locator.locate(args.element_id)
    except ElementNotVisible as exc:
        print(f"NOT FOUND: {exc}", file=sys.stderr)
        return 3
    except ProfileMismatch as exc:
        print(f"PROFILE MISMATCH: {exc}", file=sys.stderr)
        return 7
    except TreeConfigError as exc:
        print(f"LOCATE ERROR: {exc}", file=sys.stderr)
        return 3

    match = locator.last_match(args.element_id)
    payload = {
        "element": args.element_id,
        "rect": list(rect.as_tuple()),
        "score": round(match.score, 4) if match is not None else None,
        "scale": match.scale if match is not None else None,
        "profile": locator.profile_name(),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            f"[OK] {args.element_id} :: rect={rect.as_tuple()} score="
            f"{payload['score'] if payload['score'] is not None else '-'} profile={locator.profile_name()}"
        )
    return 0
