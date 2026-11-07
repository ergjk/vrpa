"""通用 SQLite MemoryStore：双库实现 ``vrpa.ports.MemoryStore``（平台无关，M0-F-05）。

说明：
    - 复用现有双库（chat_history / memory）与 ``init_databases``，不新增表；
    - 去重对齐、direction 判定等 M3 业务细化在 M3 补齐，本层先保证端口契约可用；
    - ``close()`` 用于释放 SQLite 句柄（Windows 文件锁友好），端到端编排由调用方负责关闭。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path

from vrpa.memory.db import Databases, init_databases
from vrpa.ports import IncomingMessage, MemoryItem, Message

_WHITESPACE_RE = re.compile(r"\s+")

_MESSAGE_COLUMNS = "direction, content, role, sender_name, msg_ts, source, status"


def normalize_text(text: str) -> str:
    """规范化：折叠空白 + 转小写（与 DB norm_text 语义一致）。"""
    return _WHITESPACE_RE.sub(" ", text).strip().lower()


def content_hash(text: str) -> str:
    """与 DB 约定一致的 16 位内容哈希（sha1 前缀）。"""
    return hashlib.sha1(normalize_text(text).encode("utf-8")).hexdigest()[:16]


class SQLiteMemoryStore:
    """双库门面（实现 ``vrpa.ports.MemoryStore``）。"""

    def __init__(self, data_dir: str | Path) -> None:
        self._databases: Databases = init_databases(data_dir)

    # ------------------------------------------------------------ 生命周期
    @property
    def databases(self) -> Databases:
        return self._databases

    def close(self) -> None:
        self._databases.close()

    def __enter__(self) -> SQLiteMemoryStore:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------ 内部工具
    def _chat_id(self, chat: str) -> int:
        connection = self._databases.history
        row = connection.execute("SELECT id FROM chats WHERE name = ?", (chat,)).fetchone()
        if row is not None:
            return int(row[0])
        cursor = connection.execute("INSERT INTO chats(name) VALUES(?)", (chat,))
        connection.commit()
        return int(cursor.lastrowid or 0)

    def _insert_message(
        self,
        chat_id: int,
        *,
        direction: str,
        content: str,
        role: str | None,
        sender: str | None,
        msg_ts: str | None,
        source: str,
        status: str,
        raw_meta: dict[str, object] | None = None,
    ) -> int:
        normalized = normalize_text(content)
        cursor = self._databases.history.execute(
            "INSERT INTO messages("
            "chat_id, direction, sender_name, role, content, norm_text, content_hash, "
            "msg_ts, source, status, raw_meta"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                chat_id,
                direction,
                sender,
                role,
                content,
                normalized,
                content_hash(content),
                msg_ts,
                source,
                status,
                json.dumps(raw_meta, ensure_ascii=False) if raw_meta else None,
            ),
        )
        self._databases.history.execute(
            "UPDATE chats SET last_msg_hash = ? WHERE id = ?",
            (content_hash(content), chat_id),
        )
        self._databases.history.commit()
        return int(cursor.lastrowid or 0)

    # ------------------------------------------------------------ MemoryStore
    def recent_hashes(self, session: str, limit: int) -> Sequence[str]:
        if limit <= 0:
            return ()
        chat_id = self._chat_id(session)
        rows = self._databases.history.execute(
            "SELECT content_hash FROM messages WHERE chat_id = ? AND status = 'ok' ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        return tuple(str(row[0]) for row in reversed(rows))

    def insert_messages(self, session: str, messages: Sequence[IncomingMessage]) -> int:
        chat_id = self._chat_id(session)
        for item in messages:
            self._insert_message(
                chat_id,
                direction="in",
                content=item.content,
                role=None,
                sender=item.sender,
                msg_ts=item.ts,
                source="rpa_capture",
                status="ok",
                raw_meta={"confidence": item.confidence, "reason": item.reason},
            )
        return len(messages)

    def writeback(self, session: str, text: str) -> int:
        chat_id = self._chat_id(session)
        return self._insert_message(
            chat_id,
            direction="out",
            content=text,
            role="assistant",
            sender=None,
            msg_ts=None,
            source="self_writeback",
            status="ok",
        )

    def history(self, session: str, limit: int) -> Sequence[Message]:
        if limit <= 0:
            return ()
        chat_id = self._chat_id(session)
        rows = self._databases.history.execute(
            f"SELECT {_MESSAGE_COLUMNS} FROM messages WHERE chat_id = ? AND status = 'ok' ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        return tuple(
            Message(
                direction=str(row[0]),
                content=str(row[1]),
                role=str(row[2] or "user"),
                sender=row[3],
                ts=row[4],
                source=str(row[5]),
                status=str(row[6]),
            )
            for row in reversed(rows)
        )

    def _chat_name(self, chat_id: int | None) -> str | None:
        if chat_id is None:
            return None
        row = self._databases.history.execute("SELECT name FROM chats WHERE id = ?", (chat_id,)).fetchone()
        return str(row[0]) if row is not None else None

    def recall(self, session: str | None, query: str, top_k: int) -> Sequence[MemoryItem]:
        if top_k <= 0:
            return ()
        # memories 与 chats 分属两个库（memory / chat_history），不能跨库 JOIN：
        # 先把会话名解析为 chat_history.chats.id，再用 id 过滤。
        sql = (
            "SELECT m.id, m.category, m.mem_key, m.content, m.confidence, m.importance, m.chat_id "
            "FROM memories m WHERE m.deleted = 0"
        )
        params: list[object] = []
        if session is not None:
            sql += " AND (m.chat_id IS NULL OR m.chat_id = ?)"
            params.append(self._chat_id(session))
        if query.strip():
            sql += " AND (m.content LIKE ? OR COALESCE(m.mem_key, '') LIKE ?)"
            like = f"%{query.strip()}%"
            params.extend([like, like])
        sql += " ORDER BY m.importance DESC, m.id DESC LIMIT ?"
        params.append(top_k)
        rows = self._databases.memory.execute(sql, params).fetchall()
        return tuple(
            MemoryItem(
                content=str(row[3]),
                category=str(row[1]),
                chat=self._chat_name(row[6]),
                key=row[2],
                confidence=float(row[4]),
                importance=float(row[5]),
                memory_id=int(row[0]),
            )
            for row in rows
        )

    def add_memory(self, item: MemoryItem) -> int:
        chat_id: int | None = None
        if item.chat is not None:
            chat_id = self._chat_id(item.chat)
        if item.key is not None:
            existing = self._databases.memory.execute(
                "SELECT id FROM memories WHERE deleted = 0 AND mem_key = ? AND chat_id IS ?",
                (item.key, chat_id),
            ).fetchone()
            if existing is not None:
                memory_id = int(existing[0])
                self._databases.memory.execute(
                    "UPDATE memories SET content = ?, category = ?, confidence = ?, importance = ?, "
                    "updated_at = datetime('now', 'localtime') WHERE id = ?",
                    (item.content, item.category, item.confidence, item.importance, memory_id),
                )
                self._databases.memory.commit()
                return memory_id
        cursor = self._databases.memory.execute(
            "INSERT INTO memories(chat_id, category, mem_key, content, confidence, importance) VALUES(?,?,?,?,?,?)",
            (chat_id, item.category, item.key, item.content, item.confidence, item.importance),
        )
        self._databases.memory.commit()
        return int(cursor.lastrowid or 0)

    def forget(self, memory_id: int) -> bool:
        cursor = self._databases.memory.execute(
            "UPDATE memories SET deleted = 1, updated_at = datetime('now', 'localtime') WHERE id = ? AND deleted = 0",
            (memory_id,),
        )
        self._databases.memory.commit()
        return cursor.rowcount > 0
