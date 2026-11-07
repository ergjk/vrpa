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
    parser.add_argument("--rehearse", action="store_true", help="只粘贴到输入框并截图，不按 Enter")
    parser.add_argument("--manual-focus", action="store_true", help="演练：倒计时内手动点击输入框，不再程序点击")
    parser.add_argument("--warmup", type=float, default=5.0, help="演练倒计时秒数")
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
    perception = WeChatPerception(
        config,  # type: ignore[arg-type]
        tree=tree,
        driver=driver,
        window=window,
        verify_session_capture=False,
    )

    if args.rehearse and args.manual_focus:
        import cv2

        from vrpa.vision.screen import AutoScreenSource

        wait = max(0.0, float(args.warmup))
        print(f"请 {wait:.0f} 秒内手动点击微信输入框并保持焦点……", file=sys.stderr)
        while wait > 0:
            time.sleep(min(1.0, wait))
            wait -= 1.0
        try:
            rect = tree.locate("input_box_area")
        except Exception:
            rect = tree.locate("input_box")
        driver.clipboard_set(args.text)
        driver.hotkey("ctrl", "v")
        time.sleep(0.6)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = f"data/reports/send_manual_focus_{stamp}.png"
        cv2.imwrite(path, AutoScreenSource().capture())
        driver.clipboard_set("__vrpa_input_check__")
        driver.hotkey("ctrl", "a")
        driver.hotkey("ctrl", "c")
        time.sleep(0.2)
        observed = str(driver.clipboard_get())
        driver.hotkey("ctrl", "a")
        driver.hotkey("delete")
        payload = {
            "ok": True,
            "stage": "manual_focus_rehearsal",
            "input_box": rect.as_tuple(),
            "paste_ok": observed.strip() == args.text.strip(),
            "diagnostic": path,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else f"MANUAL FOCUS: {payload}")
        return 0

    if args.rehearse:
        import cv2

        from vrpa.vision.screen import AutoScreenSource

        perception.activate()
        perception.switch_session(args.chat)
        try:
            rect = tree.locate("input_box_area")
        except Exception:
            rect = tree.locate("input_box")
        x, y, w, h = rect.x, rect.y, rect.width, rect.height
        points = {
            "center": (x + w // 2, y + h // 2),
            "top_left": (x + 30, y + 20),
            "left_mid": (x + 30, y + h // 2),
            "bottom_mid": (x + w // 2, y + h - 15),
        }
        stamp = time.strftime("%Y%m%d_%H%M%S")
        results: dict[str, bool] = {}
        shots: dict[str, str] = {}

        def read_input() -> str:
            driver.clipboard_set("__vrpa_input_check__")
            driver.hotkey("ctrl", "a")
            driver.hotkey("ctrl", "c")
            time.sleep(0.2)
            return str(driver.clipboard_get())

        def clear_input() -> None:
            driver.hotkey("ctrl", "a")
            driver.hotkey("delete")

        # 首选方案：不点击、直接粘贴（验证默认聚焦）
        driver.hotkey("ctrl", "a")
        driver.hotkey("delete")
        driver.clipboard_set(args.text)
        driver.hotkey("ctrl", "v")
        time.sleep(0.5)
        direct_shot = f"data/reports/send_rehearsal_{stamp}_direct.png"
        cv2.imwrite(direct_shot, AutoScreenSource().capture())
        results["direct_paste"] = read_input().strip() == args.text.strip()
        shots["direct"] = direct_shot
        driver.hotkey("ctrl", "a")
        driver.hotkey("delete")

        for name, point in points.items():
            driver.click(*point)
            time.sleep(0.3)
            clear_input()
            driver.clipboard_set(args.text)
            driver.hotkey("ctrl", "v")
            time.sleep(0.5)
            shot = f"data/reports/send_rehearsal_{stamp}_{name}.png"
            cv2.imwrite(shot, AutoScreenSource().capture())
            shots[name] = shot
            results[name] = read_input().strip() == args.text.strip()
            clear_input()

        # ASCII 键盘输入对照（不依赖剪贴板）
        driver.click(*points["center"])
        time.sleep(0.3)
        clear_input()
        driver.type_text("VRPA_TEST_123")
        time.sleep(0.4)
        ascii_shot = f"data/reports/send_rehearsal_{stamp}_ascii.png"
        cv2.imwrite(ascii_shot, AutoScreenSource().capture())
        results["ascii_write"] = read_input().strip() == "VRPA_TEST_123"
        clear_input()

        payload = {
            "ok": True,
            "stage": "rehearsal",
            "chat": args.chat,
            "results": results,
            "diagnostics": shots | {"ascii": ascii_shot},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else f"REHEARSAL: {results}")
        return 0

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
        if args.manual_focus:
            wait = max(0.0, float(args.warmup))
            print(f"请 {wait:.0f} 秒内手动点击微信输入框并保持焦点……", file=sys.stderr)
            while wait > 0:
                time.sleep(min(1.0, wait))
                wait -= 1.0
        outcome = executor.send(args.chat, args.text, trigger="console", click_input=not args.manual_focus)
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
        "manual_focus": bool(args.manual_focus),
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
    if args.rehearse and not args.real:
        print("REHEARSAL REFUSED: --rehearse 必须与 --real 一起使用（演练不会发送）", file=sys.stderr)
        return 2
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
