"""memory-extract CLI 测试（帮助/无 Key 路径，不调用真实 LLM）。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from wechat_agent.tools.memory_extract import run_memory_extract


def test_memory_extract_help_returns_zero() -> None:
    assert run_memory_extract(["--help"]) == 0


def test_memory_extract_requires_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import wechat_agent.core.config as config_module

    cfg = SimpleNamespace(
        data_dir=tmp_path,
        api_key=lambda: "",
        llm=SimpleNamespace(base_url="https://api.example.com/v1", model="m", timeout=5, retries=1),
    )
    monkeypatch.setattr(config_module, "load_config", lambda path=None: cfg)
    assert run_memory_extract([]) == 5
    assert "DEEPSEEK_API_KEY" in capsys.readouterr().err
