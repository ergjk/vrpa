"""拟人化延迟（M4-02，平台无关）。

机制：
    - 使用可注入的 ``random.Random`` 保证测试确定性；
    - 可打断等待：优先用 ``threading.Event.wait(timeout)``（控制通道可随时唤醒），
      无 Event 时退化为注入的 sleep 函数；
    - 所有延迟都有上限钳制，避免异常配置卡死主循环。
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

__all__ = ["Humanizer"]

MAX_DELAY_SECONDS = 60.0


@dataclass(frozen=True)
class Humanizer:
    """按配置采样拟人化延迟（秒）。"""

    think_delay: tuple[float, float] = (1.5, 5.0)
    typing_ms_per_char: tuple[float, float] = (35.0, 90.0)
    pre_send_delay: tuple[float, float] = (0.3, 1.4)
    long_reply_extra: tuple[float, float] = (1.0, 3.0)
    long_reply_threshold: int = 80
    rng: random.Random = random.Random()
    sleep: Callable[[float], None] = time.sleep

    def sample(self, bounds: Sequence[float]) -> float:
        low, high = float(bounds[0]), float(bounds[1])
        if low > high:
            low, high = high, low
        value = self.rng.uniform(low, high)
        return max(0.0, min(MAX_DELAY_SECONDS, value))

    def think_seconds(self) -> float:
        return self.sample(self.think_delay)

    def typing_seconds(self, chars: int) -> float:
        per_char = self.sample(self.typing_ms_per_char) / 1000.0
        return min(MAX_DELAY_SECONDS, max(0.0, per_char * max(0, chars)))

    def send_seconds(self, chars: int) -> float:
        delay = self.pre_send_delay_seconds() + self.typing_seconds(chars)
        if chars >= self.long_reply_threshold:
            delay += self.sample(self.long_reply_extra)
        return min(MAX_DELAY_SECONDS, delay)

    def pre_send_delay_seconds(self) -> float:
        return self.sample(self.pre_send_delay)

    def wait(self, seconds: float, *, cancel: threading.Event | None = None) -> bool:
        """等待指定秒数；返回 False 表示被取消（Event 已置位）。"""
        if seconds <= 0:
            return not (cancel is not None and cancel.is_set())
        if cancel is not None:
            return not cancel.wait(seconds)
        self.sleep(seconds)
        return True

    def human_send(self, text: str, *, cancel: threading.Event | None = None) -> bool:
        """完整拟人节奏：思考 -> 打字 -> 发送前停顿。被取消返回 False。"""
        if not self.wait(self.think_seconds(), cancel=cancel):
            return False
        if not self.wait(self.send_seconds(len(text)), cancel=cancel):
            return False
        return self.wait(self.pre_send_delay_seconds(), cancel=cancel)
