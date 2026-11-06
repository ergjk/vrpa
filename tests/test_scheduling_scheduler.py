"""M4-03 测试：调度器（限流 / 静默时段 / 冷却 / 轮转）。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from vrpa.config.schema import RatelimitConfig
from vrpa.scheduling.scheduler import ConversationRotator, Scheduler
from wechat_agent.core.config import load_config

ROOT = Path(__file__).resolve().parents[1]
BASE = load_config(ROOT / "config.yaml").ratelimit


def _config(**overrides) -> RatelimitConfig:
    values = {
        "quiet_hours": (),
        "per_chat_per_minute": 2,
        "per_chat_per_day": 3,
        "global_per_hour": 10,
        "cooldown_after_send": (0.0, 0.0),
    }
    values.update(overrides)
    return replace(BASE, **values)


class FakeClock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


def test_per_chat_minute_limit() -> None:
    clock = FakeClock()
    scheduler = Scheduler(_config(), clock=clock, now=lambda: datetime(2026, 1, 1, 12, 0))
    assert scheduler.check("张三").allowed is True
    scheduler.note_send("张三")
    scheduler.note_send("张三")
    decision = scheduler.check("张三")
    assert decision.allowed is False and decision.reason == "chat_per_minute"
    assert decision.retry_after > 0
    clock.value += 61
    assert scheduler.check("张三").allowed is True


def test_global_hour_limit() -> None:
    scheduler = Scheduler(
        _config(global_per_hour=1),
        clock=FakeClock(),
        now=lambda: datetime(2026, 1, 1, 12, 0),
    )
    assert scheduler.check("a").allowed is True
    scheduler.note_send("a")
    decision = scheduler.check("b")
    assert decision.allowed is False and decision.reason == "global_per_hour"


def test_quiet_hours() -> None:
    scheduler = Scheduler(
        _config(quiet_hours=("01:00-07:30",)),
        clock=FakeClock(),
        now=lambda: datetime(2026, 1, 1, 2, 0),
    )
    decision = scheduler.check("张三")
    assert decision.allowed is False and decision.reason == "quiet_hours"
    assert decision.retry_after > 0

    daytime = Scheduler(
        _config(quiet_hours=("01:00-07:30",)),
        clock=FakeClock(),
        now=lambda: datetime(2026, 1, 1, 8, 0),
    )
    assert daytime.check("张三").allowed is True


def test_cooldown_after_send() -> None:
    clock = FakeClock()
    scheduler = Scheduler(
        _config(cooldown_after_send=(5.0, 5.0)),
        clock=clock,
        now=lambda: datetime(2026, 1, 1, 12, 0),
    )
    scheduler.note_send("张三")
    decision = scheduler.check("张三")
    assert decision.allowed is False and decision.reason == "cooldown"
    clock.value += 6
    assert scheduler.check("张三").allowed is True


def test_rotator_cycles_and_skips_disabled() -> None:
    rotator = ConversationRotator(["a", "b", "c"], disabled={"b"})
    assert [rotator.next(), rotator.next(), rotator.next()] == ["a", "c", "a"]
    assert ConversationRotator([]).next() is None
