"""DSH-RPA 框架底座（平台无关，仅依赖标准库）。

本包是「可替换感知层」的框架层：日志/审计、异常与退出码、以及后续的
配置内核、端口协议（Ports）、平台适配器契约与合规测试套件。

纪律（M0-F，见 docs/ADR/0001-framework-layering.md）：
- 只依赖标准库；禁止 import 任何应用层包；
- 标识符与默认值不得含具体平台名，平台差异由适配器注入；
- 应用层通过本包的公开 API 使用框架能力，不再复制实现。
"""

from __future__ import annotations

__version__ = "0.1.0"

# 框架契约版本（语义化 MAJOR.MINOR，见 docs/ADR/0003-interface-stability.md）
INTERFACE_VERSION = "1.0"

__all__ = ["INTERFACE_VERSION", "__version__"]
