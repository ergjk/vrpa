"""M2-01 测试：顶层窗口与客户端矩形（FakeWindowBackend，无真实桌面）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from vrpa.errors import WindowNotForeground, WindowNotFound
from vrpa.ports import Rect
from vrpa.testing.fakes import FakeWindowBackend
from vrpa.vision.window import WindowInfo
from wechat_agent.core.config import load_config
from wechat_agent.perception.window import WeChatWindow

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config(ROOT / "config.yaml")

INFO = WindowInfo(
    hwnd=100,
    title="微信",
    rect=Rect(0, 0, 800, 620),
    client_rect=Rect(0, 20, 800, 600),
    process_name="WeChat.exe",
)


def test_find_window_and_client_rect() -> None:
    backend = FakeWindowBackend(INFO)
    window = WeChatWindow(CFG, backend)
    assert window.find() == INFO
    assert window.client_rect() == INFO.client_rect
    assert backend.find_calls[0][0] == CFG.wechat.window_title_regex
    assert backend.find_calls[0][1] == CFG.wechat.process_names


def test_window_not_found() -> None:
    window = WeChatWindow(CFG, FakeWindowBackend(None))
    with pytest.raises(WindowNotFound):
        window.find()


def test_ensure_foreground_activates() -> None:
    backend = FakeWindowBackend(INFO, foreground=False)
    window = WeChatWindow(CFG, backend)
    assert window.ensure_foreground() == INFO
    assert backend.activated == [INFO.hwnd]


def test_ensure_foreground_timeout() -> None:
    class StubbornBackend(FakeWindowBackend):
        def activate(self, hwnd: int) -> None:
            self.activated.append(hwnd)  # 不改变前台状态

    backend = StubbornBackend(INFO, foreground=False)
    window = WeChatWindow(CFG, backend, wait_timeout=0.2, sleep=lambda _seconds: None)
    with pytest.raises(WindowNotForeground):
        window.ensure_foreground()
    assert backend.activated
