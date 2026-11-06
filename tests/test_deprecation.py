"""M0-F-06 弃用清理回归：旧 shim / 旧环境变量 / 旧 import 路径必须不存在。

历史：M0-F-02 保留 ``wechat_agent.core.errors/logging`` 兼容 shim 与
``WECHAT_AGENT_*`` 环境变量回退；M0-F-06 已按计划全部移除。
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest

import vrpa.config.env as env_module
from wechat_agent import main as main_module

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "module",
    ["wechat_agent.core.errors", "wechat_agent.core.logging", "wechat_agent.memory.db"],
)
def test_legacy_modules_removed(module: str) -> None:
    assert importlib.util.find_spec(module) is None


def test_legacy_env_fallback_removed() -> None:
    signature = inspect.signature(env_module.get_env)
    assert "legacy" not in signature.parameters
    assert not hasattr(env_module, "warn_legacy_env")


def test_app_uses_vrpa_directly() -> None:
    for relative in (
        "wechat_agent/main.py",
        "wechat_agent/core/config.py",
        "wechat_agent/adapter.py",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "wechat_agent.core.errors" not in text
        assert "wechat_agent.core.logging" not in text


def test_legacy_env_name_not_referenced_in_code() -> None:
    offenders: list[str] = []
    for path in (ROOT / "wechat_agent").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "WECHAT_AGENT_CONFIG" in text or "WECHAT_AGENT_DATA_DIR" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_main_module_has_db_check_command() -> None:
    assert "db-check" in main_module.COMMANDS
