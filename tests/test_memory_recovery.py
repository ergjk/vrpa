"""未回复消息恢复测试。"""

from __future__ import annotations

from pathlib import Path

from vrpa.memory.db import init_databases
from vrpa.memory.history import HistoryStore
from wechat_agent.memory.recovery import unanswered_incoming


def _history(tmp_path: Path) -> HistoryStore:
    return HistoryStore(init_databases(tmp_path))


def test_recovers_only_after_last_response(tmp_path: Path) -> None:
    history = _history(tmp_path)
    history.append("张三", "旧消息", direction="in")
    history.append("张三", "回复", direction="out", role="assistant")
    history.append("张三", "新消息1", direction="in")
    history.append("张三", "自己发的", direction="self", role="assistant")
    history.append("张三", "新消息2", direction="in")
    pending = unanswered_incoming(history, "张三")
    assert [record.content for record in pending] == ["新消息2"]


def test_recovers_all_when_never_replied(tmp_path: Path) -> None:
    history = _history(tmp_path)
    history.append("张三", "a", direction="in")
    history.append("张三", "b", direction="in")
    pending = unanswered_incoming(history, "张三", limit=5)
    assert [record.content for record in pending] == ["a", "b"]


def test_limit_and_empty(tmp_path: Path) -> None:
    history = _history(tmp_path)
    assert unanswered_incoming(history, "张三") == ()
    for i in range(10):
        history.append("张三", f"m{i}", direction="in")
    assert len(unanswered_incoming(history, "张三", limit=3)) == 3
