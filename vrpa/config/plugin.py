"""平台配置插件契约与注册表（平台无关）。

为什么需要插件：
    配置的**通用段**（app / llm / safety ...）由框架内核校验；
    **平台私有段**（如 ``platform.options``）必须由对应平台的适配器提供校验器，
    框架内核不得出现任何平台名或平台字段知识。

清单：
    PlatformMeta        平台元信息（kind / 展示名 / 插件版本）
    PlatformPlugin      插件协议（kind / legacy_sections / meta / default_options /
                        validate_options / describe）
    PlatformRegistry    注册表：kind -> 插件；负责 v1 老平台段名到 kind 的迁移映射
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from vrpa.errors import ConfigError

__all__ = ["PlatformMeta", "PlatformPlugin", "PlatformRegistry", "is_platform_plugin"]


@dataclass(frozen=True)
class PlatformMeta:
    """平台元信息（会被 selftest / --json 输出）。"""

    kind: str
    display_name: str
    plugin_version: str = "1.0"


@runtime_checkable
class PlatformPlugin(Protocol):
    """平台配置插件协议。"""

    kind: str
    legacy_sections: tuple[str, ...]

    def meta(self) -> PlatformMeta:
        """平台元信息。"""
        ...

    def default_options(self) -> Mapping[str, Any]:
        """平台 options 的默认值（框架内核会做深度合并）。"""
        ...

    def validate_options(self, options: Mapping[str, Any]) -> Any:
        """校验并返回平台配置对象（框架不解释其内部结构）。"""
        ...

    def describe(self) -> str:
        """一行人类可读描述（进入 selftest 报告）。"""
        ...


_PLUGIN_ATTRS = ("kind", "legacy_sections")
_PLUGIN_METHODS = ("meta", "default_options", "validate_options", "describe")


def is_platform_plugin(obj: object) -> bool:
    """结构化判定：协议含数据成员，不能用 isinstance 检查 runtime_checkable 协议。"""
    if any(not hasattr(obj, name) for name in _PLUGIN_ATTRS):
        return False
    return all(callable(getattr(obj, name, None)) for name in _PLUGIN_METHODS)


class PlatformRegistry:
    """平台插件注册表。"""

    def __init__(self) -> None:
        self._plugins: dict[str, PlatformPlugin] = {}

    def register(self, plugin: PlatformPlugin) -> None:
        kind = getattr(plugin, "kind", "").strip()
        if not kind:
            raise ConfigError("平台插件缺少非空 kind")
        if kind in self._plugins:
            raise ConfigError(f"平台插件重复注册：{kind}")
        self._plugins[kind] = plugin

    def get(self, kind: str) -> PlatformPlugin:
        if kind not in self._plugins:
            raise ConfigError(f"未知平台 kind={kind!r}（已注册：{sorted(self._plugins)}；请检查 platform.kind）")
        return self._plugins[kind]

    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._plugins))

    def legacy_section_map(self) -> dict[str, str]:
        """v1 老平台段名 -> kind（供 schema v1 自动升级）。"""
        mapping: dict[str, str] = {}
        for kind, plugin in self._plugins.items():
            for section_name in plugin.legacy_sections:
                mapping[section_name] = kind
        return mapping
