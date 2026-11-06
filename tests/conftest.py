"""pytest 全局夹具：隔离真实付费 LLM 与真实桌面环境。

红线：任何单元测试不得因本机存在 API Key 而发起真实付费请求。
需要真实 Key 的测试必须显式 monkeypatch 注入 FakeTransport。
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_real_llm_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _ignore_repo_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试不读取仓库根 .env（避免真实 Key 触发真实 API 调用）。

    临时目录里的 .env 仍按原逻辑加载，供配置测试使用。
    """
    import wechat_agent.core.config as config_module

    repo_root = Path(__file__).resolve().parents[1]
    repo_env = (repo_root / ".env").resolve()
    original = config_module.load_dotenv

    def guarded(path: object) -> dict[str, str]:
        try:
            resolved = Path(str(path)).resolve()
        except OSError:
            return original(path)  # type: ignore[arg-type]
        if resolved == repo_env:
            return {}
        return original(path)  # type: ignore[arg-type]

    monkeypatch.setattr(config_module, "load_dotenv", guarded)
