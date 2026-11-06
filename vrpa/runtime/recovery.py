"""失败自保与崩溃恢复（M6-03，平台无关）。

能力：
    - ``FailureGuard``：连续失败熔断 + 原子快照（暂停/崩溃原因可审计）；
    - ``RecoveryManager``：启动时恢复快照、把僵尸 ``running`` 任务重置为 ``pending``；
    - 重启次数超限进入安全模式（只读，不自动发送）。
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from vrpa.memory.db import Databases

__all__ = [
    "FailureGuard",
    "RecoveryError",
    "RecoveryManager",
    "RecoveryReport",
    "RuntimeSnapshot",
]


@dataclass(frozen=True)
class RuntimeSnapshot:
    state: str = "idle"
    breaker: str = "closed"
    queue_len: int = 0
    last_chat: str | None = None
    dry_run: bool = True
    updated_at: float = 0.0
    note: str = ""


class RecoveryError(Exception):
    """恢复失败（重启次数超限，进入安全模式）。"""


class FailureGuard:
    """把熔断状态与运行态原子落盘，供崩溃恢复。"""

    def __init__(
        self,
        snapshot_path: Path | str,
        *,
        max_failures: int = 3,
        max_restarts: int = 3,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = Path(snapshot_path)
        self._max_failures = max(1, max_failures)
        self._max_restarts = max(1, max_restarts)
        self._clock = clock
        self._failures = 0
        self._restarts = 0
        self._state = "idle"

    @property
    def path(self) -> Path:
        return self._path

    @property
    def failures(self) -> int:
        return self._failures

    @property
    def restarts(self) -> int:
        return self._restarts

    def save(
        self,
        *,
        state: str,
        breaker: str = "closed",
        queue_len: int = 0,
        last_chat: str | None = None,
        dry_run: bool = True,
        note: str = "",
    ) -> RuntimeSnapshot:
        snapshot = RuntimeSnapshot(
            state=state,
            breaker=breaker,
            queue_len=queue_len,
            last_chat=last_chat,
            dry_run=dry_run,
            updated_at=self._clock(),
            note=note,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(asdict(snapshot), ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._path)
        self._state = state
        return snapshot

    def load(self) -> RuntimeSnapshot | None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        try:
            return RuntimeSnapshot(
                state=str(data.get("state", "unknown")),
                breaker=str(data.get("breaker", "closed")),
                queue_len=int(data.get("queue_len", 0)),
                last_chat=data.get("last_chat"),
                dry_run=bool(data.get("dry_run", True)),
                updated_at=float(data.get("updated_at", 0.0)),
                note=str(data.get("note", "")),
            )
        except (TypeError, ValueError):
            return None

    def record_success(self) -> None:
        self._failures = 0
        self._restarts = 0
        self._state = "running"

    def record_failure(self, error: str) -> RuntimeSnapshot:
        self._failures += 1
        note = f"连续失败 {self._failures} 次：{error[:200]}"
        if self._failures >= self._max_failures:
            self._state = "paused"
            return self.save(state="paused", breaker="open", note=note)
        return self.save(state="running", note=note)

    def record_crash(self, error: str) -> RuntimeSnapshot:
        self._state = "crashed"
        return self.save(state="crashed", note=f"崩溃：{error[:200]}")

    def recover(self) -> RuntimeSnapshot:
        """恢复上次快照；重启次数超限抛 RecoveryError（安全模式）。"""
        self._restarts += 1
        if self._restarts > self._max_restarts:
            raise RecoveryError(f"重启次数超限（{self._restarts}/{self._max_restarts}），进入安全模式")
        snapshot = self.load() or RuntimeSnapshot()
        restored = RuntimeSnapshot(
            state="paused" if snapshot.state in {"crashed", "paused"} else snapshot.state,
            breaker=snapshot.breaker,
            queue_len=snapshot.queue_len,
            last_chat=snapshot.last_chat,
            dry_run=True,  # 恢复后强制回到 dry_run，需人工确认再解除
            updated_at=self._clock(),
            note=f"恢复自：{snapshot.note}",
        )
        self.save(
            state=restored.state,
            breaker=restored.breaker,
            queue_len=restored.queue_len,
            last_chat=restored.last_chat,
            dry_run=True,
            note=restored.note,
        )
        return restored


@dataclass(frozen=True)
class RecoveryReport:
    recovered: bool
    stale_tasks_reset: int
    snapshot_state: str
    dry_run_forced: bool = True
    message: str = ""


class RecoveryManager:
    """崩溃恢复：快照 + tasks 僵尸态重置。"""

    def __init__(self, databases: Databases, guard: FailureGuard) -> None:
        self._databases = databases
        self._guard = guard

    def recover(self) -> RecoveryReport:
        try:
            snapshot = self._guard.recover()
        except RecoveryError as exc:
            self._guard.save(state="safe_mode", note=str(exc))
            return RecoveryReport(recovered=False, stale_tasks_reset=0, snapshot_state="safe_mode", message=str(exc))
        connection = self._databases.history
        cursor = connection.execute("UPDATE tasks SET state = 'pending' WHERE state = 'running'")
        connection.commit()
        return RecoveryReport(
            recovered=True,
            stale_tasks_reset=int(cursor.rowcount or 0),
            snapshot_state=snapshot.state,
            message="已恢复快照并重置僵尸任务；dry_run 已强制开启",
        )
