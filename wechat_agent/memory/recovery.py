"""未回复消息恢复：live 进程重启后，把最近未回复的入向消息重新入队。"""

from __future__ import annotations

from datetime import datetime, timedelta

from vrpa.errors import DBError
from vrpa.memory.history import HistoryRecord, HistoryStore

__all__ = ["unanswered_incoming"]

_RESPONSE_DIRECTIONS = frozenset({"out", "self"})


def _parse_created(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def unanswered_incoming(
    history: HistoryStore,
    chat: str,
    *,
    limit: int = 5,
    max_age_minutes: int = 30,
    now: datetime | None = None,
) -> tuple[HistoryRecord, ...]:
    """返回最后一次回复之后、仍在时效内的入向消息（旧 -> 新）。"""
    if limit <= 0:
        return ()
    try:
        records = history.recent(chat, max(limit * 4, limit))
    except DBError:
        return ()
    if not records:
        return ()
    last_response = -1
    for index, record in enumerate(records):
        if record.direction in _RESPONSE_DIRECTIONS:
            last_response = index
    pending = [record for record in records[last_response + 1 :] if record.direction == "in" and record.status == "ok"]
    if not pending:
        return ()
    current = now or datetime.now()
    threshold = current - timedelta(minutes=max(0, max_age_minutes))
    fresh = [
        record for record in pending if (created := _parse_created(record.created_at)) is None or created >= threshold
    ]
    return tuple(fresh[-limit:])
