"""运行期基础设施（平台无关）：崩溃恢复/失败自保（M6-03）。"""

from __future__ import annotations

from vrpa.runtime.recovery import FailureGuard, RecoveryError, RecoveryManager, RecoveryReport, RuntimeSnapshot

__all__ = ["FailureGuard", "RecoveryError", "RecoveryManager", "RecoveryReport", "RuntimeSnapshot"]
