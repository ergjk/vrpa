"""GUI 辅助函数测试（不打开窗口）。"""

from __future__ import annotations

import sys

from wechat_agent.tools.gui import (
    _build_dry_run_cmd,
    _build_live_cmd,
    _build_send_cmd,
    _parse_args,
    run_gui,
)


def test_build_commands_include_safety_flags() -> None:
    dry = _build_dry_run_cmd("王衢665", "config.yaml")
    assert dry[:3] == [sys.executable, "-m", "wechat_agent"]
    assert "--real" in dry and "--json" in dry
    send = _build_send_cmd("王衢665", "你好", "config.yaml")
    assert "--real" in send and "--i-understand-risk" in send
    live = _build_live_cmd("王衢665", "config.yaml")
    assert "--live" in live and "--max-sends" in live and "--i-understand-risk" in live


def test_parse_args_defaults() -> None:
    args = _parse_args([])
    assert args.chat == "王衢665" and args.config is None


def test_gui_help_does_not_open_window(capsys: object) -> None:
    assert run_gui(["--help"]) == 0
