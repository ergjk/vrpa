"""配置路径环境变量优先级测试（M0 框架底座，VRPA_* 前缀）。

契约：VRPA_CONFIG > WECHAT_AGENT_CONFIG（应用层兼容回退）> 默认 ./config.yaml
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wechat_agent.core.config import default_config_path

ENV_NAMES = ("VRPA_CONFIG", "WECHAT_AGENT_CONFIG")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_default_when_no_env() -> None:
    assert default_config_path() == Path("config.yaml")


def test_app_legacy_env_still_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WECHAT_AGENT_CONFIG", "legacy.yaml")
    assert default_config_path() == Path("legacy.yaml")


def test_new_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WECHAT_AGENT_CONFIG", "legacy.yaml")
    monkeypatch.setenv("VRPA_CONFIG", "new.yaml")
    assert default_config_path() == Path("new.yaml")
