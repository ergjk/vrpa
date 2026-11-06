"""M4-02 测试：拟人化延迟（确定性 rng + 可打断等待）。"""

from __future__ import annotations

import random
import threading

from vrpa.scheduling.delay import Humanizer


def _humanizer(**overrides) -> Humanizer:
    values = {
        "think_delay": (1.5, 5.0),
        "typing_ms_per_char": (35.0, 90.0),
        "pre_send_delay": (0.3, 1.4),
        "long_reply_extra": (1.0, 3.0),
        "rng": random.Random(7),
        "sleep": lambda _seconds: None,
    }
    values.update(overrides)
    return Humanizer(**values)


def test_samples_within_bounds() -> None:
    humanizer = _humanizer()
    think = humanizer.think_seconds()
    assert 1.5 <= think <= 5.0
    typing = humanizer.typing_seconds(10)
    assert typing > 0
    assert humanizer.typing_seconds(30) > typing
    assert 0.3 <= humanizer.pre_send_delay_seconds() <= 1.4


def test_long_reply_extra_delay() -> None:
    humanizer = _humanizer(long_reply_threshold=5)
    assert humanizer.send_seconds(100) > humanizer.send_seconds(1)


def test_wait_uses_sleep_and_cancel_event() -> None:
    sleeps: list[float] = []
    humanizer = _humanizer(sleep=sleeps.append)
    assert humanizer.wait(0.5) is True
    assert sleeps == [0.5]

    cancel = threading.Event()
    cancel.set()
    assert humanizer.wait(10.0, cancel=cancel) is False  # 立即返回，不等待


def test_human_send_respects_cancel() -> None:
    humanizer = _humanizer()
    assert humanizer.human_send("你好") is True
    cancel = threading.Event()
    cancel.set()
    assert humanizer.human_send("你好", cancel=cancel) is False


def test_delay_capped() -> None:
    humanizer = _humanizer(think_delay=(1.0, 1.0), typing_ms_per_char=(1000.0, 1000.0))
    assert humanizer.typing_seconds(10_000) <= 60.0
