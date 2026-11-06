"""M3-03/04 测试：入库闭环（去重 -> 多端识别 -> 写入 -> 状态回写）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from vrpa.memory.db import Databases, init_databases
from vrpa.memory.history import HistoryStore
from vrpa.ports import IncomingMessage
from wechat_agent.memory.pipeline import MessagePipeline


@pytest.fixture()
def databases(tmp_path: Path):
    dbs: Databases = init_databases(tmp_path)
    try:
        yield dbs
    finally:
        dbs.close()


@pytest.fixture()
def history(databases: Databases) -> HistoryStore:
    return HistoryStore(databases)


def _incoming(content: str, sender: str | None = "张三") -> IncomingMessage:
    return IncomingMessage(content=content, sender=sender)


def test_ingest_tail_overlap(history: HistoryStore) -> None:
    history.append("张三", "你好")
    history.append("张三", "在吗")
    pipeline = MessagePipeline(history)
    result = pipeline.ingest("张三", [_incoming("你好"), _incoming("在吗"), _incoming("晚上好")])
    assert result.reason == "ok"
    assert result.duplicates == 2
    assert [record.content for record in result.queued] == ["晚上好"]
    assert [record.direction for record in result.inserted] == ["in"]
    assert history.count("张三") == 3


def test_ingest_full_duplicate(history: HistoryStore) -> None:
    history.append("张三", "a")
    history.append("张三", "b")
    result = MessagePipeline(history).ingest("张三", [_incoming("a"), _incoming("b")])
    assert result.inserted == () and result.queued == () and result.duplicates == 2


def test_low_confidence_ignore(history: HistoryStore) -> None:
    history.append("张三", "旧消息")
    result = MessagePipeline(history, low_confidence_policy="ignore").ingest("张三", [_incoming("完全不同")])
    assert result.reason == "low_confidence_ignored"
    assert result.inserted == () and result.queued == ()
    assert history.count("张三") == 1


def test_low_confidence_queue_confirm(history: HistoryStore) -> None:
    history.append("张三", "旧消息")
    result = MessagePipeline(history, low_confidence_policy="queue_confirm").ingest("张三", [_incoming("完全不同")])
    assert result.reason == "low_confidence_confirm"
    assert [record.content for record in result.inserted] == ["完全不同"]
    assert result.queued == ()
    assert history.last("张三").status == "pending_confirm"  # type: ignore[union-attr]


def test_multi_device_self_messages(history: HistoryStore) -> None:
    result = MessagePipeline(history).ingest(
        "张三",
        [IncomingMessage(content="我手机发的", sender=None), _incoming("你好")],
    )
    assert [record.content for record in result.self_messages] == ["我手机发的"]
    assert [record.content for record in result.queued] == ["你好"]
    assert history.last("张三").direction == "in"  # type: ignore[union-attr]


def test_empty_incoming(history: HistoryStore) -> None:
    result = MessagePipeline(history).ingest("张三", [])
    assert result.reason == "empty_observed"
    assert history.count("张三") == 0


def test_writeback_idempotent(history: HistoryStore) -> None:
    pipeline = MessagePipeline(history)
    first = pipeline.writeback("张三", "收到")
    second = pipeline.writeback("张三", "收到")
    assert first == second
    record = history.get(first)
    assert record is not None and record.direction == "out" and record.source == "self_writeback"
    assert history.count("张三") == 1


def test_writeback_after_new_out_content(history: HistoryStore) -> None:
    pipeline = MessagePipeline(history)
    first = pipeline.writeback("张三", "回复一")
    second = pipeline.writeback("张三", "回复二")
    assert first != second
    assert history.count("张三") == 2
