"""M3-06 测试：长期记忆提炼异步 job（持久队列 + 重试）。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from vrpa.memory.db import Databases, init_databases
from vrpa.memory.jobs import MemoryExtractJob, TaskQueue
from vrpa.memory.long_term import LongTermMemory, extract_candidates
from vrpa.memory.store import SQLiteMemoryStore
from vrpa.ports import Message

FIXED_NOW = lambda: datetime(2026, 1, 1, 12, 0, 0)  # noqa: E731


@pytest.fixture()
def databases(tmp_path: Path):
    dbs: Databases = init_databases(tmp_path)
    try:
        yield dbs
    finally:
        dbs.close()


@pytest.fixture()
def queue(databases: Databases) -> TaskQueue:
    return TaskQueue(databases, now=FIXED_NOW)


@pytest.fixture()
def memory(tmp_path: Path):
    store = SQLiteMemoryStore(tmp_path)
    try:
        yield LongTermMemory(store)
    finally:
        store.close()


def test_queue_lifecycle(queue: TaskQueue) -> None:
    task_id = queue.enqueue("demo", {"x": 1})
    pending = queue.pending()
    assert len(pending) == 1 and pending[0].id == task_id
    assert queue.claim(task_id) is True
    assert queue.claim(task_id) is False
    queue.complete(task_id)
    task = queue.get(task_id)
    assert task is not None and task.state == "done"
    assert queue.counts() == {"done": 1}


def test_queue_dedupe_key(queue: TaskQueue) -> None:
    first = queue.enqueue("demo", {"a": 1}, dedupe_key="k1")
    second = queue.enqueue("demo", {"a": 2}, dedupe_key="k1")
    assert first == second


def test_queue_cancel(queue: TaskQueue) -> None:
    task_id = queue.enqueue("demo", {})
    assert queue.cancel(task_id) is True
    assert queue.get(task_id).state == "cancelled"  # type: ignore[union-attr]
    assert queue.cancel(task_id) is False


def test_memory_extract_job_success(queue: TaskQueue, memory: LongTermMemory) -> None:
    job = MemoryExtractJob(queue, memory, extractor=extract_candidates, retry_delay=0.0)
    task_id = job.enqueue("张三", [Message(direction="in", content="我喜欢喝美式")])
    assert job.run_once() is True
    task = queue.get(task_id)
    assert task is not None and task.state == "done"
    assert "美式" in memory.recall("美式", chat="张三", top_k=5)[0].content
    assert job.run_once() is False


def test_memory_extract_job_retry_then_failed(queue: TaskQueue, memory: LongTermMemory) -> None:
    def boom(_messages):  # type: ignore[no-untyped-def]
        raise RuntimeError("extractor boom")

    job = MemoryExtractJob(queue, memory, extractor=boom, retry_delay=0.0, max_attempts=2)
    task_id = job.enqueue("张三", [Message(direction="in", content="随便")])
    assert job.run_once() is True
    task = queue.get(task_id)
    assert task is not None and task.state == "pending" and task.attempts == 1
    assert "RuntimeError" in (task.last_error or "")
    assert job.run_once() is True
    task = queue.get(task_id)
    assert task is not None and task.state == "failed" and task.attempts == 2


def test_run_pending_batch(queue: TaskQueue, memory: LongTermMemory) -> None:
    job = MemoryExtractJob(queue, memory, extractor=extract_candidates, retry_delay=0.0)
    job.enqueue("张三", [Message(direction="in", content="我喜欢猫")])
    job.enqueue("张三", [Message(direction="in", content="我住在杭州")])
    assert job.run_pending(limit=10) == 2
    assert queue.pending() == ()
