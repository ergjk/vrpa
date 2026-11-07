"""LLM 记忆筛选器测试（Fake client，零真实 API）。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from vrpa.ports import Message
from wechat_agent.memory.selector import LLMMemorySelector, parse_candidates


class _FakeClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    def complete(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return SimpleNamespace(text=self.text)


def _msg(content: str, *, role: str = "user") -> Message:
    return Message(direction="in" if role == "user" else "out", content=content, role=role)


def test_selector_uses_persona_prompt_and_parses_json() -> None:
    client = _FakeClient('[{"content":"对方下周三去杭州出差","category":"event","importance":0.8,"confidence":0.9}]')
    selector = LLMMemorySelector(client)
    candidates = selector([_msg("我下周三去杭州出差"), _msg("哈哈", role="assistant")])
    assert len(candidates) == 1
    assert candidates[0].content == "对方下周三去杭州出差"
    assert candidates[0].category == "event"
    system = client.calls[0]["messages"][0]["content"]
    assert "真正会记在心里" in system
    assert "不要逐字摘抄" in system
    user = client.calls[0]["messages"][1]["content"]
    assert "对方: 我下周三去杭州出差" in user


def test_parse_candidates_accepts_fenced_json() -> None:
    text = '```json\n[{"content":"喜欢美式","category":"preference"}]\n```'
    assert parse_candidates(text)[0].content == "喜欢美式"


def test_parse_candidates_rejects_non_json() -> None:
    with pytest.raises(ValueError, match="JSON"):
        parse_candidates("我觉得没什么")


def test_selector_skips_empty_transcript() -> None:
    client = _FakeClient("[]")
    assert LLMMemorySelector(client)([Message(direction="in", content="   ")]) == ()
    assert client.calls == []


def test_parse_candidates_drops_invalid_rows() -> None:
    text = '[{"content":"x","category":"bad"},{"content":""},1,{"content":"ok","category":"event"}]'
    assert [c.content for c in parse_candidates(text)] == ["ok"]


def test_selector_from_config_builds_client() -> None:
    from types import SimpleNamespace

    from wechat_agent.memory.selector import selector_from_config

    cfg = SimpleNamespace(
        api_key=lambda: "sk-test",
        llm=SimpleNamespace(base_url="https://api.example.com/v1", model="m", timeout=5, retries=1),
    )
    assert selector_from_config(cfg) is not None
