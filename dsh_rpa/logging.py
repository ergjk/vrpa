"""兼容 shim：`dsh_rpa.logging` 已更名为 `vrpa.logging`（Vision RPA）。

弃用计划：M0-F-06 删除；请改用 `from vrpa.logging import ...`。
"""

from __future__ import annotations

import warnings

from vrpa.logging import *  # noqa: F403
from vrpa.logging import __all__ as _framework_all

warnings.warn(
    "dsh_rpa.logging 已更名为 vrpa.logging，请改用 from vrpa.logging import ...；旧包名将在 M0-F-06 移除",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = list(_framework_all)
