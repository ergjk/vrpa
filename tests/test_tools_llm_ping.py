"""M5-05 测试：llm-ping 命令（无 Key 路径不联网）。"""

from __future__ import annotations

import json

import pytest

from wechat_agent import main as main_module
from wechat_agent.tools.llm_ping import run_llm_ping


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


def test_missing_key(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_llm_ping([]) == 5
    assert "DEEPSEEK_API_KEY 未设置" in capsys.readouterr().err


def test_missing_key_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_llm_ping(["--json"]) == 5
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "DEEPSEEK_API_KEY" in payload["error"]


def test_main_dispatch_missing_key() -> None:
    assert main_module.main(["llm-ping"]) == 5


def test_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_llm_ping(["--help"]) == 0
    assert "llm-ping" in capsys.readouterr().out


def test_help_shows_command() -> None:
    assert main_module.main(["--help"]) == 0
