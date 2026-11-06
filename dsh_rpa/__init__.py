"""兼容 shim：框架包已更名为 vrpa（Vision RPA）。

按 ADR-0001 §5 兼容策略，旧包名 `dsh_rpa` 保留一个里程碑，首次导入打 DeprecationWarning。
弃用计划：M0-F-06 删除；请改用 `import vrpa` / `from vrpa.errors import ...`。
"""

from __future__ import annotations

import warnings

from vrpa import INTERFACE_VERSION, __version__

warnings.warn(
    "dsh_rpa 已更名为 vrpa（Vision RPA），请改用 import vrpa；旧包名将在 M0-F-06 移除",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["INTERFACE_VERSION", "__version__"]
