"""微信消息解析器（M2-04）：剪贴板文本 -> IncomingMessage 列表。

红线 R3：解析器只接受**文本**，不做任何图像识别/OCR。
支持三种策略（与适配器 parser_pack 对齐）：
    timestamp_prefix   行首日期/时间 + 发送者 + 内容（微信复制常见格式）
    sender_colon       发送者: 内容
    multi_line_block   空行分块，首行发送者，其余为内容
无前缀的续行自动并入上一条消息内容。
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from vrpa.parsing import ParsedMessage, StrategyDispatcher
from vrpa.ports import IncomingMessage

__all__ = [
    "PARSER_STRATEGIES",
    "WeChatParser",
    "parse_block",
    "parse_sender_colon",
    "parse_timestamp_prefix",
]

PARSER_STRATEGIES = ("timestamp_prefix", "sender_colon", "multi_line_block")

_TIMESTAMP = r"(?:\d{4}-\d{2}-\d{2}\s+)?\d{1,2}:\d{2}(?::\d{2})?"
_TIMESTAMP_LINE = re.compile(rf"^(?P<ts>{_TIMESTAMP})\s+(?P<sender>[^:：]{{1,40}}?)\s*[:：]\s?(?P<content>.*)$")
_SENDER_LINE = re.compile(r"^(?P<sender>[^:：]{1,40}?)\s*[:：]\s?(?P<content>.*)$")
_SYSTEM_HINTS = ("以下为新消息", "以上是历史消息", "查看更多消息")


def _split_blocks(text: str) -> list[tuple[str | None, str | None, str]]:
    """按行解析，返回 (ts, sender, content)；无前缀续行并入上一条内容。"""
    rows: list[tuple[str | None, str | None, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if any(hint in line for hint in _SYSTEM_HINTS):
            continue
        match = _TIMESTAMP_LINE.match(line)
        if match is not None:
            rows.append((match.group("ts"), match.group("sender").strip(), match.group("content")))
            continue
        match = _SENDER_LINE.match(line)
        if match is not None:
            rows.append((None, match.group("sender").strip(), match.group("content")))
            continue
        if rows:
            ts, sender, content = rows[-1]
            rows[-1] = (ts, sender, f"{content}\n{line}".strip())
    return rows


def parse_timestamp_prefix(text: str) -> Sequence[ParsedMessage]:
    """仅接受带时间戳前缀的行。"""
    rows = [row for row in _split_blocks(text) if row[0] is not None]
    return tuple(
        ParsedMessage(content=content, sender=sender, ts=ts, confidence=0.95, strategy="timestamp_prefix")
        for ts, sender, content in rows
        if content
    )


def parse_sender_colon(text: str) -> Sequence[ParsedMessage]:
    """日期/时间前缀可有可无的「发送者: 内容」格式。"""
    rows = _split_blocks(text)
    return tuple(
        ParsedMessage(content=content, sender=sender, ts=ts, confidence=0.9, strategy="sender_colon")
        for ts, sender, content in rows
        if content and sender
    )


def parse_block(text: str) -> Sequence[ParsedMessage]:
    """空行分块：首行 sender[: 内容]，其余行并入 content。"""
    messages: list[ParsedMessage] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        head = lines[0]
        match = _SENDER_LINE.match(head) or _TIMESTAMP_LINE.match(head)
        if match is None:
            continue
        sender = match.group("sender").strip() if "sender" in match.groupdict() else None
        ts = match.group("ts") if (match.groupdict().get("ts") is not None) else None
        content = match.group("content")
        if len(lines) > 1:
            content = "\n".join([content, *lines[1:]])
        messages.append(
            ParsedMessage(
                content=content.strip(),
                sender=sender,
                ts=ts,
                confidence=0.75,
                strategy="multi_line_block",
            )
        )
    return tuple(message for message in messages if message.content)


class WeChatParser:
    """微信剪贴板文本解析器（策略执行由框架 StrategyDispatcher 统一分发）。"""

    def __init__(self, order: Sequence[str] = PARSER_STRATEGIES) -> None:
        strategies = {
            "timestamp_prefix": parse_timestamp_prefix,
            "sender_colon": parse_sender_colon,
            "multi_line_block": parse_block,
        }
        if not set(order) <= set(strategies):
            raise ValueError(f"未知解析策略：{sorted(set(order) - set(strategies))}")
        self._dispatcher = StrategyDispatcher([(name, strategies[name]) for name in order])

    @property
    def strategy_names(self) -> tuple[str, ...]:
        return self._dispatcher.strategy_names

    def parse(self, text: str) -> tuple[IncomingMessage, ...]:
        result = self._dispatcher.parse(text)
        return tuple(
            IncomingMessage(
                content=message.content,
                sender=message.sender,
                ts=message.ts,
                confidence=message.confidence,
                reason=message.strategy,
            )
            for message in result.messages
        )
