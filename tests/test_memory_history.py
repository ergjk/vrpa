"""M3-01 测试：流水库读写 API（HistoryStore）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from vrpa.errors import DBError
from vrpa.memory.db import Databases, init_databases
from vrpa.memory.history import HistoryStore


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


def test_ensure_chat_idempotent(history: HistoryStore) -> None:
    first = history.ensure_chat("张三")
    assert history.ensure_chat("张三") == first
    chat = history.get_chat("张三")
    assert chat is not None and chat.name == "张三" and chat.chat_type == "private"
    assert history.chat_id("张三") == first


def test_chat_id_unknown_raises(history: HistoryStore) -> None:
    with pytest.raises(DBError, match="会话不存在"):
        history.chat_id("不存在")


def test_append_and_read(history: HistoryStore) -> None:
    message_id = history.append(
        "张三",
        "你好",
        direction="in",
        role="user",
        sender="张三",
        ts="10:00",
        raw_meta={"confidence": 0.9},
    )
    record = history.get(message_id)
    assert record is not None
    assert record.content == "你好"
    assert record.direction == "in"
    assert record.sender == "张三"
    assert record.ts == "10:00"
    assert record.content_hash == history.tail_hashes("张三", 1)[0]
    assert history.count("张三") == 1
    assert history.last("张三").id == message_id  # type: ignore[union-attr]


def test_recent_order_and_status(history: HistoryStore) -> None:
    ids = [history.append("张三", text, direction="in") for text in ("a", "b", "c")]
    recent = history.recent("张三", 2)
    assert [record.content for record in recent] == ["b", "c"]
    assert history.update_status(ids[0], "recalled") is True
    assert history.update_status(99999, "ok") is False
    assert history.get(ids[0]).status == "recalled"  # type: ignore[union-attr]
    assert [record.content for record in history.recent("张三", 10)] == ["b", "c"]


def test_dedup_count_increments(history: HistoryStore) -> None:
    first = history.append("张三", "重复内容")
    second = history.append("张三", "重复内容")
    assert history.get(first).dedup_count == 1  # type: ignore[union-attr]
    assert history.get(second).dedup_count == 2  # type: ignore[union-attr]


def test_tail_hashes_window(history: HistoryStore) -> None:
    for text in ("a", "b", "c"):
        history.append("张三", text)
    assert len(history.tail_hashes("张三", 2)) == 2
    assert history.tail_hashes("张三", 0) == ()
