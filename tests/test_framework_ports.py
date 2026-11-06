"""M0-F-04 框架端口与 DTO 测试（vrpa.ports + Fakes）。

覆盖：DTO 校验/默认值、五个端口协议可被 Fakes 满足、Fakes 的失败语义、
内存记忆流水、Ports 容器。
"""

from __future__ import annotations

import pytest

from vrpa.errors import CopyFailed, ElementNotVisible, LLMError, SessionSwitchFailed, VerifyFailed
from vrpa.ports import (
    Brain,
    ElementTree,
    Executor,
    IncomingMessage,
    LLMResult,
    MemoryItem,
    MemoryStore,
    Message,
    Perception,
    Ports,
    Rect,
    SendOutcome,
)
from vrpa.testing.fakes import (
    FakeBrain,
    FakeElementTree,
    FakeExecutor,
    FakeMemoryStore,
    FakePerception,
    make_fake_ports,
)


def test_rect_validation_and_helpers() -> None:
    rect = Rect(100, 200, 80, 40)
    assert rect.center == (140, 220)
    assert rect.right == 180 and rect.bottom == 240
    assert rect.contains(100, 200) and not rect.contains(180, 240)
    assert rect.as_tuple() == (100, 200, 80, 40)
    with pytest.raises(ValueError):
        Rect(0, 0, 0, 10)
    with pytest.raises(TypeError):
        Rect(0, 0, 10, 10.5)  # type: ignore[arg-type]


def test_dto_defaults() -> None:
    message = Message(direction="in", content="你好")
    assert message.role == "user" and message.status == "ok"
    assert IncomingMessage(content="hi").confidence == 1.0
    assert SendOutcome(ok=True, stage="sent").trace_id == "-"
    assert dict(LLMResult(text="hi").usage) == {}
    assert MemoryItem(content="喜欢猫").category == "event"


def test_fakes_satisfy_all_ports() -> None:
    ports = make_fake_ports()
    assert isinstance(ports.element_tree, ElementTree)
    assert isinstance(ports.perception, Perception)
    assert isinstance(ports.executor, Executor)
    assert isinstance(ports.brain, Brain)
    assert isinstance(ports.memory, MemoryStore)
    assert isinstance(ports, Ports)
    assert set(ports.as_mapping()) == {"element_tree", "perception", "executor", "brain", "memory"}


def test_element_tree_failure_semantics() -> None:
    tree = FakeElementTree()
    assert isinstance(tree.locate("input_box"), Rect)
    tree.invalidate()
    assert tree.invalidated == 1
    assert tree.validate() is True
    assert tree.profile_name() == "fake@1.0"
    with pytest.raises(ElementNotVisible):
        FakeElementTree(fail_locate=True).locate("input_box")


def test_perception_script_and_failure_semantics() -> None:
    perception = FakePerception(scripted=("a: 1", "b: 2"))
    perception.activate()
    assert perception.captures == []
    assert perception.capture("demo") == "a: 1"
    assert perception.capture("demo") == "b: 2"
    assert perception.capture("demo") == "b: 2"  # 用完复用最后一条
    assert perception.activated == 1
    with pytest.raises(CopyFailed):
        FakePerception().capture("demo")
    with pytest.raises(SessionSwitchFailed):
        FakePerception(fail_switch=True).switch_session("demo")


def test_executor_send_outcomes() -> None:
    executor = FakeExecutor(dry_run=True)
    outcome = executor.send("demo", "hi")
    assert outcome.ok and outcome.stage == "dry_run"
    assert executor.sent == [("demo", "hi", "auto")]
    assert executor.is_dry_run() is True
    with pytest.raises(VerifyFailed):
        FakeExecutor(fail_send=True).send("demo", "hi")


def test_brain_generate_and_failure() -> None:
    result = FakeBrain(reply="好的").generate([{"role": "user", "content": "hi"}])
    assert result.text == "好的"
    assert result.usage["total_tokens"] == len("好的")
    assert FakeBrain().ping() >= 0
    with pytest.raises(LLMError):
        FakeBrain(fail=True).generate([])


def test_memory_store_flow() -> None:
    memory = FakeMemoryStore()
    assert memory.insert_messages("demo", [IncomingMessage(content="hi", sender="visitor")]) == 1
    assert memory.writeback("demo", "reply") == 1
    assert memory.writeback("demo", "reply2") == 2
    history = memory.history("demo", 10)
    assert [message.content for message in history] == ["hi", "reply", "reply2"]
    memory_id = memory.add_memory(MemoryItem(content="喜欢美式", category="preference"))
    assert memory_id == 1
    assert len(memory.recall(None, "美式", 5)) == 1
    assert memory.forget(memory_id) is True
    assert memory.forget(memory_id) is False
    assert len(memory.recent_hashes("demo", 2)) == 2
