"""优先级队列（M4-01，平台无关）。

规则：priority 数值越小越优先；同优先级 FIFO；支持按会话阻塞（同会话串行）。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

__all__ = ["MessageQueue", "QueuedMessage"]


@dataclass(frozen=True)
class QueuedMessage:
    """待回复消息。"""

    chat: str
    content: str
    message_id: int | None = None
    priority: int = 5
    enqueued_at: float = field(default_factory=time.monotonic)
    attempts: int = 0
    trace_id: str = ""


class MessageQueue:
    """线程安全的优先级队列。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[int, deque[QueuedMessage]] = {}

    def push(self, item: QueuedMessage) -> None:
        with self._lock:
            self._items.setdefault(item.priority, deque()).append(item)

    def pop(self, *, blocked_chats: set[str] | None = None) -> QueuedMessage | None:
        blocked = blocked_chats or set()
        with self._lock:
            for priority in sorted(self._items):
                bucket = self._items[priority]
                for index, item in enumerate(bucket):
                    if item.chat in blocked:
                        continue
                    del bucket[index]
                    if not bucket:
                        del self._items[priority]
                    return item
        return None

    def peek(self) -> QueuedMessage | None:
        with self._lock:
            for priority in sorted(self._items):
                bucket = self._items[priority]
                if bucket:
                    return bucket[0]
        return None

    def __len__(self) -> int:
        with self._lock:
            return sum(len(bucket) for bucket in self._items.values())

    def chats(self) -> tuple[str, ...]:
        with self._lock:
            seen: list[str] = []
            for bucket in self._items.values():
                for item in bucket:
                    if item.chat not in seen:
                        seen.append(item.chat)
            return tuple(seen)

    def drain(self) -> tuple[QueuedMessage, ...]:
        with self._lock:
            items = [item for priority in sorted(self._items) for item in self._items[priority]]
            self._items.clear()
            return tuple(items)
