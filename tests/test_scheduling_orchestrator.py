"""M4-04/05/06 测试：编排循环（Fake 后端、dry_run、控制通道、熔断）。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from vrpa.memory.db import Databases, init_databases
from vrpa.memory.history import HistoryStore
from vrpa.scheduling.loop import ControlChannel, ControlCommand, Orchestrator
from vrpa.scheduling.machine import CircuitBreaker, RunState, RunStateMachine
from vrpa.scheduling.queue import MessageQueue
from vrpa.scheduling.scheduler import Scheduler
from vrpa.testing.fakes import FakeExecutor
from wechat_agent.core.config import load_config
from wechat_agent.memory.pipeline import MessagePipeline
from wechat_agent.perception.parser import WeChatParser
from wechat_agent.tools.run import InstantHumanizer, ScriptedBrain, ScriptedPerception

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config(ROOT / "config.yaml")


def _scheduler() -> Scheduler:
    deterministic = replace(
        CFG.ratelimit,
        quiet_hours=(),
        per_chat_per_minute=100,
        per_chat_per_day=10000,
        global_per_hour=10000,
        cooldown_after_send=(0.0, 0.0),
    )
    return Scheduler(
        deterministic,
        clock=lambda: 1000.0,
        now=lambda: datetime(2026, 1, 1, 12, 0),
    )


@pytest.fixture()
def rig(tmp_path: Path):
    databases: Databases = init_databases(tmp_path)
    history = HistoryStore(databases)
    perception = ScriptedPerception({"张三": ["10:00 张三: 你好", ""]})
    brain = ScriptedBrain({"张三": ["你好呀"]})
    executor = FakeExecutor(dry_run=True)
    control = ControlChannel()
    orchestrator = Orchestrator(
        CFG,
        perception=perception,
        parser=WeChatParser(),
        pipeline=MessagePipeline(history),
        brain=brain,
        executor=executor,
        humanizer=InstantHumanizer(),
        scheduler=_scheduler(),
        queue=MessageQueue(),
        machine=RunStateMachine(),
        breaker=CircuitBreaker(max_consecutive_failures=3, clock=lambda: 1000.0),
        control=control,
    )
    try:
        yield orchestrator, history, executor, control
    finally:
        databases.close()


def test_tick_capture_ingest_reply(rig) -> None:
    orchestrator, history, executor, _ = rig
    orchestrator.start()
    result = orchestrator.tick(["张三"])
    assert result.captured == 1 and result.ingested == 1
    assert result.replies == ("你好呀",)
    assert executor.sent == [("张三", "你好呀", "auto")]
    assert history.count("张三") == 2  # in + out
    assert "reply:张三:你好呀" in orchestrator._events


def test_pause_and_resume(rig) -> None:
    orchestrator, _, executor, control = rig
    orchestrator.start()
    control.submit(ControlCommand(action="pause", reason="test"))
    paused = orchestrator.tick(["张三"])
    assert paused.state == "paused" and paused.captured == 0
    assert executor.sent == []

    control.submit(ControlCommand(action="resume"))
    resumed = orchestrator.tick(["张三"])
    assert resumed.state == "running" and resumed.replies == ("你好呀",)


def test_takeover_channel(rig) -> None:
    orchestrator, history, executor, control = rig
    orchestrator.start()
    control.submit(ControlCommand(action="takeover", chat="张三", text="手动接管"))
    result = orchestrator.tick(["张三"])
    assert "takeover" in result.events
    assert ("张三", "手动接管", "override") in executor.sent
    assert history.last("张三").content == "手动接管"  # type: ignore[union-attr]


def test_stop_channel(rig) -> None:
    orchestrator, _, _, control = rig
    orchestrator.start()
    control.submit(ControlCommand(action="stop"))
    result = orchestrator.tick(["张三"])
    assert result.state == "stopped"
    assert control.stop_requested is True


def test_pause_interrupts_humanized_wait(rig) -> None:
    orchestrator, _, _, control = rig
    orchestrator.start()
    control.pause()
    humanizer = InstantHumanizer()
    assert humanizer.human_send("x", cancel=control.interrupt_event) is False
    control.resume()
    assert humanizer.human_send("x", cancel=control.interrupt_event) is True


def test_circuit_breaker_pauses_loop(tmp_path: Path) -> None:
    databases = init_databases(tmp_path)
    try:
        control = ControlChannel()
        orchestrator = Orchestrator(
            CFG,
            perception=ScriptedPerception({}, failures=3),
            parser=WeChatParser(),
            pipeline=MessagePipeline(HistoryStore(databases)),
            brain=ScriptedBrain({}),
            executor=FakeExecutor(),
            humanizer=InstantHumanizer(),
            scheduler=_scheduler(),
            machine=RunStateMachine(),
            breaker=CircuitBreaker(max_consecutive_failures=3, clock=lambda: 1000.0),
            control=control,
        )
        orchestrator.start()
        for _ in range(3):
            result = orchestrator.tick(["张三"])
        assert result.state == "paused"
        assert result.breaker == "open"
        assert result.failures == 1
        assert any("breaker_open" in event for event in result.events)
    finally:
        databases.close()


def test_run_report(rig) -> None:
    orchestrator, _, _, control = rig
    control.submit(ControlCommand(action="pause"))
    control.submit(ControlCommand(action="resume"))
    report = orchestrator.run(["张三"], max_ticks=2)
    assert report.ticks == 2
    assert report.state == RunState.RUNNING.value
    assert report.replies == ("你好呀",)
    assert report.queue_left == 0


def test_memory_job_enqueued(rig) -> None:
    orchestrator, _, _, _ = rig

    class _Job:
        def __init__(self) -> None:
            self.calls: list[tuple[str, list[object], str]] = []

        def enqueue(self, chat: str, messages, *, dedupe_key: str | None = None) -> None:
            self.calls.append((chat, list(messages), dedupe_key or ""))

    job = _Job()
    orchestrator._memory_job = job  # noqa: SLF001
    orchestrator.start()
    result = orchestrator.tick(["张三"])
    assert "memory_queued" in result.events
    assert job.calls and job.calls[0][0] == "张三"
    assert job.calls[0][1][0].content == "你好"
    assert job.calls[0][2].startswith("张三:")
