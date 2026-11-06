"""应用层适配器注册表：把微信参考适配器接入 ``vrpa.platform.AdapterRegistry``（M0-F-05）。

第三方平台在自己的应用包里做同样的事：
    registry = AdapterRegistry()
    registry.register(MyAdapter())
"""

from __future__ import annotations

from vrpa.platform import AdapterRegistry
from wechat_agent.adapter import ADAPTER, WeChatAdapter

ADAPTER_REGISTRY: AdapterRegistry = AdapterRegistry()
ADAPTER_REGISTRY.register(ADAPTER)

__all__ = ["ADAPTER", "ADAPTER_REGISTRY", "WeChatAdapter"]
