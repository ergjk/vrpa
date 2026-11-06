"""环境变量解析：统一 ``VRPA_*`` 前缀（M0-F-06 弃用清理：不再回退旧名）。

设计目标（M0-F-06，ADR-0002 收口）：
    - 新前缀：``VRPA_CONFIG`` / ``VRPA_DATA_DIR`` / ``VRPA_DEBUG`` 等；
    - 旧应用前缀（如 ``APPNAME_*``）已在 M0-F-06 移除，读取不到即视为未设置；
    - 框架内核不硬编码任何平台/应用名。
"""

from __future__ import annotations

import os

__all__ = ["get_env"]


def get_env(primary: str, *, default: str | None = None) -> str | None:
    """读取环境变量：非空即返回，否则返回 ``default``。"""
    value = os.environ.get(primary, "").strip()
    return value or default
