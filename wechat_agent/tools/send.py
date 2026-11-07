"""`send` 命令（M6-01）：控制台接管发送；默认 dry-run，真实发送需多重显式授权。"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import sys
import time
from collections.abc import Sequence

from vrpa.errors import AgentFrameworkError

__all__ = ["run_send"]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m wechat_agent send", description="控制台发送（默认 dry_run）")
    parser.add_argument("--config", default=None)
    parser.add_argument("--chat", required=True, help="目标会话")
    parser.add_argument("--text", required=True, help="发送内容")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--real", action="store_true", help="真实发送（需 dry_run=false + allow_real_send=true）")
    parser.add_argument("--i-understand-risk", action="store_true", help="真实发送风险确认（必须显式传入）")
    return parser.parse_args(list(argv))


def _print_refusal(reason: str) -> int:
    print(f"REAL SEND REFUSED: {reason}", file=sys.stderr)
    return 2


def _writeback(config: object, chat: str, text: str) -> int:
    from vrpa.memory.db import init_databases
    from vrpa.memory.history import HistoryStore
    from wechat_agent.memory.pipeline import MessagePipeline

    databases = init_databases(config.data_dir)  # type: ignore[attr-defined]
    try:
        return MessagePipeline(HistoryStore(databases)).writeback(chat, text)
    finally:
        databases.close()


def _run_real(args: argparse.Namespace, config: object) -> int:
    from vrpa.vision.driver import PyAutoGuiDriver
    from wechat_agent.act.executor import WeChatExecutor
    from wechat_agent.perception.capture import WeChatPerception
    from wechat_agent.perception.element_tree import WeChatElementTree
    from wechat_agent.perception.window import WeChatWindow

    if not args.i_understand_risk:
        return _print_refusal("真实发送必须显式传入 --i-understand-risk")
    if config.app.dry_run:  # type: ignore[attr-defined]
        return _print_refusal("config.app.dry_run=true；真实发送需先显式改为 false")
    if not config.safety.allow_real_send:  # type: ignore[attr-defined]
        return _print_refusal("config.safety.allow_real_send=false；真实发送总开关未开启")
    allowlist = tuple(config.safety.real_send_allowlist)  # type: ignore[attr-defined]
    if args.chat not in allowlist:
        return _print_refusal(f"会话 {args.chat!r} 不在 real_send_allowlist={list(allowlist)}")
    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        is_admin = False
    if not is_admin:
        return _print_refusal("真实发送需要管理员 PowerShell（否则鼠标/键盘注入会被系统丢弃）")

    tree = WeChatElementTree(config)  # type: ignore[arg-type]
    window = WeChatWindow(config)  # type: ignore[arg-type]
    driver = PyAutoGuiDriver()
    perception = WeChatPerception(config, tree=tree, driver=driver, window=window)  # type: ignore[arg-type]

    def _capture_after_send(session: str) -> str:
        last = ""
        for _ in range(3):
            with contextlib.suppress(Exception):
                perception.scroll_to_bottom()
            last = str(perception.capture(session))
            if args.text.strip() in last:
                return last
            time.sleep(0.8)
        return last

    executor = WeChatExecutor(
        config,  # type: ignore[arg-type]
        window=window,
        driver=driver,
        capture=_capture_after_send,
        tree=tree,
        allow_real_send=True,
    )
    try:
        perception.activate()
        perception.switch_session(args.chat)
        outcome = executor.send(args.chat, args.text, trigger="console")
        message_id = _writeback(config, args.chat, args.text)
    except AgentFrameworkError as exc:
        print(f"SEND ERROR: {exc}", file=sys.stderr)
        with contextlib.suppress(Exception):
            import cv2

            from vrpa.vision.screen import AutoScreenSource

            stamp = time.strftime("%Y%m%d_%H%M%S")
            path = f"data/reports/send_failed_{stamp}.png"
            cv2.imwrite(path, AutoScreenSource().capture())
            print(f"SEND DIAG: {path}", file=sys.stderr)
        return int(exc.exit_code)

    payload = {
        "ok": outcome.ok,
        "stage": outcome.stage,
        "chat": args.chat,
        "dry_run": False,
        "text_length": len(args.text),
        "message_id": message_id,
        "allowlist": list(allowlist),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"stage   : {outcome.stage}")
        print(f"target  : {args.chat}")
        print(f"message : {message_id}")
        print("RESULT: OK")
    return 0


def run_send(argv: Sequence[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    from wechat_agent.act.executor import WeChatExecutor
    from wechat_agent.core.config import load_config

    config = load_config(args.config)
    if args.real:
        return _run_real(args, config)

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
