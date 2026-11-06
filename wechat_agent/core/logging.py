"""兼容 shim：已迁移到 `dsh_rpa.logging`（M0-F-02，见 ADR-0001 §5 兼容策略）。

保留原因：旧路径 `wechat_agent.core.logging` 已被 M0-03 验收；
按兼容策略保留**一个里程碑**，首次导入打 DeprecationWarning。
弃用计划：M0-F-06 删除；新代码请直接 `from dsh_rpa.logging import ...`。

本 shim 会把框架日志命名空间配置为 `wechat_agent`（旧行为），
并让数据目录环境变量按 `DSH_RPA_DATA_DIR` -> `WECHAT_AGENT_DATA_DIR` 顺序回退。
"""

from __future__ import annotations

import warnings

from dsh_rpa.logging import (
    AUDIT_FILE_NAME,
    LOG_BACKUP_COUNT,
    LOG_FILE_NAME,
    LOG_FORMAT,
    LOG_MAX_BYTES,
    TRACE_ID_LEN,
    AuditLogger,
    LoggingNamespace,
    TraceFilter,
    audit,
    audit_path,
    bind_trace,
    configure_logging_namespace,
    current_trace_id,
    get_logger,
    get_namespace_config,
    log_path,
    logger_namespace,
    new_trace_id,
    redact,
    redact_mapping,
    self_check,
    setup_audit,
    setup_logging,
    shutdown_logging,
    trace_scope,
)

# 旧行为：logger 名 wechat_agent；环境变量新名优先、旧名回退
configure_logging_namespace(
    "wechat_agent",
    data_dir_env=("DSH_RPA_DATA_DIR", "WECHAT_AGENT_DATA_DIR"),
)

warnings.warn(
    "wechat_agent.core.logging 已迁移到 dsh_rpa.logging（M0-F-02）；旧路径将在 M0-F-06 移除",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "AUDIT_FILE_NAME",
    "LOG_BACKUP_COUNT",
    "LOG_FILE_NAME",
    "LOG_FORMAT",
    "LOG_MAX_BYTES",
    "TRACE_ID_LEN",
    "AuditLogger",
    "LoggingNamespace",
    "TraceFilter",
    "audit",
    "audit_path",
    "bind_trace",
    "configure_logging_namespace",
    "current_trace_id",
    "get_logger",
    "get_namespace_config",
    "log_path",
    "logger_namespace",
    "new_trace_id",
    "redact",
    "redact_mapping",
    "self_check",
    "setup_audit",
    "setup_logging",
    "shutdown_logging",
    "trace_scope",
]
