"""调度器（M4-03，平台无关）：跨会话轮转 / 限流 / 静默时段 / 冷却。

限流窗口基于单调时钟（可注入），静默时段基于本地时间（可注入 datetime）。
所有拒绝都必须给出 ``retry_after`` 与可读 ``reason``，由主循环决定等待或跳过。
"""

from __future__ import annotations

import random
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from vrpa.config.schema import RatelimitConfig

__all__ = ["ConversationRotator", "Scheduler", "SendDecision"]


@dataclass(frozen=True)
class SendDecision:
    """单次发送判定。"""

    allowed: bool
    reason: str = "ok"
    retry_after: float = 0.0


def _parse_quiet_range(spec: str) -> tuple[int, int]:
    start_text, _, end_text = spec.strip().partition("-")
    if not start_text or not end_text:
        raise ValueError(f"静默时段格式错误：{spec!r}")
    start_hour, start_minute = (int(part) for part in start_text.strip().split(":"))
    end_hour, end_minute = (int(part) for part in end_text.strip().split(":"))
    return start_hour * 60 + start_minute, end_hour * 60 + end_minute


class ConversationRotator:
    """跨会话轮转：按列表顺序依次返回会话，可跳过禁用会话。"""

    def __init__(self, chats: Sequence[str], *, disabled: set[str] | None = None) -> None:
        self._chats = tuple(chats)
        self._disabled = disabled or set()
        self._index = 0

    @property
    def chats(self) -> tuple[str, ...]:
        return self._chats

    def next(self) -> str | None:
        if not self._chats:
            return None
        for _ in range(len(self._chats)):
            chat = self._chats[self._index % len(self._chats)]
            self._index += 1
            if chat not in self._disabled:
                return chat
        return None


class Scheduler:
    """限流 + 静默时段 + 冷却的发送闸门。"""

    def __init__(
        self,
        config: RatelimitConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = datetime.now,
        rng: random.Random | None = None,
    ) -> None:
        self._config = config
        self._clock = clock
        self._now = now
        self._rng = rng or random.Random()
        self._chat_minute: dict[str, deque[float]] = {}
        self._chat_day: dict[str, deque[float]] = {}
        self._global_hour: deque[float] = deque()
        self._last_send: dict[str, float] = {}
        self._quiet_ranges = tuple(_parse_quiet_range(spec) for spec in config.quiet_hours)

    # ------------------------------------------------------------ 判定
    def check(self, chat: str) -> SendDecision:
        now_dt = self._now()
        if self._in_quiet_hours(now_dt):
            return SendDecision(False, "quiet_hours", self._seconds_until_quiet_end(now_dt))
        monkey_now = self._clock()

        minute = self._window(self._chat_minute, chat)
        self._prune(minute, monkey_now, 60.0)
        if len(minute) >= self._config.per_chat_per_minute:
            return SendDecision(False, "chat_per_minute", 60.0 - (monkey_now - minute[0]))

        day = self._window(self._chat_day, chat)
        self._prune(day, monkey_now, 86400.0)
        if len(day) >= self._config.per_chat_per_day:
            return SendDecision(False, "chat_per_day", 86400.0 - (monkey_now - day[0]))

        self._prune(self._global_hour, monkey_now, 3600.0)
        if len(self._global_hour) >= self._config.global_per_hour:
            return SendDecision(False, "global_per_hour", 3600.0 - (monkey_now - self._global_hour[0]))

        last = self._last_send.get(chat)
        if last is not None:
            low, high = self._config.cooldown_after_send
            cooldown = self._rng.uniform(min(low, high), max(low, high))
            remaining = cooldown - (monkey_now - last)
            if remaining > 0:
                return SendDecision(False, "cooldown", remaining)
        return SendDecision(True)

    def note_send(self, chat: str) -> None:
        monkey_now = self._clock()
        self._window(self._chat_minute, chat).append(monkey_now)
        self._window(self._chat_day, chat).append(monkey_now)
        self._global_hour.append(monkey_now)
        self._last_send[chat] = monkey_now

    # ------------------------------------------------------------ 静默时段
    def _in_quiet_hours(self, now_dt: datetime) -> bool:
        minutes = now_dt.hour * 60 + now_dt.minute
        for start, end in self._quiet_ranges:
            if start <= end:
                if start <= minutes < end:
                    return True
            elif minutes >= start or minutes < end:  # 跨午夜
                return True
        return False

    def _seconds_until_quiet_end(self, now_dt: datetime) -> float:
        minutes = now_dt.hour * 60 + now_dt.minute
        best = 0.0
        for start, end in self._quiet_ranges:
            in_range = start <= minutes < end if start <= end else (minutes >= start or minutes < end)
            if not in_range:
                continue
            delta = (end - minutes) % (24 * 60)
            if delta == 0:
                return float(24 * 60)
            best = max(best, float(delta * 60))
        return best or float(24 * 60)

    # ------------------------------------------------------------ 内部
    @staticmethod
    def _window(store: dict[str, deque[float]], chat: str) -> deque[float]:
        bucket = store.get(chat)
        if bucket is None:
            bucket = deque()
            store[chat] = bucket
        return bucket

    @staticmethod
    def _prune(window: deque[float], now: float, seconds: float) -> None:
        while window and now - window[0] > seconds:
            window.popleft()


def _unused(*_args: object) -> None:  # pragma: no cover - 保持 timedelta 导入供类型提示
    _ = timedelta
