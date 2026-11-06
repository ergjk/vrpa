"""M6-01 测试：发送三重校验（全 Fake，dry_run 绝不触碰键鼠）。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from vrpa.errors import VerifyFailed
from vrpa.ports import Rect
from vrpa.testing.fakes import FakeDriver, FakeWindowBackend
from vrpa.vision.window import WindowInfo
from wechat_agent.act.executor import WeChatExecutor
from wechat_agent.core.config import load_config
from wechat_agent.perception.window import WeChatWindow

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "config.yaml").read_text(encoding="utf-8")
CFG = load_config(ROOT / "config.yaml")
INFO = WindowInfo(hwnd=1, title="微信", rect=Rect(0, 0, 100, 100), client_rect=Rect(0, 0, 100, 90))


def _config(tmp_path: Path, *, dry_run: bool = True, sensitive: str = "[]"):
    text = BASE.replace("data_dir: ./data", f"data_dir: {tmp_path.as_posix()}/data", 1)
    text = text.replace("dry_run: true", f"dry_run: {'true' if dry_run else 'false'}", 1)
    text = re.sub(r"sensitive_words: \[.*?\]", f"sensitive_words: {sensitive}", text, count=1)
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return load_config(path)


def test_dry_run_never_touches_driver(tmp_path: Path) -> None:
    driver = FakeDriver()
    executor = WeChatExecutor(
        CFG,
        window=WeChatWindow(CFG, FakeWindowBackend(INFO)),
        driver=driver,
        capture=lambda _chat: "你好",
        allow_real_send=True,
    )
    outcome = executor.send("张三", "你好")
    assert outcome.ok and outcome.stage == "dry_run"
    assert driver.drags == [] and driver.hotkeys == [] and driver.clipboard_sets == []
    assert executor.is_dry_run() is True


def test_content_validation(tmp_path: Path) -> None:
    executor = WeChatExecutor(_config(tmp_path))
    with pytest.raises(VerifyFailed, match="内容为空"):
        executor.send("张三", "   ")
    with pytest.raises(VerifyFailed, match="超过上限"):
        executor.send("张三", "长" * (CFG.safety.max_reply_chars + 1))
    with pytest.raises(VerifyFailed, match="控制字符"):
        executor.send("张三", "a\x00b")


def test_sensitive_word_blocks(tmp_path: Path) -> None:
    executor = WeChatExecutor(_config(tmp_path, sensitive='["违禁词"]'))
    with pytest.raises(VerifyFailed, match="敏感词"):
        executor.send("张三", "这是违禁词内容")


def test_real_send_requires_explicit_authorization(tmp_path: Path) -> None:
    executor = WeChatExecutor(_config(tmp_path, dry_run=False))
    with pytest.raises(VerifyFailed, match="安全开关"):
        executor.send("张三", "你好")


def test_real_send_requires_dependencies(tmp_path: Path) -> None:
    executor = WeChatExecutor(_config(tmp_path, dry_run=False), allow_real_send=True)
    with pytest.raises(VerifyFailed, match="缺少"):
        executor.send("张三", "你好")


def test_real_send_three_checks_passed(tmp_path: Path) -> None:
    driver = FakeDriver()
    executor = WeChatExecutor(
        _config(tmp_path, dry_run=False),
        window=WeChatWindow(CFG, FakeWindowBackend(INFO, foreground=False)),
        driver=driver,
        capture=lambda _chat: "张三: 你好",
        allow_real_send=True,
        sleep=lambda _s: None,
    )
    outcome = executor.send("张三", "你好", trigger="console")
    assert outcome.ok and outcome.stage == "sent"
    assert driver.clipboard_sets == ["你好"]
    assert driver.hotkeys == [("ctrl", "v"), ("enter",)]
    assert executor.checks is not None and executor.checks.passed


def test_real_send_verify_failure(tmp_path: Path) -> None:
    executor = WeChatExecutor(
        _config(tmp_path, dry_run=False),
        window=WeChatWindow(CFG, FakeWindowBackend(INFO)),
        driver=FakeDriver(),
        capture=lambda _chat: "别的消息",
        allow_real_send=True,
        sleep=lambda _s: None,
    )
    with pytest.raises(VerifyFailed, match="回读校验失败"):
        executor.send("张三", "你好")
