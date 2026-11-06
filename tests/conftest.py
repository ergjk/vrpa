"""pytest 全局夹具：隔离真实付费 LLM 与真实桌面环境。

红线：任何单元测试不得因本机存在 API Key 而发起真实付费请求。
需要真实 Key 的测试必须显式 monkeypatch 注入 FakeTransport。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_real_llm_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
