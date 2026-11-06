"""M4-04 测试：运行状态机 + 连续失败熔断。"""

from __future__ import annotations

import pytest

from vrpa.errors import InternalError
from vrpa.scheduling.machine import BreakerState, CircuitBreaker, RunState, RunStateMachine


def test_run_state_transitions() -> None:
    machine = RunStateMachine()
    assert machine.state is RunState.IDLE
    assert machine.start() is RunState.RUNNING
    assert machine.pause("manual") is RunState.PAUSED
    assert machine.resume() is RunState.RUNNING
    assert machine.stop() is RunState.STOPPED


def test_illegal_transition_raises() -> None:
    machine = RunStateMachine()
    with pytest.raises(InternalError, match="非法运行状态迁移"):
        machine.pause()
    machine.start()
    machine.stop()
    with pytest.raises(InternalError):
        machine.start()


class Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


def test_breaker_open_and_half_open() -> None:
    clock = Clock()
    breaker = CircuitBreaker(max_consecutive_failures=2, cooldown_seconds=10.0, clock=clock)
    assert breaker.allow() is True
    breaker.record_failure()
    assert breaker.state is BreakerState.CLOSED
    breaker.record_failure()
    assert breaker.state is BreakerState.OPEN
    assert breaker.allow() is False

    clock.value += 11
    assert breaker.state is BreakerState.HALF_OPEN
    assert breaker.allow() is True  # 一次探测
    assert breaker.allow() is False  # 探测名额已用
    breaker.record_failure()
    assert breaker.state is BreakerState.OPEN


def test_breaker_success_resets() -> None:
    clock = Clock()
    breaker = CircuitBreaker(max_consecutive_failures=1, cooldown_seconds=5.0, clock=clock)
    breaker.record_failure()
    assert breaker.state is BreakerState.OPEN
    clock.value += 6
    assert breaker.allow() is True
    breaker.record_success()
    assert breaker.state is BreakerState.CLOSED
    assert breaker.consecutive_failures == 0
    breaker.reset()
    assert breaker.allow() is True
