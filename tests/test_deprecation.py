"""M0-F-02 兼容 shim 测试（含 M0-F-02b 框架包改名 dsh_rpa -> vrpa）。

覆盖：
    1. 旧路径 `wechat_agent.core.*` 与框架对象同一、发 DeprecationWarning；
    2. 旧框架包名 `dsh_rpa*` 已降级为 shim，与 `vrpa*` 同一对象、发 DeprecationWarning；
    3. 应用内部已不再 import 任何 shim（含旧框架包名）；
    4. 告警不是死代码（`-W error` 子进程必须失败）。

旧路径删除计划：M0-F-06（见 docs/ADR/0001-framework-layering.md §5）。
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

import dsh_rpa as legacy_framework
import dsh_rpa.errors as legacy_errors
import dsh_rpa.logging as legacy_logging
import vrpa
import vrpa.errors as framework_errors
import vrpa.logging as framework_logging
import wechat_agent.core.errors as shim_errors
import wechat_agent.core.logging as shim_logging

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- 应用层 shim
def test_error_shim_identity() -> None:
    assert shim_errors.ConfigError is framework_errors.ConfigError
    assert shim_errors.WeChatAgentError is framework_errors.AgentFrameworkError
    assert shim_errors.ChatSwitchFailed is framework_errors.SessionSwitchFailed
    assert shim_errors.ERROR_CLASSES is framework_errors.ERROR_CLASSES
    assert shim_errors.EXIT_CODE_MAP is framework_errors.EXIT_CODE_MAP
    assert shim_errors.exit_code_for is framework_errors.exit_code_for


def test_logging_shim_identity() -> None:
    assert shim_logging.setup_logging is framework_logging.setup_logging
    assert shim_logging.get_logger is framework_logging.get_logger
    assert shim_logging.LOG_FILE_NAME == framework_logging.LOG_FILE_NAME
    assert shim_logging.AUDIT_FILE_NAME == framework_logging.AUDIT_FILE_NAME


def test_logging_shim_sets_app_namespace() -> None:
    # shim 导入时把命名空间配置为 wechat_agent（旧行为兼容）
    assert framework_logging.logger_namespace() == "wechat_agent"
    assert shim_logging.get_logger().name == "wechat_agent"


def test_error_shim_emits_deprecation_warning() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.reload(shim_errors)
    messages = [str(item.message) for item in caught if issubclass(item.category, DeprecationWarning)]
    assert any("vrpa.errors" in message for message in messages), messages


def test_logging_shim_emits_deprecation_warning() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.reload(shim_logging)
    messages = [str(item.message) for item in caught if issubclass(item.category, DeprecationWarning)]
    assert any("vrpa.logging" in message for message in messages), messages


# ---------------------------------------------------------------- 旧框架包名 shim
def test_legacy_framework_shim_identity() -> None:
    assert legacy_framework.__version__ == vrpa.__version__
    assert legacy_framework.INTERFACE_VERSION == vrpa.INTERFACE_VERSION
    assert legacy_errors.ConfigError is framework_errors.ConfigError
    assert legacy_errors.AgentFrameworkError is framework_errors.AgentFrameworkError
    assert legacy_errors.ERROR_CLASSES is framework_errors.ERROR_CLASSES
    assert legacy_logging.setup_logging is framework_logging.setup_logging
    assert legacy_logging.LOG_FILE_NAME == framework_logging.LOG_FILE_NAME


def test_legacy_framework_package_warns() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.reload(legacy_framework)
    messages = [str(item.message) for item in caught if issubclass(item.category, DeprecationWarning)]
    assert any("已更名为 vrpa" in message for message in messages), messages


def test_legacy_framework_errors_warns() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.reload(legacy_errors)
    messages = [str(item.message) for item in caught if issubclass(item.category, DeprecationWarning)]
    assert any("vrpa.errors" in message for message in messages), messages


def test_legacy_framework_logging_warns() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.reload(legacy_logging)
    messages = [str(item.message) for item in caught if issubclass(item.category, DeprecationWarning)]
    assert any("vrpa.logging" in message for message in messages), messages


# ---------------------------------------------------------------- 告警有效性 & 迁移完整性
@pytest.mark.parametrize(
    "target",
    [
        "wechat_agent.core.errors",
        "wechat_agent.core.logging",
        "dsh_rpa",
        "dsh_rpa.errors",
        "dsh_rpa.logging",
    ],
)
def test_shim_warning_is_fatal_under_w_error(target: str) -> None:
    """新导入路径必须真的触发 DeprecationWarning（不是死代码）。"""
    proc = subprocess.run(
        [sys.executable, "-W", "error::DeprecationWarning", "-c", f"import {target}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode != 0
    assert "DeprecationWarning" in (proc.stderr + proc.stdout)


@pytest.mark.parametrize(
    "relative_path",
    ["wechat_agent/main.py", "wechat_agent/core/config.py", "wechat_agent/memory/db.py"],
)
def test_app_internals_use_only_vrpa(relative_path: str) -> None:
    text = (ROOT / relative_path).read_text(encoding="utf-8")
    assert "wechat_agent.core.errors" not in text
    assert "wechat_agent.core.logging" not in text
    assert "dsh_rpa" not in text
