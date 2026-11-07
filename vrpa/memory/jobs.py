"""长期记忆提炼异步 job（M3-06，平台无关）。

异步模型：SQLite ``tasks`` 表作为持久队列；主循环（M4）周期性调用
``MemoryExtractJob.run_pending()``，本模块不自行起线程。
特性：幂等入队、失败重试（指数退避可配）、最大尝试次数、可取消。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from vrpa.errors import DBError
from vrpa.memory.db import Databases
from vrpa.memory.long_term import LongTermMemory, MemoryCandidate
from vrpa.ports import Message

__all__ = ["MemoryExtractJob", "Task", "TaskQueue"]

TASK_TYPE_MEMORY_EXTRACT = "memory_extract"


def _now() -> datetime:
    return datetime.now()


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


@dataclass(frozen=True)
class Task:
    """tasks 表读模型。"""

    id: int
    task_type: str
    payload: dict[str, Any]
    state: str
    attempts: int
    last_error: str | None
    run_at: str | None
    created_at: str


class TaskQueue:
    """基于 chat_history.tasks 的持久任务队列。"""

    def __init__(self, databases: Databases, *, now: Callable[[], datetime] = _now) -> None:
        self._databases = databases
        self._now = now

    # ------------------------------------------------------------ 入队
    def enqueue(
        self,
        task_type: str,
        payload: dict[str, Any],
        *,
        run_at: datetime | None = None,
        dedupe_key: str | None = None,
    ) -> int:
        connection = self._databases.history
        if dedupe_key is not None:
            payload = {**payload, "dedupe_key": dedupe_key}
            row = connection.execute(
                "SELECT id FROM tasks WHERE type = ? AND state IN ('pending','running') "
                "AND payload LIKE ? ORDER BY id DESC LIMIT 1",
                (task_type, f"%{dedupe_key}%"),
            ).fetchone()
            if row is not None:
                return int(row[0])
        cursor = connection.execute(
            "INSERT INTO tasks(type, payload, state, run_at) VALUES(?,?,?,?)",
            (task_type, json.dumps(payload, ensure_ascii=False), "pending", _iso(run_at) if run_at else None),
        )
        connection.commit()
        return int(cursor.lastrowid or 0)

    # ------------------------------------------------------------ 领取 / 完成
    def pending(self, *, limit: int = 10) -> tuple[Task, ...]:
        now_iso = _iso(self._now())
        rows = self._databases.history.execute(
            "SELECT id, type, payload, state, attempts, last_error, run_at, created_at FROM tasks "
            "WHERE state = 'pending' AND (run_at IS NULL OR run_at <= ?) ORDER BY id LIMIT ?",
            (now_iso, limit),
        ).fetchall()
        return tuple(self._to_task(row) for row in rows)

    def claim(self, task_id: int) -> bool:
        connection = self._databases.history
        cursor = connection.execute("UPDATE tasks SET state = 'running' WHERE id = ? AND state = 'pending'", (task_id,))
        connection.commit()
        return cursor.rowcount > 0

    def complete(self, task_id: int) -> None:
        connection = self._databases.history
        connection.execute("UPDATE tasks SET state = 'done', last_error = NULL WHERE id = ?", (task_id,))
        connection.commit()

    def fail(
        self,
        task_id: int,
        error: str,
        *,
        retry_delay: float = 60.0,
        max_attempts: int = 3,
    ) -> str:
        """记录失败：未达上限则退避重试，否则标记 failed。返回新状态。"""
        connection = self._databases.history
        row = connection.execute("SELECT attempts FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise DBError(f"任务不存在：{task_id}")
        attempts = int(row[0]) + 1
        if attempts >= max_attempts:
            connection.execute(
                "UPDATE tasks SET state = 'failed', attempts = ?, last_error = ? WHERE id = ?",
                (attempts, error[:500], task_id),
            )
            new_state = "failed"
        else:
            retry_at = _iso(self._now() + timedelta(seconds=retry_delay))
            connection.execute(
                "UPDATE tasks SET state = 'pending', attempts = ?, last_error = ?, run_at = ? WHERE id = ?",
                (attempts, error[:500], retry_at, task_id),
            )
            new_state = "pending"
        connection.commit()
        return new_state

    def cancel(self, task_id: int) -> bool:
        connection = self._databases.history
        cursor = connection.execute(
            "UPDATE tasks SET state = 'cancelled' WHERE id = ? AND state IN ('pending','running')", (task_id,)
        )
        connection.commit()
        return cursor.rowcount > 0

    def get(self, task_id: int) -> Task | None:
        row = self._databases.history.execute(
            "SELECT id, type, payload, state, attempts, last_error, run_at, created_at FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        return None if row is None else self._to_task(row)

    def counts(self) -> dict[str, int]:
        rows = self._databases.history.execute("SELECT state, COUNT(*) FROM tasks GROUP BY state").fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    @staticmethod
    def _to_task(row: tuple[Any, ...]) -> Task:
        payload = json.loads(row[2]) if row[2] else {}
        return Task(
            id=int(row[0]),
            task_type=str(row[1]),
            payload=payload,
            state=str(row[3]),
            attempts=int(row[4]),
            last_error=None if row[5] is None else str(row[5]),
            run_at=None if row[6] is None else str(row[6]),
            created_at=str(row[7]),
        )


class MemoryExtractJob:
    """长期记忆提炼任务：从流水消息中提取候选并写入档案库。"""

    def __init__(
        self,
        queue: TaskQueue,
        memory: LongTermMemory,
        *,
        extractor: Callable[[Sequence[Message]], Sequence[MemoryCandidate]] | None = None,
        max_attempts: int = 3,
        retry_delay: float = 60.0,
    ) -> None:
        if extractor is None:
            raise ValueError("MemoryExtractJob 需要显式 extractor（生产请注入 LLMMemorySelector）")
        self._queue = queue
        self._memory = memory
        self._extractor = extractor
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay

    def enqueue(self, chat: str, messages: Sequence[Message], *, dedupe_key: str | None = None) -> int:
        payload = {
            "chat": chat,
            "messages": [
                {
                    "direction": message.direction,
                    "content": message.content,
                    "role": message.role,
                    "sender": message.sender,
                    "ts": message.ts,
                    "source": message.source,
                    "status": message.status,
                }
                for message in messages
            ],
        }
        return self._queue.enqueue(TASK_TYPE_MEMORY_EXTRACT, payload, dedupe_key=dedupe_key)

    def run_once(self) -> bool:
        """处理一个任务；无待处理任务返回 False。"""
        tasks = self._queue.pending(limit=1)
        if not tasks:
            return False
        task = tasks[0]
        if not self._queue.claim(task.id):
            return False
        try:
            chat = str(task.payload.get("chat") or "")
            raw_messages = task.payload.get("messages") or []
            messages = [
                Message(
                    direction=str(item.get("direction", "in")),
                    content=str(item.get("content", "")),
                    role=str(item.get("role") or "user"),
                    sender=item.get("sender"),
                    ts=item.get("ts"),
                    source=str(item.get("source", "rpa_capture")),
                    status=str(item.get("status", "ok")),
                )
                for item in raw_messages
            ]
            candidates = tuple(self._extractor(messages))
            self._memory.remember(candidates, chat=chat or None)
        except Exception as exc:  # noqa: BLE001 - 失败必须落库并重试
            self._queue.fail(
                task.id,
                f"{type(exc).__name__}: {exc}",
                retry_delay=self._retry_delay,
                max_attempts=self._max_attempts,
            )
            return True
        self._queue.complete(task.id)
        return True

    def run_pending(self, *, limit: int = 100) -> int:
        """同步跑完当前待处理任务，返回处理数量（主循环可反复调用）。"""
        processed = 0
        for _ in range(limit):
            if not self.run_once():
                break
            processed += 1
        return processed

    def run_until_idle(self, *, max_rounds: int = 1000, interval: float = 0.0) -> int:
        """兼容后台线程的节流循环：无任务即退出。"""
        processed = 0
        for _ in range(max_rounds):
            if not self.run_once():
                break
            processed += 1
            if interval > 0:
                time.sleep(interval)
        return processed
