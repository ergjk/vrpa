"""M2-01 测试：顶层窗口与客户端矩形（FakeWindowBackend，无真实桌面）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from vrpa.errors import WindowNotForeground, WindowNotFound
from vrpa.ports import Rect
from vrpa.testing.fakes import FakeWindowBackend
from vrpa.vision.window import PywinautoWindowBackend, WindowInfo
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


class _FakeRect:
    def __init__(self) -> None:
        self.left, self.top, self.right, self.bottom = 10, 20, 810, 620


class _FakePwWindow:
    def __init__(self, title: str, hwnd: int = 123) -> None:
        self._title, self._hwnd = title, hwnd

    def window_text(self) -> str:
        return self._title

    def process_id(self) -> int:
        return 4

    def rectangle(self):
        return _FakeRect()

    @property
    def handle(self) -> int:
        return self._hwnd


class _FakeDesktop:
    def __init__(self, windows) -> None:
        self._windows = windows

    def windows(self, **_kwargs):
        return list(self._windows)


class _FallbackBackend(PywinautoWindowBackend):
    def __init__(self, mapping) -> None:
        super().__init__()
        self._mapping = mapping

    def _desktop_instance(self, backend="uia"):
        return self._mapping[backend]


def test_uia_empty_falls_back_to_win32() -> None:
    backend = _FallbackBackend({"uia": _FakeDesktop([]), "win32": _FakeDesktop([_FakePwWindow("微信")])})
    info = backend.find(title_regex="^微信$", process_names=())
    assert info is not None and info.title == "微信" and info.hwnd == 123


def test_both_backends_empty_returns_none() -> None:
    backend = _FallbackBackend({"uia": _FakeDesktop([]), "win32": _FakeDesktop([])})
    assert backend.find(title_regex="^微信$", process_names=()) is None


def test_foreground_process_name_without_hwnd(monkeypatch: pytest.MonkeyPatch) -> None:
    import win32gui

    window = WeChatWindow(CFG, FakeWindowBackend(INFO))
    monkeypatch.setattr(win32gui, "GetForegroundWindow", lambda: 0)
    assert window.foreground_process_name() is None


def test_foreground_process_name_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    fake_gui = types.ModuleType("win32gui")
    fake_gui.GetForegroundWindow = lambda: 123  # type: ignore[attr-defined]
    fake_gui.GetWindowThreadProcessId = lambda _hwnd: (1, 999)  # type: ignore[attr-defined]
    fake_vw = types.ModuleType("vrpa.vision.window")
    fake_vw._process_name = lambda _pid: "Weixin.exe"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "win32gui", fake_gui)
    monkeypatch.setitem(sys.modules, "vrpa.vision.window", fake_vw)
    window = WeChatWindow(CFG, FakeWindowBackend(INFO))
    assert window.foreground_process_name() == "Weixin.exe"
