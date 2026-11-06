"""微信参考适配器：把 ``vrpa`` 的 Ports / PlatformAdapter / AdapterRegistry 接到微信实现（M0-F-05）。

职责：
    - 声明平台身份与能力矩阵（text_only + group_chat）；
    - 提供配置插件、元素树 profile 规范、消息解析策略包；
    - ``create_ports()`` 组装五个微信端口实现（M1-M6 逐步补齐真实能力）。

用法：
    >>> from wechat_agent.adapter import ADAPTER, WeChatAdapter
    >>> ports = WeChatAdapter().create_ports(cfg)      # cfg: wechat_agent.core.config.Config
    >>> python -m vrpa.testing.contracts --adapter wechat_agent.adapter:WeChatAdapter
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from vrpa.platform import CAPABILITY_GROUP_CHAT, CAPABILITY_TEXT_ONLY
from vrpa.ports import Ports
from wechat_agent.act.executor import WeChatExecutor
from wechat_agent.brain.client import WeChatBrain
from wechat_agent.config.wechat_schema import WECHAT_PLATFORM_KIND, WechatPlatformPlugin, create_plugin
from wechat_agent.core.config import Config, load_config
from wechat_agent.memory.store import WeChatMemoryStore
from wechat_agent.perception.capture import WeChatPerception
from wechat_agent.perception.element_tree import ELEMENT_IDS, WeChatElementTree

ADAPTER_VERSION = "1.0"

ELEMENT_TREE_PROFILE_SPEC: Mapping[str, Any] = {
    "schema": 1,
    "root": "main_window",
    "elements": list(ELEMENT_IDS),
    "anchors": "data/anchors/<profile>/<element>.png",
    "match": {"algorithm": "opencv-multi-scale", "threshold": 0.88, "fallback": "forbidden"},
}

PARSER_PACK: Mapping[str, Any] = {
    "strategies": ["wechat_block", "timestamp_prefix", "sender_colon", "multi_line_block"],
    "fallbacks": ["anchor_high", "anchor_single", "count_diff"],
    "min_samples": 15,
}


class WeChatAdapter:
    """微信参考适配器（实现 ``vrpa.platform.PlatformAdapter`` 结构）。"""

    kind = WECHAT_PLATFORM_KIND
    display_name = "微信 PC 4.x"
    adapter_version = ADAPTER_VERSION

    def capabilities(self) -> frozenset[str]:
        return frozenset({CAPABILITY_TEXT_ONLY, CAPABILITY_GROUP_CHAT})

    def config_plugin(self) -> WechatPlatformPlugin:
        return create_plugin()

    def element_tree_profile_spec(self) -> Mapping[str, Any]:
        return dict(ELEMENT_TREE_PROFILE_SPEC)

    def parser_pack(self) -> Mapping[str, Any]:
        return dict(PARSER_PACK)

    def create_ports(self, options: Any = None) -> Ports:
        config = coerce_config(options)
        return Ports(
            element_tree=WeChatElementTree(config),
            perception=WeChatPerception(config),
            executor=WeChatExecutor(config),
            brain=WeChatBrain(config),
            memory=WeChatMemoryStore(config),
        )

    def describe(self) -> str:
        return "微信 PC 4.x（假 UIA 树 + 剪贴板采集 + 双库记忆 + 推理/执行端口；M1/M2/M5/M6 逐步实现真实能力）"


ADAPTER: WeChatAdapter = WeChatAdapter()


def coerce_config(options: Any = None) -> Config:
    """契约套件/CLI 传 Mapping 时按默认配置文件装配；传 Config 时直接使用。"""
    if isinstance(options, Config):
        return options
    return load_config()
