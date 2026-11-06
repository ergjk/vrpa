"""兼容 shim：已迁移到 `vrpa.errors`（M0-F-02；包名更名见 ADR-0001 §5 兼容策略）。

保留原因：旧路径 `wechat_agent.core.errors` 在 M0-01~M0-06 已被验收，
按兼容策略保留**一个里程碑**，首次导入打 DeprecationWarning。
弃用计划：M0-F-06 删除；新代码请直接 `from vrpa.errors import ...`。

旧应用层类名别名已按指令彻底移除，
请直接使用框架名 `AgentFrameworkError` / `SessionSwitchFailed`。
"""

from __future__ import annotations

import warnings

from vrpa.errors import (
    ERROR_CLASSES,
    EXIT_CODE_MAP,
    AgentFrameworkError,
    ConfigError,
    CopyFailed,
    DBError,
    ElementNotVisible,
    ExitCode,
    InternalError,
    Interrupted,
    LLMError,
    ProfileMismatch,
    RedlineViolation,
    SessionSwitchFailed,
    TreeConfigError,
    UsageError,
    VerifyFailed,
    WindowNotForeground,
    WindowNotFound,
    exit_code_for,
    format_exception_chain,
)

warnings.warn(
    "wechat_agent.core.errors 已迁移到 vrpa.errors（M0-F-02）；旧路径将在 M0-F-06 移除",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "ERROR_CLASSES",
    "EXIT_CODE_MAP",
    "AgentFrameworkError",
    "ConfigError",
    "CopyFailed",
    "DBError",
    "ElementNotVisible",
    "ExitCode",
    "InternalError",
    "Interrupted",
    "LLMError",
    "ProfileMismatch",
    "RedlineViolation",
    "SessionSwitchFailed",
    "TreeConfigError",
    "UsageError",
    "VerifyFailed",
    "WindowNotFound",
    "WindowNotForeground",
    "exit_code_for",
    "format_exception_chain",
]
