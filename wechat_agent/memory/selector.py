"""LLM 记忆筛选器：只提炼“真正会记在心里”的内容，替代规则硬提取。"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from vrpa.llm.client import LLMClient
from vrpa.memory.long_term import CATEGORIES, MemoryCandidate
from vrpa.ports import Message

__all__ = ["LLMMemorySelector", "SELECTION_SYSTEM_PROMPT", "parse_candidates"]

_SELECTION_PROMPT = """你是一个真实的人，正在回顾与对方的聊天记录。
只提取你真正会记在心里的内容：
- 对方的情绪/状态/近况
- 重要约定、时间、计划
- 特殊喜好、习惯、禁忌
- 关系变化、明确要求你记住的事

忽略：寒暄、测试串、“吃了吗”、“哈哈”、重复内容、助手自己的客套。
不要逐字摘抄整段对话；每条记忆用一句自然语言概括。
没有值得记住的内容时返回空数组 []。

只输出 JSON 数组，不要 Markdown 代码块。每项字段：
{"content": "一句记忆", "category": "profile|preference|event|relation|rule",
 "importance": 0.0-1.0, "confidence": 0.0-1.0, "key": "可选稳定键"}
最多 8 条。"""

SELECTION_SYSTEM_PROMPT = _SELECTION_PROMPT
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _transcript(messages: Sequence[Message]) -> str:
    lines: list[str] = []
    for message in messages:
        if message.status != "ok" or not message.content.strip():
            continue
        who = "我" if message.role == "assistant" or message.direction in {"out", "self"} else "对方"
        lines.append(f"{who}: {message.content.strip()[:500]}")
    return "\n".join(lines)


def _clamp(value: object, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def parse_candidates(text: str) -> tuple[MemoryCandidate, ...]:
    """解析 LLM JSON；任何异常由调用方转成 job 失败重试。"""
    raw = text.strip()
    fence = _FENCE.search(raw)
    if fence is not None:
        raw = fence.group(1).strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("记忆筛选输出缺少 JSON 数组")
    data = json.loads(raw[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("记忆筛选输出必须是数组")
    result: list[MemoryCandidate] = []
    for item in data[:8]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        category = str(item.get("category", "event")).strip()
        if not content or category not in CATEGORIES:
            continue
        key = item.get("key")
        result.append(
            MemoryCandidate(
                content=content[:200],
                category=category,
                key=str(key).strip() if key else None,
                confidence=_clamp(item.get("confidence"), 0.6),
                importance=_clamp(item.get("importance"), 0.5),
            )
        )
    return tuple(result)


class LLMMemorySelector:
    """实现 ``MemoryExtractJob`` 的 extractor 签名（同步调用 LLM）。"""

    def __init__(self, client: LLMClient, *, max_items: int = 8) -> None:
        self._client = client
        self._max_items = max(1, max_items)

    def __call__(self, messages: Sequence[Message]) -> tuple[MemoryCandidate, ...]:
        transcript = _transcript(messages)
        if not transcript.strip():
            return ()
        response = self._client.complete(
            [
                {"role": "system", "content": SELECTION_SYSTEM_PROMPT},
                {"role": "user", "content": f"聊天记录：\n{transcript}"},
            ],
            temperature=0.2,
            max_tokens=500,
        )
        return parse_candidates(response.text)[: self._max_items]


def selector_from_config(config: Any) -> LLMMemorySelector:
    client = LLMClient(
        api_key=config.api_key(),
        base_url=config.llm.base_url,
        model=config.llm.model,
        timeout=config.llm.timeout,
        retries=config.llm.retries,
    )
    return LLMMemorySelector(client)
