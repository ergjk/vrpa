"""M2-06 红线 R3 静态/行为测试：消息流只走「框选 + Ctrl+C」剪贴板文本。

禁止在消息路径使用图像识别 / OCR / 模板匹配；解析器只接收文本。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from vrpa.ports import Rect
from vrpa.testing.fakes import FakeDriver, FakeElementTree, FakeWindowBackend
from vrpa.vision.window import WindowInfo
from wechat_agent.core.config import load_config
from wechat_agent.perception.capture import WeChatPerception
from wechat_agent.perception.window import WeChatWindow

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config(ROOT / "config.yaml")

MESSAGE_PATH_FILES = (
    "wechat_agent/perception/capture.py",
    "wechat_agent/perception/parser.py",
    "wechat_agent/tools/probe.py",
)
FORBIDDEN_IMPORTS = {
    "cv2",
    "pytesseract",
    "easyocr",
    "PIL",
    "vrpa.vision.matcher",
    "vrpa.vision.locator",
}


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


@pytest.mark.parametrize("relative", MESSAGE_PATH_FILES)
def test_message_path_has_no_image_recognition(relative: str) -> None:
    imports = _imports_of(ROOT / relative)
    forbidden = {module for module in imports if module in FORBIDDEN_IMPORTS}
    assert forbidden == set(), f"{relative} 引入了图像识别依赖：{forbidden}"


def test_capture_uses_clipboard_ctrl_c_only() -> None:
    source = (ROOT / "wechat_agent/perception/capture.py").read_text(encoding="utf-8")
    assert '"ctrl", "c"' in source
    for forbidden in ("screenshot", "imread", "matchTemplate", "OCR", "pytesseract"):
        assert forbidden not in source, f"capture.py 出现禁用能力：{forbidden}"


def test_parser_accepts_text_only() -> None:
    source = (ROOT / "wechat_agent/perception/parser.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    parse_method = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "parse":
            args = [arg.arg for arg in node.args.args]
            if "self" in args and "text" in args:
                parse_method = args
    assert parse_method is not None
    assert "image" not in parse_method and "screenshot" not in parse_method


def test_probe_never_writes_storage() -> None:
    source = (ROOT / "wechat_agent/tools/probe.py").read_text(encoding="utf-8")
    for forbidden in ("insert_messages", "writeback", "memory.db", "Database", "add_memory"):
        assert forbidden not in source, f"probe.py 不应写库：{forbidden}"


def test_capture_returns_plain_text_via_fakes() -> None:
    area = Rect(100, 200, 400, 300)
    info = WindowInfo(hwnd=3, title="微信", rect=Rect(0, 0, 800, 620), client_rect=Rect(0, 20, 800, 600))
    tree = FakeElementTree(element_rects={"message_area": area})
    driver = FakeDriver(scripted=("旧剪贴板", "张三: 你好"))
    perception = WeChatPerception(
        CFG,
        tree=tree,
        driver=driver,
        window=WeChatWindow(CFG, FakeWindowBackend(info)),
        sleep=lambda _s: None,
    )
    text = perception.capture("测试会话")
    assert isinstance(text, str)
    assert text == "张三: 你好"
    assert driver.drags and driver.hotkeys == [("ctrl", "c")]
