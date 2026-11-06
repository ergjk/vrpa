"""环境变量解析：``VRPA_*`` 为唯一正式前缀，旧名回退但打印 DeprecationWarning。

设计目标（M0-F-03，ADR-0002）：
    - 新前缀：``VRPA_CONFIG`` / ``VRPA_DATA_DIR`` / ``VRPA_DEBUG`` 等；
    - 旧名（如 ``APPNAME_CONFIG``）保留一个里程碑，读取时发 DeprecationWarning；
    - 框架内核不硬编码任何平台/应用名。
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Sequence

__all__ = ["get_env", "warn_legacy_env"]


def warn_legacy_env(name: str, replacement: str) -> None:
    """对使用旧环境变量名的调用方发出弃用告警。"""
    warnings.warn(
        f"环境变量 {name} 已弃用，请改用 {replacement}（旧名将在后续里程碑移除）",
        DeprecationWarning,
        stacklevel=3,
    )


def get_env(
    primary: str,
    legacy: Sequence[str] = (),
    *,
    default: str | None = None,
) -> str | None:
    """按 ``primary -> legacy[0] -> legacy[1] ...`` 顺序取第一个非空环境变量。

    使用旧名时会发出 DeprecationWarning；全部未设置时返回 ``default``。
    """
    value = os.environ.get(primary, "").strip()
    if value:
        return value
    for name in legacy:
        value = os.environ.get(name, "").strip()
        if value:
            warn_legacy_env(name, primary)
            return value
    return default
