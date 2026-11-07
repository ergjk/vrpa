"""M5 集成测试：真实 Brain（FakeTransport，零真实 API）。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from vrpa.errors import LLMError
from vrpa.llm.client import LLMClient
from vrpa.memory.store import SQLiteMemoryStore
from vrpa.ports import IncomingMessage, MemoryItem
from wechat_agent.brain.client import WeChatBrain
from wechat_agent.core.config import load_config
from wechat_agent.identity import ChatIdentity, IdentityMap

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config(ROOT / "config.yaml")


class FakeTransport:
    def __init__(self, content: str = "你好呀", *, status: int = 200) -> None:
        self.calls: list[dict[str, Any]] = []
        self._content = content
        self._status = status

    def request(self, method, url, *, headers, payload, timeout):
        self.calls.append({"method": method, "url": url, "payload": payload})
        return self._status, {
            "model": "fake-model",
            "choices": [{"message": {"role": "assistant", "content": self._content}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
        }


def _brain(transport: FakeTransport, memory=None, identity=None) -> WeChatBrain:
    client = LLMClient(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="fake-model",
        transport=transport,
        sleep=lambda _s: None,
    )
    return WeChatBrain(CFG, client=client, memory=memory, identity=identity)


def test_generate_success(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeTransport()
    brain = _brain(transport)
    result = brain.generate([{"role": "user", "content": "在吗"}], session="张三")
    assert result.text == "你好呀"
    assert result.usage["total_tokens"] == 12
    payload = transport.calls[0]["payload"]
    assert payload["messages"][0]["role"] == "system"
    assert "助手" in payload["messages"][0]["content"]
    assert payload["messages"][-1]["content"] == "在吗"


def test_postprocess_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    brain = _brain(FakeTransport("**加粗** 回复"))
    assert brain.generate([{"role": "user", "content": "hi"}]).text == "加粗 回复"


def test_empty_output_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    brain = _brain(FakeTransport("   "))
    with pytest.raises(LLMError, match="安全过滤"):
        brain.generate([{"role": "user", "content": "hi"}])


def test_no_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    brain = WeChatBrain(CFG)
    with pytest.raises(LLMError, match="DEEPSEEK_API_KEY"):
        brain.generate([{"role": "user", "content": "hi"}])
    with pytest.raises(LLMError):
        brain.ping()


def test_memory_injected_into_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SQLiteMemoryStore(tmp_path)
    try:
        store.add_memory(MemoryItem(content="用户喜欢喝美式", category="preference", chat="张三", key="喜欢"))
        transport = FakeTransport()
        brain = _brain(transport, memory=store)
        brain.generate([{"role": "user", "content": "推荐点喝的"}], session="张三")
        system_content = transport.calls[0]["payload"]["messages"][0]["content"]
        assert "用户喜欢喝美式" in system_content
    finally:
        store.close()


def test_missing_user_message(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(LLMError, match="缺少用户消息"):
        _brain(FakeTransport()).generate([{"role": "system", "content": "x"}])


def test_identity_note_in_system_prompt() -> None:
    identity = IdentityMap(
        chats={"王衢665": ChatIdentity(nicknames=("三",))},
        self_nicknames=("王",),
    )
    transport = FakeTransport()
    brain = _brain(transport, identity=identity)
    brain.generate([{"role": "user", "content": "在吗"}], session="王衢665")
    system_content = transport.calls[0]["payload"]["messages"][0]["content"]
    assert "你是「王」" in system_content
    assert "对方是「三」" in system_content
    assert "assistant" in system_content


def test_history_prompt_is_truncated_to_recent_n(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path)
    try:
        store.insert_messages("张三", [IncomingMessage(content=f"m{i}", sender="张三") for i in range(20)])
        transport = FakeTransport()
        cfg = replace(CFG, llm=replace(CFG.llm, history_turns=3))
        client = LLMClient(
            api_key="sk-test",
            base_url="https://api.example.com/v1",
            model="fake-model",
            transport=transport,
            sleep=lambda _s: None,
        )
        brain = WeChatBrain(cfg, client=client, memory=store)
        brain.generate([{"role": "user", "content": "m20"}], session="张三")
        messages = transport.calls[0]["payload"]["messages"]
        assert len(messages) <= 5  # system + 最近 3 条 + 当前
        contents = [item["content"] for item in messages]
        assert "m17" in contents and "m18" in contents and "m19" in contents
        assert "m1" not in contents and "m2" not in contents
    finally:
        store.close()
