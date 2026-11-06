"""解析策略框架（M2-04，平台无关）：策略注册与分发。

平台适配器只提供策略**数据**（parser_pack）；执行器统一在本模块，
应用层不得再写平台分支（M0-F-05 架构约束）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from vrpa.errors import TreeConfigError

__all__ = ["ParseResult", "ParsedMessage", "StrategyDispatcher", "StrategyFn"]

StrategyFn = Callable[[str], Sequence["ParsedMessage"]]


@dataclass(frozen=True)
class ParsedMessage:
    """一条解析结果（平台无关字段）。"""

    content: str
    sender: str | None = None
    ts: str | None = None
    confidence: float = 1.0
    strategy: str = ""


@dataclass(frozen=True)
class ParseResult:
    """一次解析的完整结果。"""

    messages: tuple[ParsedMessage, ...] = ()
    strategy: str = ""
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return bool(self.messages)


class StrategyDispatcher:
    """按声明顺序尝试策略，返回第一个产出非空结果的结果。"""

    def __init__(self, strategies: Mapping[str, StrategyFn] | Sequence[tuple[str, StrategyFn]]) -> None:
        items = dict(strategies.items()) if isinstance(strategies, Mapping) else dict(strategies)
        if not items:
            raise TreeConfigError("解析器至少需要一个策略")
        self._strategies = tuple(items.items())

    @property
    def strategy_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self._strategies)

    def parse(self, text: str) -> ParseResult:
        if not text.strip():
            return ParseResult(warnings=("输入文本为空",))
        last_error = "所有策略均产出空结果"
        for name, strategy in self._strategies:
            try:
                messages = tuple(strategy(text))
            except Exception as exc:  # noqa: BLE001 - 单策略失败降级尝试下一个
                last_error = f"{name}: {exc}"
                continue
            if messages:
                return ParseResult(messages=messages, strategy=name)
        return ParseResult(warnings=(f"所有策略均未产出消息（最后错误：{last_error}）",))
