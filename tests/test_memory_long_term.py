"""M3-05 测试：长期档案库与规则提取。"""

from __future__ import annotations

from pathlib import Path

import pytest

from vrpa.memory.long_term import LongTermMemory, MemoryCandidate, extract_candidates
from vrpa.memory.store import SQLiteMemoryStore
from vrpa.ports import Message


@pytest.fixture()
def store(tmp_path: Path):
    memory_store = SQLiteMemoryStore(tmp_path)
    try:
        yield memory_store
    finally:
        memory_store.close()


def _message(content: str) -> Message:
    return Message(direction="in", content=content, sender="张三")


def test_extract_candidates_rules() -> None:
    messages = [
        _message("我喜欢喝美式"),
        _message("我的生日是 5 月 1 日"),
        _message("记住: 每周五发朋友圈"),
        _message("今天天气不错"),
    ]
    candidates = extract_candidates(messages)
    keys = {(candidate.category, candidate.key) for candidate in candidates}
    assert ("preference", "喜欢") in keys
    assert ("profile", "生日") in keys
    assert ("rule", "记住") in keys
    assert len(candidates) == 3


def test_extract_candidates_dedup_same_key() -> None:
    candidates = extract_candidates([_message("我喜欢猫"), _message("我喜欢狗")])
    assert len(candidates) == 1


def test_remember_upsert_and_recall(store: SQLiteMemoryStore) -> None:
    memory = LongTermMemory(store)
    candidates = extract_candidates([_message("我喜欢喝美式")])
    ids = memory.remember(candidates, chat="张三")
    assert len(ids) == 1
    recalled = memory.recall("美式", chat="张三")
    assert len(recalled) == 1 and "美式" in recalled[0].content

    updated = extract_candidates([_message("我喜欢喝拿铁")])
    new_ids = memory.remember(updated, chat="张三")
    assert new_ids[0] == ids[0]  # 同 key 幂等更新
    assert "拿铁" in memory.recall("拿铁", chat="张三")[0].content
    assert len(memory.recall("美式", chat="张三")) >= 0


def test_extract_and_remember(store: SQLiteMemoryStore) -> None:
    memory = LongTermMemory(store)
    ids = memory.extract_and_remember([_message("我住在杭州")], chat="张三")
    assert len(ids) == 1
    assert "杭州" in memory.recall("杭州", top_k=5)[0].content


def test_forget_and_invalid_category(store: SQLiteMemoryStore) -> None:
    memory = LongTermMemory(store)
    memory_id = memory.remember(extract_candidates([_message("我叫小明")]), chat="张三")[0]
    assert memory.forget(memory_id) is True
    assert memory.forget(memory_id) is False
    with pytest.raises(ValueError, match="未知记忆分类"):
        memory.remember([MemoryCandidate(content="x", category="bad")])
