"""M6-03 测试：失败自保与崩溃恢复。"""

from __future__ import annotations

from pathlib import Path

import pytest

from vrpa.memory.db import init_databases
from vrpa.memory.jobs import TaskQueue
from vrpa.runtime.recovery import FailureGuard, RecoveryError, RecoveryManager

SNAPSHOT = "runtime_state.json"


def test_snapshot_roundtrip_and_corruption(tmp_path: Path) -> None:
    guard = FailureGuard(tmp_path / SNAPSHOT, clock=lambda: 100.0)
    assert guard.load() is None
    saved = guard.save(state="running", breaker="closed", queue_len=2, last_chat="张三", dry_run=True)
    loaded = guard.load()
    assert loaded == saved and loaded.queue_len == 2 and loaded.last_chat == "张三"
    (tmp_path / SNAPSHOT).write_text("{bad json", encoding="utf-8")
    assert guard.load() is None


def test_failure_guard_pauses_after_threshold(tmp_path: Path) -> None:
    guard = FailureGuard(tmp_path / SNAPSHOT, max_failures=2, clock=lambda: 1.0)
    first = guard.record_failure("boom")
    assert first.state == "running" and first.breaker == "closed"
    second = guard.record_failure("boom")
    assert second.state == "paused" and second.breaker == "open"
    guard.record_success()
    assert guard.failures == 0


def test_crash_snapshot_and_recover_forces_dry_run(tmp_path: Path) -> None:
    guard = FailureGuard(tmp_path / SNAPSHOT, clock=lambda: 1.0)
    guard.record_crash("segfault")
    assert guard.load().state == "crashed"  # type: ignore[union-attr]
    restored = guard.recover()
    assert restored.state == "paused" and restored.dry_run is True


def test_restart_limit_enters_safe_mode(tmp_path: Path) -> None:
    guard = FailureGuard(tmp_path / SNAPSHOT, max_restarts=1)
    guard.recover()
    with pytest.raises(RecoveryError, match="安全模式"):
        guard.recover()


def test_recovery_manager_resets_stale_tasks(tmp_path: Path) -> None:
    databases = init_databases(tmp_path)
    try:
        queue = TaskQueue(databases)
        task_id = queue.enqueue("demo", {})
        databases.history.execute("UPDATE tasks SET state='running' WHERE id=?", (task_id,))
        databases.history.commit()
        guard = FailureGuard(tmp_path / SNAPSHOT, max_restarts=5)
        report = RecoveryManager(databases, guard).recover()
        assert report.recovered is True and report.stale_tasks_reset == 1
        row = databases.history.execute("SELECT state FROM tasks WHERE id=?", (task_id,)).fetchone()
        assert row[0] == "pending"
    finally:
        databases.close()


def test_recovery_manager_safe_mode(tmp_path: Path) -> None:
    databases = init_databases(tmp_path)
    try:
        guard = FailureGuard(tmp_path / SNAPSHOT, max_restarts=1)
        guard.recover()
        report = RecoveryManager(databases, guard).recover()
        assert report.recovered is False and report.snapshot_state == "safe_mode"
        assert guard.load().state == "safe_mode"  # type: ignore[union-attr]
    finally:
        databases.close()
