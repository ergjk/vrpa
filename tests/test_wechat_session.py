"""M2-02 测试：会话切换 ensure_chat（FakeTree + FakeDriver，无真实键鼠）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from vrpa.errors import SessionSwitchFailed
from vrpa.ports import Rect
from vrpa.testing.fakes import FakeDriver, FakeElementTree, FakeWindowBackend
from vrpa.vision.window import WindowInfo
from wechat_agent.core.config import load_config
from wechat_agent.identity import ChatIdentity, IdentityMap
from wechat_agent.perception.session import WeChatSessionSwitcher
from wechat_agent.perception.window import WeChatWindow

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config(ROOT / "config.yaml")

SEARCH = Rect(100, 100, 200, 40)
TITLE = Rect(0, 60, 200, 30)
AREA = Rect(100, 200, 400, 300)
INFO = WindowInfo(hwnd=7, title="微信", rect=Rect(0, 0, 800, 620), client_rect=Rect(0, 20, 800, 600))


def _tree(*, with_title: bool = True, with_search: bool = True) -> FakeElementTree:
    rects: dict[str, Rect] = {"message_area": AREA}
    if with_search:
        rects["search_box"] = SEARCH
    if with_title:
        rects["chat_title"] = TITLE
    return FakeElementTree(element_rects=rects)


def test_ensure_chat_happy_path() -> None:
    tree = _tree()
    driver = FakeDriver(clipboard="原剪贴板", scripted=("原剪贴板",))
    window = WeChatWindow(CFG, FakeWindowBackend(INFO))
    switcher = WeChatSessionSwitcher(CFG, tree, driver, window=window, sleep=lambda _s: None)
    switcher.ensure_chat("测试会话")

    assert driver.clicks == [SEARCH.center]
    assert driver.hotkeys == [("ctrl", "a"), ("ctrl", "v"), ("enter",)]
    assert driver.clipboard_sets[0] == "测试会话"
    assert "原剪贴板" in driver.clipboard_sets
    assert tree.invalidated == 1


def test_ensure_chat_capture_verification() -> None:
    tree = _tree()
    driver = FakeDriver(scripted=("",))
    switcher = WeChatSessionSwitcher(
        CFG,
        tree,
        driver,
        capture=lambda _chat: "测试会话 的消息",
        sleep=lambda _s: None,
    )
    switcher.ensure_chat("测试会话")

    failing = WeChatSessionSwitcher(
        CFG,
        tree,
        FakeDriver(scripted=("",)),
        capture=lambda _chat: "别的会话",
        sleep=lambda _s: None,
    )
    with pytest.raises(SessionSwitchFailed, match="未包含会话名"):
        failing.ensure_chat("测试会话")


def test_ensure_chat_missing_search_box() -> None:
    switcher = WeChatSessionSwitcher(CFG, _tree(with_search=False), FakeDriver(), sleep=lambda _s: None)
    with pytest.raises(SessionSwitchFailed, match="search_box"):
        switcher.ensure_chat("测试会话")


def test_ensure_chat_missing_chat_title() -> None:
    switcher = WeChatSessionSwitcher(CFG, _tree(with_title=False), FakeDriver(scripted=("",)), sleep=lambda _s: None)
    with pytest.raises(SessionSwitchFailed, match="chat_title"):
        switcher.ensure_chat("测试会话")


def test_ensure_chat_rejects_empty_name() -> None:
    switcher = WeChatSessionSwitcher(CFG, _tree(), FakeDriver(), sleep=lambda _s: None)
    with pytest.raises(SessionSwitchFailed, match="不能为空"):
        switcher.ensure_chat("  ")


def test_ensure_chat_activates_window() -> None:
    backend = FakeWindowBackend(INFO, foreground=False)
    switcher = WeChatSessionSwitcher(
        CFG,
        _tree(),
        FakeDriver(scripted=("",)),
        window=WeChatWindow(CFG, backend),
        sleep=lambda _s: None,
    )
    switcher.ensure_chat("测试会话")
    assert backend.activated == [INFO.hwnd]


def test_capture_verification_with_identity_nickname() -> None:
    identity = IdentityMap(chats={"测试会话": ChatIdentity(nicknames=("三",))})
    switcher = WeChatSessionSwitcher(
        CFG,
        _tree(),
        FakeDriver(scripted=("",)),
        capture=lambda _chat: "三: 你好",
        sleep=lambda _s: None,
        identity=identity,
    )
    switcher.ensure_chat("测试会话")

    mismatch = WeChatSessionSwitcher(
        CFG,
        _tree(),
        FakeDriver(scripted=("",)),
        capture=lambda _chat: "别的昵称: 你好",
        sleep=lambda _s: None,
        identity=identity,
    )
    with pytest.raises(SessionSwitchFailed, match="已知昵称"):
        mismatch.ensure_chat("测试会话")
