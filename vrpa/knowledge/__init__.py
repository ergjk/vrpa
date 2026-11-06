"""知识层（平台无关）：只读知识块、Provider 协议、检索与防注入组装。

红线：知识仅来自静态只读文件/第三方 Provider，**绝不写入 memory.db**。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = [
    "KNOWLEDGE_SCOPES",
    "KnowledgeBase",
    "FileKnowledgeProvider",
    "KnowledgeChunk",
    "KnowledgeProvider",
    "keywords",
]

KNOWLEDGE_SCOPES = ("chat", "global")
_TOKEN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}")


def keywords(query: str) -> tuple[str, ...]:
    """把查询切分为关键词（中文连续串/英文数字词），用于检索。"""
    return tuple(dict.fromkeys(_TOKEN.findall(query or "")))


@dataclass(frozen=True)
class KnowledgeChunk:
    """一块只读知识。scope=chat 为专属知识，global 为全局知识。"""

    scope: str
    title: str
    content: str
    source: str = ""

    def __post_init__(self) -> None:
        if self.scope not in KNOWLEDGE_SCOPES:
            raise ValueError(f"未知知识作用域：{self.scope!r}")


@runtime_checkable
class KnowledgeProvider(Protocol):
    """第三方扩展点：返回知识块（文件/数据库/API 均可，但只读）。"""

    def chunks(self, chat_id: str | None = None) -> Sequence[KnowledgeChunk]:
        """返回全局 + 指定会话的专属知识。"""
        ...

    def reload(self) -> None:
        """使缓存失效（热加载）。"""
        ...


class KnowledgeBase:
    """检索门面：按关键词/标题过滤，限额限长，禁止无脑全量塞入。"""

    def __init__(
        self,
        provider: KnowledgeProvider,
        *,
        max_chunks: int = 6,
        max_chars: int = 2000,
    ) -> None:
        self._provider = provider
        self._max_chunks = max(1, int(max_chunks))
        self._max_chars = max(50, int(max_chars))

    def reload(self) -> None:
        self._provider.reload()

    def list(self, chat_id: str | None = None) -> tuple[KnowledgeChunk, ...]:
        return tuple(self._provider.chunks(chat_id))

    def select(
        self,
        chat_id: str | None,
        query: str,
        *,
        limit: int | None = None,
    ) -> tuple[KnowledgeChunk, ...]:
        """关键词/标题命中才返回；query 为空返回空（不默认全量）。"""
        terms = keywords(query)
        if not terms:
            return ()
        expanded = list(terms)
        for term in terms:
            if len(term) > 2 and all("\u4e00" <= char <= "\u9fff" for char in term):
                expanded.extend(term[index : index + 2] for index in range(len(term) - 1))
        terms = tuple(dict.fromkeys(expanded))
        scored: list[tuple[int, KnowledgeChunk]] = []
        for chunk in self._provider.chunks(chat_id):
            haystack = f"{chunk.title}\n{chunk.content}"
            score = sum(haystack.count(term) for term in terms) + sum(2 for term in terms if term in chunk.title)
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda item: (-item[0], item[1].scope, item[1].title))
        capped: list[KnowledgeChunk] = []
        used = 0
        max_chunks = min(self._max_chunks, max(1, int(limit))) if limit else self._max_chunks
        for _score, chunk in scored:
            if len(capped) >= max_chunks:
                break
            remaining = self._max_chars - used
            if remaining <= 0:
                break
            content = chunk.content
            if len(content) > remaining:
                content = content[: max(1, remaining - 1)].rstrip() + "…"
            capped.append(
                KnowledgeChunk(
                    scope=chunk.scope,
                    title=chunk.title,
                    content=content,
                    source=chunk.source,
                )
            )
            used += len(content)
        return tuple(capped)


from vrpa.knowledge.files import FileKnowledgeProvider  # noqa: E402  (避免循环导入)
