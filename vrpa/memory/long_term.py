"""长期档案库（M3-05，平台无关）：候选提炼 + 幂等写入 + 召回。

注意：本模块的 ``extract_candidates`` 是**规则提取器**（确定性、可测试）；
M5 接入 LLM 后可在其前/后串联更高质量的提取器，接口保持不变。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from vrpa.ports import MemoryItem, MemoryStore, Message

__all__ = [
    "MemoryCandidate",
    "LongTermMemory",
    "extract_candidates",
    "RULES",
]

CATEGORIES = frozenset({"profile", "preference", "event", "relation", "rule", "summary"})


@dataclass(frozen=True)
class MemoryCandidate:
    """待写入档案库的候选条目。"""

    content: str
    category: str = "event"
    key: str | None = None
    confidence: float = 0.6
    importance: float = 0.5
    source_msg_ids: tuple[int, ...] = ()


# (正则, category, key 模板)；key 用于幂等 upsert，避免同类事实反复堆叠
RULES: tuple[tuple[re.Pattern[str], str, str | None], ...] = (
    (re.compile(r"我喜欢(.{1,30})"), "preference", "喜欢"),
    (re.compile(r"我不喜欢(.{1,30})"), "preference", "不喜欢"),
    (re.compile(r"我爱吃(.{1,30})"), "preference", "爱吃"),
    (re.compile(r"我叫(.{1,20})"), "profile", "称呼"),
    (re.compile(r"我的生日(?:是|在)?(.{1,20})"), "profile", "生日"),
    (re.compile(r"我住在(.{1,30})"), "profile", "居住地"),
    (re.compile(r"我的工作(?:是|在)?(.{1,30})"), "profile", "工作"),
    (re.compile(r"记住[:：]?(.{1,120})"), "rule", "记住"),
)


def extract_candidates(messages: Sequence[Message]) -> tuple[MemoryCandidate, ...]:
    """规则提取：从消息文本中抽取长期记忆候选（确定性）。"""
    candidates: list[MemoryCandidate] = []
    seen: set[tuple[str, str | None]] = set()
    for message in messages:
        text = message.content.strip()
        if not text:
            continue
        for pattern, category, key in RULES:
            match = pattern.search(text)
            if match is None:
                continue
            if (category, key) in seen:
                continue
            seen.add((category, key))
            candidates.append(
                MemoryCandidate(
                    content=text[:200],
                    category=category,
                    key=key,
                    confidence=0.6,
                    importance=0.6 if category in {"profile", "preference"} else 0.5,
                )
            )
    return tuple(candidates)


class LongTermMemory:
    """基于 ``MemoryStore`` 端口的档案库服务。"""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def remember(
        self,
        candidates: Sequence[MemoryCandidate],
        *,
        chat: str | None = None,
    ) -> tuple[int, ...]:
        """幂等写入（按 key upsert），返回 memory_id 列表。"""
        ids: list[int] = []
        for candidate in candidates:
            if candidate.category not in CATEGORIES:
                raise ValueError(f"未知记忆分类：{candidate.category}")
            item = MemoryItem(
                content=candidate.content,
                category=candidate.category,
                chat=chat,
                key=candidate.key,
                confidence=candidate.confidence,
                importance=candidate.importance,
            )
            ids.append(int(self._store.add_memory(item)))
        return tuple(ids)

    def extract_and_remember(
        self,
        messages: Sequence[Message],
        *,
        chat: str | None = None,
    ) -> tuple[int, ...]:
        return self.remember(extract_candidates(messages), chat=chat)

    def recall(self, query: str, *, chat: str | None = None, top_k: int = 6) -> tuple[MemoryItem, ...]:
        return tuple(self._store.recall(chat, query, top_k))

    def forget(self, memory_id: int) -> bool:
        return bool(self._store.forget(memory_id))
