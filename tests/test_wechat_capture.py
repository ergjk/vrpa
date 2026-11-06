"""M2-03 测试：框选 + Ctrl+C 采集（FakeTree/FakeDriver/ FakeWindow，无真实键鼠）。"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from vrpa.errors import CopyFailed, ElementNotVisible, WindowNotForeground
from vrpa.ports import Rect
from vrpa.testing.fakes import FakeDriver, FakeElementTree, FakeWindowBackend
from vrpa.vision.window import WindowInfo
from wechat_agent.core.config import load_config
from wechat_agent.perception.capture import (
    WeChatPerception,
    _sample_end_hold,
    _start_outside_bubble,
)
from wechat_agent.perception.window import WeChatWindow

ROOT = Path(__file__).resolve().parents[1]
BASE_TEXT = (ROOT / "config.yaml").read_text(encoding="utf-8")
CFG = load_config(ROOT / "config.yaml")

AREA = Rect(100, 200, 400, 300)
INFO = WindowInfo(hwnd=9, title="微信", rect=Rect(0, 0, 800, 620), client_rect=Rect(0, 20, 800, 600))
CAPTURED = "张三: 你好\n李四: 在吗"


def _config(tmp_path: Path, *, restore: bool = True):
    text = BASE_TEXT.replace("data_dir: ./data", f"data_dir: {tmp_path.as_posix()}/data", 1)
    if not restore:
        text = text.replace("restore_clipboard: true", "restore_clipboard: false", 1)
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return load_config(path)


def _perception(
    *,
    restore: bool = True,
    scripted: tuple[str, ...] = ("旧剪贴板", CAPTURED),
    area: Rect | None = AREA,
    foreground: bool = True,
    tmp_path: Path,
):
    cfg = _config(tmp_path, restore=restore)
    rects = {"message_area": area or AREA, "search_box": Rect(0, 0, 10, 10), "chat_title": Rect(0, 0, 5, 5)}
    tree = FakeElementTree(element_rects=rects)
    driver = FakeDriver(scripted=scripted)
    backend = FakeWindowBackend(INFO, foreground=foreground)
    window = WeChatWindow(cfg, backend)
    perception = WeChatPerception(cfg, tree=tree, driver=driver, window=window, sleep=lambda _s: None)
    return perception, driver, backend


def test_capture_returns_clipboard_text(tmp_path: Path) -> None:
    perception, driver, _ = _perception(tmp_path=tmp_path)
    text = perception.capture("测试会话")
    assert isinstance(text, str) and text == CAPTURED

    drag_cfg = perception._config.capture.drag
    expected_start = (
        AREA.x + int(round(AREA.width * drag_cfg.from_x)),
        AREA.y + int(round(AREA.height * drag_cfg.from_y)),
    )
    expected_end = (
        AREA.x + int(round(AREA.width * drag_cfg.to_x)),
        AREA.y + int(round(AREA.height * drag_cfg.to_y)),
    )
    assert driver.drags == [(expected_start, expected_end, drag_cfg.steps, drag_cfg.duration)]
    assert driver.hotkeys == [("ctrl", "c")]
    # 剪贴板已恢复
    assert driver.clipboard_sets[-1] == "旧剪贴板"


def test_capture_without_restore(tmp_path: Path) -> None:
    perception, driver, _ = _perception(tmp_path=tmp_path, restore=False, scripted=(CAPTURED,))
    assert perception.capture("测试会话") == CAPTURED
    # 即使不恢复旧剪贴板，也会先写入防伪哨兵
    assert len(driver.clipboard_sets) == 1 and driver.clipboard_sets[0].startswith("__vrpa_clipboard_")


def test_capture_empty_clipboard_raises(tmp_path: Path) -> None:
    perception, _, _ = _perception(tmp_path=tmp_path, scripted=("旧剪贴板", "   "))
    with pytest.raises(CopyFailed, match="剪贴板为空"):
        perception.capture("测试会话")


def test_capture_missing_message_area(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    tree = FakeElementTree(element_rects={"search_box": Rect(0, 0, 10, 10)})
    perception = WeChatPerception(
        cfg,
        tree=tree,
        driver=FakeDriver(),
        window=WeChatWindow(cfg, FakeWindowBackend(INFO)),
        sleep=lambda _s: None,
    )
    with pytest.raises(ElementNotVisible, match="消息区"):
        perception.capture("测试会话")


def test_capture_activates_window(tmp_path: Path) -> None:
    perception, _, backend = _perception(tmp_path=tmp_path, foreground=False)
    perception.capture("测试会话")
    assert backend.activated == [INFO.hwnd]


def test_activate_and_switch_session(tmp_path: Path) -> None:
    perception, driver, _ = _perception(tmp_path=tmp_path, scripted=("旧剪贴板", "测试会话: 你好"))
    perception.activate()
    perception.switch_session("测试会话")
    assert ("ctrl", "v") in driver.hotkeys
    assert driver.clipboard_sets[0] == "测试会话"


def test_switch_session_failure_when_foreground_fails(tmp_path: Path) -> None:
    class Stubborn(FakeWindowBackend):
        def activate(self, hwnd: int) -> None:
            self.activated.append(hwnd)

    cfg = _config(tmp_path)
    backend = Stubborn(INFO, foreground=False)
    perception = WeChatPerception(
        cfg,
        tree=FakeElementTree(element_rects={"search_box": Rect(0, 0, 10, 10)}),
        driver=FakeDriver(),
        window=WeChatWindow(cfg, backend, wait_timeout=0.2, sleep=lambda _s: None),
        sleep=lambda _s: None,
    )
    with pytest.raises(WindowNotForeground):
        perception.switch_session("测试会话")


def test_end_hold_at_least_two_seconds() -> None:
    for _ in range(50):
        value = _sample_end_hold()
        assert 2.0 <= value <= 3.1


def test_multi_end_hold_longer() -> None:
    for _ in range(50):
        value = _sample_end_hold(multi=True)
        assert 2.8 <= value <= 5.2


def test_capture_retries_after_scroll_to_bottom(tmp_path: Path) -> None:
    perception, driver, _ = _perception(tmp_path=tmp_path, scripted=("旧剪贴板", "", CAPTURED))
    assert perception.capture("测试会话") == CAPTURED
    assert len(driver.drags) == 2
    assert len(driver.scrolls) == 1
    assert driver.scrolls[0][2] > 0  # 真机实测：正值向消息列表底部滚动


def test_multi_mode_prescrolls_bottom(tmp_path: Path) -> None:
    text = BASE_TEXT.replace("from: {x: 0.94, y: 0.14}", "from: {x: 0.08, y: 0.98}")
    text = text.replace("to: {x: 0.06, y: 0.92}", "to: {x: 0.90, y: 0.00}")
    text = text.replace("data_dir: ./data", f"data_dir: {tmp_path.as_posix()}/data", 1)
    path = tmp_path / "multi.yaml"
    path.write_text(text, encoding="utf-8")
    cfg = load_config(path)
    tree = FakeElementTree(element_rects={"message_area": AREA})
    driver = FakeDriver(scripted=("旧剪贴板", CAPTURED))
    perception = WeChatPerception(
        cfg,
        tree=tree,
        driver=driver,
        window=WeChatWindow(cfg, FakeWindowBackend(INFO)),
        sleep=lambda _s: None,
    )
    assert perception.capture("测试会话") == CAPTURED
    assert driver.scrolls and driver.scrolls[0][2] > 0  # 向下滚到底部
    assert driver.drags


def test_capture_uses_drag_start_area(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    drag = dataclasses.replace(cfg.capture.drag, from_x=0.02, from_y=0.01, to_x=0.95, to_y=1.03)
    cfg = dataclasses.replace(cfg, capture=dataclasses.replace(cfg.capture, drag=drag))
    start_area = Rect(220, 100, 120, 40)
    tree = FakeElementTree(
        element_rects={
            "message_area": AREA,
            "search_box": Rect(0, 0, 10, 10),
            "chat_title": Rect(0, 0, 5, 5),
            "drag_start_area": start_area,
        }
    )
    driver = FakeDriver(scripted=("旧剪贴板", CAPTURED))
    perception = WeChatPerception(
        cfg,
        tree=tree,
        driver=driver,
        window=WeChatWindow(cfg, FakeWindowBackend(INFO)),
        sleep=lambda _s: None,
    )
    assert perception.capture("测试会话") == CAPTURED
    assert driver.drags[0][0] == (start_area.center[0], start_area.y + 2)
    assert perception.last_capture_info["start_source"] == "drag_start_area"


def test_start_outside_bubble_uses_right_strip() -> None:
    text = Rect(100, 200, 400, 300)
    assert _start_outside_bubble(text, Rect(100, 200, 100, 300)) == (350, 202)
    # 气泡-头像区覆盖整个文本框区 -> 无补集
    assert _start_outside_bubble(text, Rect(100, 200, 400, 300)) is None


def test_capture_uses_bubble_avatar_complement(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    drag = dataclasses.replace(cfg.capture.drag, from_x=0.02, from_y=0.01, to_x=0.95, to_y=1.03)
    cfg = dataclasses.replace(cfg, capture=dataclasses.replace(cfg.capture, drag=drag))
    tree = FakeElementTree(
        element_rects={
            "message_area": AREA,
            "search_box": Rect(0, 0, 10, 10),
            "chat_title": Rect(0, 0, 5, 5),
            "bubble_avatar_area": Rect(AREA.x, AREA.y, 100, AREA.height),
        }
    )
    driver = FakeDriver(scripted=("旧剪贴板", CAPTURED))
    perception = WeChatPerception(
        cfg,
        tree=tree,
        driver=driver,
        window=WeChatWindow(cfg, FakeWindowBackend(INFO)),
        sleep=lambda _s: None,
    )
    assert perception.capture("测试会话") == CAPTURED
    assert driver.drags[0][0] == (AREA.x + 100 + (AREA.width - 100) // 2, AREA.y + 2)
    assert perception.last_capture_info["start_source"] == "message_area-bubble_avatar_area"
