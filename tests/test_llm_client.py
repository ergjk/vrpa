"""M5-01 测试：OpenAI 兼容客户端（FakeTransport，绝不访问真实 API）。"""

from __future__ import annotations

from typing import Any

import pytest

from vrpa.errors import LLMError
from vrpa.llm.client import LLMClient, TransportError


class FakeTransport:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(self, method, url, *, headers, payload, timeout):
        self.calls.append(
            {"method": method, "url": url, "headers": dict(headers), "payload": payload, "timeout": timeout}
        )
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _ok(content: str = "你好", *, model: str = "fake-model") -> tuple[int, dict[str, Any]]:
    return 200, {
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _client(transport: FakeTransport, sleeps: list[float], **overrides: Any) -> LLMClient:
    values = {
        "api_key": "sk-test",
        "base_url": "https://api.example.com/v1/",
        "model": "fake-model",
        "timeout": 5.0,
        "retries": 2,
        "backoff": 0.5,
        "transport": transport,
        "sleep": sleeps.append,
    }
    values.update(overrides)
    return LLMClient(**values)


def test_complete_success_and_usage() -> None:
    transport = FakeTransport([_ok()])
    sleeps: list[float] = []
    client = _client(transport, sleeps)
    result = client.complete([{"role": "user", "content": "hi"}], temperature=0.7, max_tokens=50)
    assert result.text == "你好"
    assert result.model == "fake-model"
    assert client.stats.requests == 1 and client.stats.total_tokens == 15
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.example.com/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-test"
    assert call["payload"]["model"] == "fake-model"
    assert call["payload"]["temperature"] == 0.7
    assert sleeps == []


def test_retry_on_network_and_5xx() -> None:
    transport = FakeTransport([TransportError("timeout"), (503, {}), _ok()])
    sleeps: list[float] = []
    client = _client(transport, sleeps)
    assert client.complete([{"role": "user", "content": "hi"}]).text == "你好"
    assert len(transport.calls) == 3
    assert sleeps == [0.5, 1.0]
    assert client.stats.requests == 1 and client.stats.failures == 2


def test_401_not_retried() -> None:
    transport = FakeTransport([(401, {"error": {"message": "invalid key"}})])
    sleeps: list[float] = []
    client = _client(transport, sleeps)
    with pytest.raises(LLMError, match="HTTP 401"):
        client.complete([{"role": "user", "content": "hi"}])
    assert len(transport.calls) == 1 and sleeps == [] and client.stats.failures == 0


def test_exhausted_retries() -> None:
    transport = FakeTransport([TransportError("down"), TransportError("down"), TransportError("down")])
    sleeps: list[float] = []
    client = _client(transport, sleeps)
    with pytest.raises(LLMError, match="已重试 2 次"):
        client.complete([{"role": "user", "content": "hi"}])
    assert client.stats.failures == 3


def test_malformed_response() -> None:
    transport = FakeTransport([(200, {"choices": []})])
    with pytest.raises(LLMError, match="响应结构异常"):
        _client(transport, []).complete([{"role": "user", "content": "hi"}])


def test_usage_accumulates() -> None:
    transport = FakeTransport([_ok(), _ok()])
    client = _client(transport, [])
    client.complete([{"role": "user", "content": "a"}])
    client.complete([{"role": "user", "content": "b"}])
    assert client.stats.as_dict() == {
        "requests": 2,
        "failures": 0,
        "prompt_tokens": 20,
        "completion_tokens": 10,
        "total_tokens": 30,
    }


def test_ping_success_and_failures() -> None:
    transport = FakeTransport([(200, {"data": []})])
    client = _client(transport, [])
    assert client.ping() >= 0.0
    assert transport.calls[0]["method"] == "GET"
    assert transport.calls[0]["url"] == "https://api.example.com/v1/models"

    with pytest.raises(LLMError, match="HTTP 403"):
        _client(FakeTransport([(403, {})]), []).ping()
    with pytest.raises(LLMError, match="连通性失败"):
        _client(FakeTransport([TransportError("dns")]), []).ping()
