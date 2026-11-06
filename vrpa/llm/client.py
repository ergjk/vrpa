"""OpenAI 兼容 LLM 客户端（M5-01，平台无关）：超时重试 + 用量统计。

网络层抽象为 ``HttpTransport``：生产使用 stdlib ``urllib``；测试注入 FakeTransport，
**单元测试绝不发起真实付费 API 请求**。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from vrpa.errors import LLMError
from vrpa.ports import LLMResult

__all__ = [
    "HttpTransport",
    "LLMClient",
    "TransportError",
    "UrllibTransport",
    "UsageStats",
]


class TransportError(Exception):
    """网络层错误（连接失败/超时），可重试。"""


@runtime_checkable
class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None,
        timeout: float,
    ) -> tuple[int, Mapping[str, Any]]:
        """返回 (HTTP 状态码, JSON 响应体)。"""
        ...


class UrllibTransport:
    """stdlib 实现（无第三方依赖，天然兼容 OpenAI 协议）。"""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None,
        timeout: float,
    ) -> tuple[int, Mapping[str, Any]]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=dict(headers), method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - 固定 OpenAI 兼容地址
                return int(response.status), _decode(response.read())
        except urllib.error.HTTPError as exc:
            return int(exc.code), _decode(exc.read())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError(str(exc)) from exc


def _decode(raw: bytes) -> Mapping[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError as exc:
        raise TransportError(f"响应不是合法 JSON：{exc}") from exc
    return data if isinstance(data, dict) else {}


@dataclass
class UsageStats:
    """累计用量统计。"""

    requests: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def record(self, usage: Mapping[str, Any]) -> None:
        prompt = int(usage.get("prompt_tokens", 0) or 0)
        completion = int(usage.get("completion_tokens", 0) or 0)
        total = int(usage.get("total_tokens", prompt + completion) or 0)
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += total

    def as_dict(self) -> dict[str, int]:
        return {
            "requests": self.requests,
            "failures": self.failures,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class LLMClient:
    """OpenAI 兼容 Chat Completions 客户端。"""

    api_key: str
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    timeout: float = 25.0
    retries: int = 3
    backoff: float = 0.5
    transport: HttpTransport = field(default_factory=UrllibTransport)
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    stats: UsageStats = field(default_factory=UsageStats)

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    def _headers(self) -> Mapping[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float = 1.15,
        max_tokens: int = 400,
    ) -> LLMResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(message) for message in messages],
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        self.stats.requests += 1
        last_error: str = "未知错误"
        for attempt in range(self.retries + 1):
            started = self.clock()
            try:
                status, data = self.transport.request(
                    "POST",
                    self._url("/chat/completions"),
                    headers=self._headers(),
                    payload=payload,
                    timeout=self.timeout,
                )
            except TransportError as exc:
                last_error = f"网络错误：{exc}"
                self.stats.failures += 1
                self._backoff(attempt)
                continue
            if status == 429 or status >= 500:
                last_error = f"HTTP {status}（可重试）"
                self.stats.failures += 1
                self._backoff(attempt)
                continue
            if status != 200:
                raise LLMError(
                    f"LLM 请求被拒绝：HTTP {status}（{_error_message(data)}）",
                    hint="检查 API Key / base_url / 模型名",
                )
            result = self._parse(data, latency_ms=(self.clock() - started) * 1000.0)
            self.stats.record(result.usage)
            return result
        raise LLMError(
            f"LLM 请求失败（已重试 {self.retries} 次）：{last_error}",
            hint="检查网络、代理与 API 配额后重试",
        )

    def ping(self) -> float:
        """连通性探测（GET /models，返回延迟毫秒；不产生 Completions 计费）。"""
        started = self.clock()
        try:
            status, data = self.transport.request(
                "GET",
                self._url("/models"),
                headers=self._headers(),
                payload=None,
                timeout=min(self.timeout, 10.0),
            )
        except TransportError as exc:
            raise LLMError(f"LLM 连通性失败：{exc}", hint="检查网络/代理/base_url") from exc
        latency = (self.clock() - started) * 1000.0
        if status != 200:
            raise LLMError(
                f"LLM 连通性失败：HTTP {status}（{_error_message(data)}）",
                hint="检查 API Key 是否有效",
            )
        return latency

    # ------------------------------------------------------------ 内部
    def _parse(self, data: Mapping[str, Any], *, latency_ms: float) -> LLMResult:
        try:
            choices = data["choices"]
            content = choices[0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"LLM 响应结构异常：{data!r}"[:500]) from exc
        if not isinstance(content, str):
            raise LLMError(f"LLM 响应 content 非字符串：{type(content).__name__}")
        usage = data.get("usage", {})
        return LLMResult(
            text=content,
            model=str(data.get("model", self.model)),
            usage=dict(usage) if isinstance(usage, Mapping) else {},
            latency_ms=float(latency_ms),
        )

    def _backoff(self, attempt: int) -> None:
        if attempt >= self.retries:
            return
        self.sleep(self.backoff * (2**attempt))


def _error_message(data: Mapping[str, Any]) -> str:
    error = data.get("error")
    if isinstance(error, Mapping):
        return str(error.get("message", ""))[:200]
    return str(error or "")[:200]
