"""配置路径环境变量测试（M0-F-06 弃用清理后：仅 VRPA_CONFIG）。

契约：VRPA_CONFIG > 默认 ./config.yaml（旧 WECHAT_AGENT_CONFIG 已移除）。
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


def test_vrpa_config_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VRPA_CONFIG", "custom.yaml")
    assert default_config_path() == Path("custom.yaml")


def test_legacy_env_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WECHAT_AGENT_CONFIG", "legacy.yaml")
    assert default_config_path() == Path("config.yaml")
