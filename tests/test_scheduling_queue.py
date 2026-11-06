"""M4-01 测试：优先级队列。"""

from __future__ import annotations

from vrpa.scheduling.queue import MessageQueue, QueuedMessage


def test_priority_then_fifo() -> None:
    queue = MessageQueue()
    queue.push(QueuedMessage(chat="a", content="p5-1", priority=5))
    queue.push(QueuedMessage(chat="b", content="p1", priority=1))
    queue.push(QueuedMessage(chat="a", content="p5-2", priority=5))
    assert len(queue) == 3
    assert queue.pop().content == "p1"
    assert queue.pop().content == "p5-1"
    assert queue.pop().content == "p5-2"
    assert queue.pop() is None


def test_blocked_chat_is_skipped() -> None:
    queue = MessageQueue()
    queue.push(QueuedMessage(chat="a", content="a1", priority=1))
    queue.push(QueuedMessage(chat="b", content="b1", priority=1))
    first = queue.pop(blocked_chats={"a"})
    assert first is not None and first.chat == "b"
    assert queue.pop(blocked_chats={"a"}) is None
    assert queue.pop(blocked_chats=set()).content == "a1"


def test_peek_chats_and_drain() -> None:
    queue = MessageQueue()
    queue.push(QueuedMessage(chat="a", content="1"))
    queue.push(QueuedMessage(chat="b", content="2"))
    assert queue.peek().content == "1"  # type: ignore[union-attr]
    assert set(queue.chats()) == {"a", "b"}
    drained = queue.drain()
    assert [item.content for item in drained] == ["1", "2"]
    assert len(queue) == 0
