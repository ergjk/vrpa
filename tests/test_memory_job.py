"""M3 异步记忆 job：LLM 筛选器接线与持久队列。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from vrpa.memory.db import init_databases
from vrpa.memory.long_term import MemoryCandidate
from vrpa.memory.store import SQLiteMemoryStore
from vrpa.ports import Message
from wechat_agent.memory.job_factory import build_memory_extract_job


class _Selector:
    def __call__(self, messages):
        return (MemoryCandidate(content="对方下周三去杭州出差", category="event", importance=0.8),)


def test_factory_returns_none_without_key(tmp_path: Path) -> None:
    databases = init_databases(tmp_path)
    store = SQLiteMemoryStore(tmp_path)
    try:
        config = SimpleNamespace(api_key=lambda: "")
        assert build_memory_extract_job(config, databases, store) is None
    finally:
        store.close()
        databases.close()


def test_factory_job_persists_filtered_memory(tmp_path: Path) -> None:
    databases = init_databases(tmp_path)
    store = SQLiteMemoryStore(tmp_path)
    try:
        config = SimpleNamespace(api_key=lambda: "sk-test")
        job = build_memory_extract_job(config, databases, store, selector=_Selector())
        assert job is not None
        job.enqueue("张三", [Message(direction="in", content="我下周三去杭州出差", role="user")], dedupe_key="张三:1")
        assert job.run_once() is True
        recalled = store.recall("张三", "杭州", 5)
        assert [item.content for item in recalled] == ["对方下周三去杭州出差"]
    finally:
        store.close()
        databases.close()
