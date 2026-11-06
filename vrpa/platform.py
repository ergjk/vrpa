"""平台适配器契约与注册表（平台无关）。

``PlatformAdapter`` 是「新增平台」的唯一扩展点：
    1. 声明平台标识与能力矩阵；
    2. 提供配置插件（实现 ``PlatformPlugin``，供 ``vrpa.config`` 注册）；
    3. 提供元素树 profile 规范与消息解析策略包；
    4. 创建五个端口（Ports）。

``AdapterRegistry`` 负责按 ``kind`` 注册与实例化；未知/重复 kind 给可读 ``ConfigError``。

「可替换感知层」的判定标准：适配器通过 ``vrpa.testing.contracts`` 全绿（M0-F-04 交付）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from vrpa.config.plugin import PlatformPlugin
from vrpa.errors import ConfigError
from vrpa.ports import Ports

__all__ = [
    "CAPABILITY_TEXT_ONLY",
    "CAPABILITY_GROUP_CHAT",
    "CAPABILITY_FILE_TRANSFER",
    "AdapterInfo",
    "AdapterRegistry",
    "PlatformAdapter",
    "is_platform_adapter",
]

CAPABILITY_TEXT_ONLY = "text_only"
CAPABILITY_GROUP_CHAT = "group_chat"
CAPABILITY_FILE_TRANSFER = "file_transfer"


class PlatformAdapter(Protocol):
    """平台适配器协议（第三方实现必须满足，并通过合规测试套件）。"""

    kind: str
    display_name: str
    adapter_version: str

    def capabilities(self) -> frozenset[str]:
        """能力矩阵（如 text_only / group_chat / file_transfer）。"""
        ...

    def config_plugin(self) -> PlatformPlugin:
        """配置插件（platform.options 校验器）；插件 kind 必须与适配器一致。"""
        ...

    def element_tree_profile_spec(self) -> Mapping[str, Any]:
        """元素树 profile 规范（schema / elements 等结构约束）。"""
        ...

    def parser_pack(self) -> Mapping[str, Any]:
        """消息解析策略包（strategies / min_samples 等）。"""
        ...

    def create_ports(self, options: Any) -> Ports:
        """按平台配置创建五端口集合。"""
        ...

    def describe(self) -> str:
        """一行人类可读描述（进入 selftest / 契约报告）。"""
        ...


_ADAPTER_ATTRS = ("kind", "display_name", "adapter_version")
_ADAPTER_METHODS = (
    "capabilities",
    "config_plugin",
    "element_tree_profile_spec",
    "parser_pack",
    "create_ports",
    "describe",
)


def is_platform_adapter(obj: object) -> bool:
    """结构化判定：协议含数据成员，不能用 isinstance 检查 runtime_checkable 协议。"""
    if any(not hasattr(obj, name) for name in _ADAPTER_ATTRS):
        return False
    return all(callable(getattr(obj, name, None)) for name in _ADAPTER_METHODS)


class AdapterRegistry:
    """适配器注册表：kind -> 适配器实例。"""

    def __init__(self) -> None:
        self._adapters: dict[str, PlatformAdapter] = {}

    def register(self, adapter: PlatformAdapter) -> None:
        kind = getattr(adapter, "kind", "").strip()
        if not kind:
            raise ConfigError("平台适配器缺少非空 kind")
        if kind in self._adapters:
            raise ConfigError(f"平台适配器重复注册：{kind}")
        if not is_platform_adapter(adapter):
            raise ConfigError(f"平台适配器 {kind!r} 未实现 PlatformAdapter 协议")
        self._adapters[kind] = adapter

    def get(self, kind: str) -> PlatformAdapter:
        if kind not in self._adapters:
            raise ConfigError(f"未知平台适配器 kind={kind!r}（已注册：{sorted(self._adapters)}；请检查 platform.kind）")
        return self._adapters[kind]

    def create(self, kind: str, options: Any = None) -> Ports:
        """按 kind 创建五端口集合。"""
        return self.get(kind).create_ports(options)

    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def config_plugins(self) -> tuple[tuple[str, PlatformPlugin], ...]:
        """返回 (kind, config_plugin) 列表，便于应用层注册到配置内核。"""
        return tuple((kind, adapter.config_plugin()) for kind, adapter in self._adapters.items())

    def describe_all(self) -> Mapping[str, str]:
        return {kind: adapter.describe() for kind, adapter in self._adapters.items()}


@dataclass(frozen=True)
class AdapterInfo:
    """适配器元信息快照（供 selftest / --json 输出）。"""

    kind: str
    display_name: str
    adapter_version: str
    capabilities: tuple[str, ...]

    @classmethod
    def from_adapter(cls, adapter: PlatformAdapter) -> AdapterInfo:
        return cls(
            kind=adapter.kind,
            display_name=adapter.display_name,
            adapter_version=adapter.adapter_version,
            capabilities=tuple(sorted(adapter.capabilities())),
        )
