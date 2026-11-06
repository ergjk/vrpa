"""`send` 命令（M6-01）：控制台接管发送，默认 dry_run；真实发送需显式授权。"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from vrpa.errors import AgentFrameworkError

__all__ = ["run_send"]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m wechat_agent send", description="控制台发送（默认 dry_run）")
    parser.add_argument("--config", default=None)
    parser.add_argument("--chat", required=True, help="目标会话")
    parser.add_argument("--text", required=True, help="发送内容")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(list(argv))


def run_send(argv: Sequence[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    from wechat_agent.act.executor import WeChatExecutor
    from wechat_agent.core.config import load_config

    config = load_config(args.config)
    executor = WeChatExecutor(config)
    try:
        outcome = executor.send(args.chat, args.text, trigger="console")
    except AgentFrameworkError as exc:
        print(f"SEND ERROR: {exc}", file=sys.stderr)
        return 5
    payload = {
        "ok": outcome.ok,
        "stage": outcome.stage,
        "chat": args.chat,
        "dry_run": executor.is_dry_run(),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"stage   : {outcome.stage}")
        print(f"dry_run : {executor.is_dry_run()}")
        print("RESULT: OK")
    return 0
