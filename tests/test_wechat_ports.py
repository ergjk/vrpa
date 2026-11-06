"""M0-F-05 微信端口实现测试：双库 MemoryStore、ElementTree、Perception、Executor、Brain。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vrpa.errors import ElementNotVisible, LLMError, VerifyFailed
from vrpa.ports import IncomingMessage, MemoryItem, Rect
from wechat_agent.act.executor import WeChatExecutor
from wechat_agent.brain.client import WeChatBrain
from wechat_agent.core.config import Config, load_config
from wechat_agent.memory.store import WeChatMemoryStore, content_hash, normalize_text
from wechat_agent.perception.capture import WeChatPerception
from wechat_agent.perception.element_tree import ELEMENT_IDS, WeChatElementTree

ROOT = Path(__file__).resolve().parents[1]
BASE_TEXT = (ROOT / "config.yaml").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clean_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


def _config(tmp_path: Path, *, dry_run: bool = True) -> Config:
    text = BASE_TEXT.replace("data_dir: ./data", f"data_dir: {tmp_path.as_posix()}/data", 1)
    if not dry_run:
        assert "dry_run: true" in text
        text = text.replace("dry_run: true", "dry_run: false", 1)
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return load_config(path)


def _write_profile(cfg: Config, *, complete: bool = True) -> Path:
    cfg.ensure_dirs()
    elements = {
        element_id: {"rect": [100 + index * 10, 200, 300, 400]}
        for index, element_id in enumerate(ELEMENT_IDS)
        if complete or element_id in {"main_window", "input_box"}
    }
    path = cfg.profile_path()
    path.write_text(json.dumps({"schema": 1, "elements": elements}), encoding="utf-8")
    return path


# ---------------------------------------------------------------- 记忆端口
def test_memory_store_roundtrip(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    store = WeChatMemoryStore(cfg)
    try:
        assert normalize_text("  你好\n 世界 ") == "你好 世界"
        assert len(content_hash("你好")) == 16

        inserted = store.insert_messages(
            "测试会话",
            [IncomingMessage(content="你好"), IncomingMessage(content="在吗", sender="张三")],
        )
        assert inserted == 2
        message_id = store.writeback("测试会话", "收到")
        assert message_id > 0

        hashes = store.recent_hashes("测试会话", 10)
        assert len(hashes) == 3
        assert all(len(value) == 16 for value in hashes)

        history = store.history("测试会话", 10)
        assert [message.content for message in history] == ["你好", "在吗", "收到"]
        assert history[-1].role == "assistant"
        assert history[0].sender is None

        memory_id = store.add_memory(MemoryItem(content="喜欢美式", category="preference", chat="测试会话", key="咖啡"))
        assert memory_id > 0
        updated_id = store.add_memory(
            MemoryItem(content="喜欢拿铁", category="preference", chat="测试会话", key="咖啡")
        )
        assert updated_id == memory_id

        recalled = store.recall("测试会话", "拿铁", 5)
        assert len(recalled) == 1 and recalled[0].content == "喜欢拿铁"

        assert store.forget(memory_id) is True
        assert store.recall("测试会话", "拿铁", 5) == ()
        assert store.forget(memory_id) is False
    finally:
        store.close()


# ---------------------------------------------------------------- 元素树
def test_element_tree_raises_without_profile(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    tree = WeChatElementTree(cfg)
    with pytest.raises(ElementNotVisible):
        tree.locate("input_box")
    assert tree.validate() is False
    assert tree.profile_name() == cfg.profile_name()
    assert "input_box" in tree.element_ids()


def test_element_tree_loads_and_caches_profile(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    _write_profile(cfg)
    tree = WeChatElementTree(cfg)
    first = tree.locate("input_box")
    assert isinstance(first, Rect)

    # 修改 profile 后缓存仍生效；invalidate 后重新加载
    path = cfg.profile_path()
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["elements"]["input_box"]["rect"] = [999, 888, 77, 66]
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert tree.locate("input_box") == first
    tree.invalidate()
    assert tree.locate("input_box") == Rect(999, 888, 77, 66)
    assert tree.validate() is True


def test_element_tree_validate_requires_all_elements(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    _write_profile(cfg, complete=False)
    tree = WeChatElementTree(cfg)
    assert tree.validate() is False
    with pytest.raises(ElementNotVisible):
        tree.locate("message_area")


# ---------------------------------------------------------------- 感知 / 执行 / 推理
def test_perception_requires_real_environment(tmp_path: Path) -> None:
    from vrpa.testing.fakes import FakeDriver, FakeElementTree, FakeWindowBackend
    from vrpa.vision.window import WindowInfo
    from wechat_agent.perception.window import WeChatWindow

    info = WindowInfo(hwnd=1, title="微信", rect=Rect(0, 0, 10, 10), client_rect=Rect(0, 0, 10, 10))
    cfg = _config(tmp_path)
    perception = WeChatPerception(
        cfg,
        tree=FakeElementTree(fail_locate=True),
        driver=FakeDriver(),
        window=WeChatWindow(cfg, FakeWindowBackend(info)),
    )
    with pytest.raises(ElementNotVisible):
        perception.capture("测试会话")


def test_executor_dry_run_and_live(tmp_path: Path) -> None:
    dry = WeChatExecutor(_config(tmp_path, dry_run=True))
    assert dry.is_dry_run() is True
    outcome = dry.send("测试会话", "你好")
    assert outcome.ok and outcome.stage == "dry_run"
    assert dry.clear_input() == ""

    live = WeChatExecutor(_config(tmp_path, dry_run=False))
    assert live.is_dry_run() is False
    with pytest.raises(VerifyFailed):
        live.send("测试会话", "你好")


def test_brain_requires_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config(tmp_path)
    brain = WeChatBrain(cfg)
    with pytest.raises(LLMError):
        brain.ping()
    with pytest.raises(LLMError):
        brain.generate([{"role": "user", "content": "hi"}])

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-1234567890")
    assert brain.ping() == 0.0
