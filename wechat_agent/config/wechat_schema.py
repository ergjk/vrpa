"""微信平台配置插件（M0-F-03）：校验 ``platform.options``。

职责边界：
    - 本模块知道微信字段（窗口标题正则 / 进程名 / 会话切换方式）；
    - ``vrpa`` 框架内核不知道任何微信字段，只通过 ``PlatformPlugin`` 协议调用本插件；
    - 插件版本随字段契约演进，写入 ``PlatformMeta.plugin_version`` 并进入 selftest 报告。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from vrpa.config.plugin import PlatformMeta
from vrpa.config.validators import as_bool, as_str, as_str_list, check_keys, expect_mapping
from vrpa.errors import ConfigError

WECHAT_PLATFORM_KIND = "wechat"
WECHAT_PLUGIN_VERSION = "1.0"

_CHAT_TYPES = frozenset({"private", "group"})
_SWITCH_MODES = frozenset({"search_box", "session_list"})
_OPTION_KEYS = (
    "window_title_regex",
    "process_names",
    "activate_before_action",
    "chat_type_default",
    "switch_chat",
)


@dataclass(frozen=True)
class WechatPlatformOptions:
    """``platform.options`` 校验后的微信平台配置。"""

    window_title_regex: str
    process_names: tuple[str, ...]
    activate_before_action: bool
    chat_type_default: str
    switch_chat: str


class WechatPlatformPlugin:
    """微信平台配置插件（实现 ``vrpa.config.plugin.PlatformPlugin`` 协议）。"""

    kind = WECHAT_PLATFORM_KIND
    legacy_sections = ("wechat",)

    def meta(self) -> PlatformMeta:
        return PlatformMeta(
            kind=self.kind,
            display_name="微信 PC 4.x",
            plugin_version=WECHAT_PLUGIN_VERSION,
        )

    def default_options(self) -> Mapping[str, Any]:
        return {
            "activate_before_action": True,
            "chat_type_default": "private",
            "switch_chat": "search_box",
        }

    def validate_options(self, options: Mapping[str, Any]) -> WechatPlatformOptions:
        where = "platform.options"
        raw = expect_mapping(options, where)
        check_keys(raw, _OPTION_KEYS, where)

        pattern = as_str(raw.get("window_title_regex"), f"{where}.window_title_regex")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ConfigError(f"{where}.window_title_regex 不是合法正则：{exc}") from exc

        return WechatPlatformOptions(
            window_title_regex=pattern,
            process_names=as_str_list(raw.get("process_names"), f"{where}.process_names", non_empty=True),
            activate_before_action=as_bool(raw.get("activate_before_action"), f"{where}.activate_before_action"),
            chat_type_default=as_str(raw.get("chat_type_default"), f"{where}.chat_type_default", choices=_CHAT_TYPES),
            switch_chat=as_str(raw.get("switch_chat"), f"{where}.switch_chat", choices=_SWITCH_MODES),
        )

    def describe(self) -> str:
        return f"{self.kind}（微信 PC 4.x：窗口定位 + 假 UIA 树 + 剪贴板采集；插件 v{WECHAT_PLUGIN_VERSION}）"


def create_plugin() -> WechatPlatformPlugin:
    """工厂函数（应用装配处调用，便于测试替换）。"""
    return WechatPlatformPlugin()
