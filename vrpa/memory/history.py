"""流水库读写 API（M3-01，平台无关）：chat_history 的仓储层。

只封装 SQL；去重对齐、多端识别、入库编排在 ``vrpa.memory.dedup`` 与
应用层入库编排（pipeline）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from vrpa.errors import DBError
from vrpa.memory.db import Databases
from vrpa.memory.store import content_hash, normalize_text

__all__ = ["ChatRecord", "HistoryRecord", "HistoryStore"]

_COLUMNS = (
    "m.id, c.name, m.direction, m.content, m.role, m.sender_name, m.msg_ts, "
    "m.source, m.status, m.content_hash, m.dedup_count, m.created_at"
)


@dataclass(frozen=True)
class HistoryRecord:
    """一条流水记录（读模型）。"""

    id: int
    chat: str
    direction: str
    content: str
    role: str | None
    sender: str | None
    ts: str | None
    source: str
    status: str
    content_hash: str
    dedup_count: int
    created_at: str = ""


@dataclass(frozen=True)
class ChatRecord:
    """会话记录。"""

    id: int
    name: str
    chat_type: str
    enabled: bool
    auto_reply: bool


class HistoryStore:
    """chat_history 读写门面。"""

    def __init__(self, databases: Databases) -> None:
        self._databases = databases

    # ------------------------------------------------------------ 会话
    def ensure_chat(self, name: str, *, chat_type: str = "private", auto_reply: bool = True) -> int:
        connection = self._databases.history
        row = connection.execute("SELECT id FROM chats WHERE name = ?", (name,)).fetchone()
        if row is not None:
            return int(row[0])
        cursor = connection.execute(
            "INSERT INTO chats(name, type, auto_reply) VALUES(?,?,?)",
            (name, chat_type, 1 if auto_reply else 0),
        )
        connection.commit()
        return int(cursor.lastrowid or 0)

    def get_chat(self, name: str) -> ChatRecord | None:
        row = self._databases.history.execute(
            "SELECT id, name, type, enabled, auto_reply FROM chats WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        return ChatRecord(
            id=int(row[0]),
            name=str(row[1]),
            chat_type=str(row[2]),
            enabled=bool(row[3]),
            auto_reply=bool(row[4]),
        )

    def chat_id(self, name: str) -> int:
        row = self._databases.history.execute("SELECT id FROM chats WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise DBError(f"会话不存在：{name!r}（先 ensure_chat）")
        return int(row[0])

    # ------------------------------------------------------------ 写入
    def append(
        self,
        chat: str,
        content: str,
        *,
        direction: str = "in",
        role: str | None = None,
        sender: str | None = None,
        ts: str | None = None,
        source: str = "rpa_capture",
        status: str = "ok",
        raw_meta: dict[str, Any] | None = None,
    ) -> int:
        chat_id = self.ensure_chat(chat)
        normalized = normalize_text(content)
        text_hash = content_hash(content)
        dedup_count = int(
            self._databases.history.execute(
                "SELECT COUNT(*) FROM messages WHERE chat_id = ? AND content_hash = ?", (chat_id, text_hash)
            ).fetchone()[0]
        )
        cursor = self._databases.history.execute(
            "INSERT INTO messages("
            "chat_id, direction, sender_name, role, content, norm_text, content_hash, msg_ts, "
            "source, status, dedup_count, raw_meta"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                chat_id,
                direction,
                sender,
                role,
                content,
                normalized,
                text_hash,
                ts,
                source,
                status,
                dedup_count + 1,
                json.dumps(raw_meta, ensure_ascii=False) if raw_meta else None,
            ),
        )
        self._databases.history.execute("UPDATE chats SET last_msg_hash = ? WHERE id = ?", (text_hash, chat_id))
        self._databases.history.commit()
        return int(cursor.lastrowid or 0)

    def update_status(self, message_id: int, status: str) -> bool:
        cursor = self._databases.history.execute("UPDATE messages SET status = ? WHERE id = ?", (status, message_id))
        self._databases.history.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------ 读取
    def get(self, message_id: int) -> HistoryRecord | None:
        row = self._databases.history.execute(
            f"SELECT {_COLUMNS} FROM messages m JOIN chats c ON c.id = m.chat_id WHERE m.id = ?",
            (message_id,),
        ).fetchone()
        return None if row is None else self._to_record(row)

    def last(self, chat: str) -> HistoryRecord | None:
        chat_id = self.chat_id(chat)
        row = self._databases.history.execute(
            f"SELECT {_COLUMNS} FROM messages m JOIN chats c ON c.id = m.chat_id "
            "WHERE m.chat_id = ? ORDER BY m.id DESC LIMIT 1",
            (chat_id,),
        ).fetchone()
        return None if row is None else self._to_record(row)

    def recent(self, chat: str, limit: int) -> tuple[HistoryRecord, ...]:
        if limit <= 0:
            return ()
        chat_id = self.chat_id(chat)
        rows = self._databases.history.execute(
            f"SELECT {_COLUMNS} FROM messages m JOIN chats c ON c.id = m.chat_id "
            "WHERE m.chat_id = ? AND m.status = 'ok' ORDER BY m.id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        return tuple(self._to_record(row) for row in reversed(rows))

    def tail_hashes(self, chat: str, limit: int) -> tuple[str, ...]:
        """尾部锚点哈希（旧 -> 新）。"""
        return tuple(record.content_hash for record in self.recent(chat, limit))

    def count(self, chat: str) -> int:
        chat_id = self.chat_id(chat)
        row = self._databases.history.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ?", (chat_id,)).fetchone()
        return int(row[0])

    @staticmethod
    def _to_record(row: tuple[Any, ...]) -> HistoryRecord:
        return HistoryRecord(
            id=int(row[0]),
            chat=str(row[1]),
            direction=str(row[2]),
            content=str(row[3]),
            role=None if row[4] is None else str(row[4]),
            sender=None if row[5] is None else str(row[5]),
            ts=None if row[6] is None else str(row[6]),
            source=str(row[7]),
            status=str(row[8]),
            content_hash=str(row[9]),
            dedup_count=int(row[10]),
            created_at=str(row[11]),
        )
