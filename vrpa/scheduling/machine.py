"""状态机与熔断（M4-04，平台无关）。

状态：idle -> running <-> paused -> stopped；熔断打开时进入 paused 并记录原因。
熔断：连续失败达到阈值 -> open（拒绝发送）；冷却后 half_open 允许一次探测；
探测成功 -> closed，失败 -> 重新 open。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from vrpa.errors import InternalError

__all__ = ["BreakerState", "CircuitBreaker", "RunState", "RunStateMachine"]


class RunState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class BreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


_RUN_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.IDLE: frozenset({RunState.RUNNING, RunState.STOPPED}),
    RunState.RUNNING: frozenset({RunState.PAUSED, RunState.STOPPED}),
    RunState.PAUSED: frozenset({RunState.RUNNING, RunState.STOPPED}),
    RunState.STOPPED: frozenset(),
}


class RunStateMachine:
    """运行状态机（非法迁移抛 InternalError，避免静默错状态）。"""

    def __init__(self) -> None:
        self._state = RunState.IDLE

    @property
    def state(self) -> RunState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state is RunState.RUNNING

    def start(self) -> RunState:
        return self._transition(RunState.RUNNING)

    def pause(self, reason: str = "") -> RunState:
        self.pause_reason = reason
        return self._transition(RunState.PAUSED)

    def resume(self) -> RunState:
        return self._transition(RunState.RUNNING)

    def stop(self) -> RunState:
        return self._transition(RunState.STOPPED)

    def _transition(self, target: RunState) -> RunState:
        if target not in _RUN_TRANSITIONS[self._state]:
            raise InternalError(f"非法运行状态迁移：{self._state.value} -> {target.value}")
        self._state = target
        return self._state


@dataclass
class CircuitBreaker:
    """连续失败熔断器。"""

    max_consecutive_failures: int = 3
    cooldown_seconds: float = 300.0
    clock: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        self._state = BreakerState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._half_open_used = False

    @property
    def state(self) -> BreakerState:
        if self._state is BreakerState.OPEN and self.clock() - self._opened_at >= self.cooldown_seconds:
            self._state = BreakerState.HALF_OPEN
        return self._state

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def allow(self) -> bool:
        state = self.state
        if state is BreakerState.CLOSED:
            return True
        if state is BreakerState.HALF_OPEN and not self._half_open_used:
            self._half_open_used = True
            return True
        return False

    def record_success(self) -> None:
        self._state = BreakerState.CLOSED
        self._consecutive_failures = 0
        self._half_open_used = False

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._state is BreakerState.HALF_OPEN or self._consecutive_failures >= self.max_consecutive_failures:
            self._state = BreakerState.OPEN
            self._opened_at = self.clock()
            self._half_open_used = False

    def reset(self) -> None:
        self._state = BreakerState.CLOSED
        self._consecutive_failures = 0
        self._half_open_used = False
