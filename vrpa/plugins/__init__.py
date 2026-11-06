"""插件接口（M6-04，平台无关）：生命周期钩子 + 故障隔离的管理器。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = ["Plugin", "PluginContext", "PluginManager", "PluginMeta"]


@dataclass(frozen=True)
class PluginContext:
    """插件运行上下文（dry_run 必须透传，插件不得直接触碰键鼠）。"""

    dry_run: bool = True
    session: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginMeta:
    name: str
    version: str = "0.1"
    description: str = ""


@runtime_checkable
class Plugin(Protocol):
    """第三方插件扩展点：可选实现任意钩子。"""

    @property
    def meta(self) -> PluginMeta: ...

    def on_start(self, context: PluginContext) -> None: ...

    def on_tick(self, context: PluginContext, tick: int) -> None: ...

    def on_message(self, context: PluginContext, chat: str, content: str) -> None: ...

    def on_stop(self, context: PluginContext) -> None: ...


class PluginManager:
    """注册/调度插件；单个插件异常被隔离并记录，不影响主循环。"""

    def __init__(self) -> None:
        self._plugins: dict[str, Any] = {}
        self._errors: list[str] = []
        self._calls = 0

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(self._errors)

    @property
    def calls(self) -> int:
        return self._calls

    def register(self, plugin: Any) -> None:
        name = plugin.meta.name
        if name in self._plugins:
            raise ValueError(f"插件已注册：{name}")
        self._plugins[name] = plugin

    def unregister(self, name: str) -> bool:
        return self._plugins.pop(name, None) is not None

    def get(self, name: str) -> Any | None:
        return self._plugins.get(name)

    def plugins(self) -> tuple[PluginMeta, ...]:
        return tuple(plugin.meta for plugin in self._plugins.values())

    def dispatch(self, hook: str, context: PluginContext, *args: Any) -> int:
        """按注册顺序调用；返回成功次数。异常注入 ``_errors``。"""
        successes = 0
        for name, plugin in list(self._plugins.items()):
            callback: Callable[..., Any] | None = getattr(plugin, hook, None)
            if callback is None:
                continue
            self._calls += 1
            try:
                callback(context, *args)
            except Exception as exc:  # noqa: BLE001 - 插件故障隔离
                self._errors.append(f"{name}.{hook}: {type(exc).__name__}: {exc}")
                continue
            successes += 1
        return successes
