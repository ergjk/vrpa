"""微信感知层（M2-02/03）：窗口激活、会话切换、框选 + Ctrl+C 采集。

红线 R3：消息内容唯一来源 = 「框选 + Ctrl+C」剪贴板文本；本模块不做任何图像识别。
真实鼠标/键盘/窗口由 Driver/WindowBackend 注入；单元测试全部使用 Fakes。
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from vrpa.errors import CopyFailed, ElementNotVisible, TreeConfigError
from vrpa.ports import Rect
from vrpa.vision.driver import Driver, PyAutoGuiDriver
from wechat_agent.perception.session import WeChatSessionSwitcher
from wechat_agent.perception.window import WeChatWindow

if TYPE_CHECKING:  # pragma: no cover
    from wechat_agent.core.config import Config

__all__ = ["WeChatPerception"]

# 终点停留：0.3/0.6/0.9 三档按泊松权重抽样，再叠加 ±0.1s 抖动（节奏拟人，非安全边界）
_HOLD_AFTER_CHOICES = (0.3, 0.6, 0.9)
_HOLD_POISSON_LAMBDA = 1.0


def _sample_end_hold() -> float:
    """按泊松分布选择终点停留档位，并加入 ±0.1s 抖动。"""
    weights = []
    for index, _choice in enumerate(_HOLD_AFTER_CHOICES, start=1):
        weight = math.exp(-_HOLD_POISSON_LAMBDA) * (_HOLD_POISSON_LAMBDA**index) / math.factorial(index)
        weights.append(weight)
    base = random.choices(_HOLD_AFTER_CHOICES, weights=weights, k=1)[0]
    return round(max(0.15, base + random.uniform(-0.1, 0.1)), 3)


# 兜底拖拽方案：起点尽量压在左侧（对方）消息气泡上，向右上/上方拖。
_FALLBACK_DRAG_PLANS: tuple[tuple[tuple[float, float], tuple[float, float]], ...] = (
    ((0.10, 0.80), (0.92, 0.15)),
    ((0.10, 0.55), (0.92, 0.20)),
    ((0.12, 0.35), (0.92, 0.15)),
    ((0.10, 0.90), (0.92, 0.10)),
)


class WeChatPerception:
    """微信窗口激活 / 会话切换 / 消息采集。"""

    def __init__(
        self,
        config: Config,
        *,
        tree: Any | None = None,
        driver: Driver | None = None,
        window: WeChatWindow | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._tree = tree if tree is not None else _build_default_tree(config)
        self._driver: Driver = driver or PyAutoGuiDriver()
        self._window = window if window is not None else WeChatWindow(config)
        self._sleep = sleep
        self._session = WeChatSessionSwitcher(
            config,
            self._tree,
            self._driver,
            window=self._window,
            capture=self.capture,
            sleep=sleep,
        )

    def activate(self) -> None:
        self._window.ensure_foreground()

    def is_foreground(self) -> bool:
        return self._window.is_foreground()

    def foreground_process_name(self) -> str | None:
        return self._window.foreground_process_name()

    def switch_session(self, session: str) -> None:
        self._session.ensure_chat(session)

    def drag_plan(self) -> tuple[Rect, tuple[int, int], tuple[int, int], float]:
        """计算本次框选计划（真机调试用：消息区 / 起点 / 终点 / 时长）。"""
        self._window.ensure_foreground()
        try:
            area = self._tree.locate("message_area")
        except (ElementNotVisible, TreeConfigError) as exc:
            raise ElementNotVisible(f"无法定位消息区：{exc}") from exc
        self._assert_window_matches_profile()
        drag = self._config.capture.drag
        start = (
            area.x + int(round(area.width * drag.from_x)),
            area.y + int(round(area.height * drag.from_y)),
        )
        end = (
            area.x + int(round(area.width * drag.to_x)),
            area.y + int(round(area.height * drag.to_y)),
        )
        return area, start, end, float(drag.duration)

    def _assert_window_matches_profile(self) -> None:
        """静态容器依赖窗口位置：窗口移动/缩放后必须重新校准。"""
        try:
            expected = self._tree.locate("main_window")
            actual = self._window.find().rect
        except (ElementNotVisible, TreeConfigError):
            return
        tolerance = 40
        if (
            abs(expected.x - actual.x) > tolerance
            or abs(expected.y - actual.y) > tolerance
            or abs(expected.width - actual.width) > tolerance
            or abs(expected.height - actual.height) > tolerance
        ):
            raise TreeConfigError(
                f"微信窗口位置/大小与校准不一致（profile main_window={expected.as_tuple()}，"
                f"当前窗口={actual.as_tuple()}）；请保持窗口不动或重新执行 calibrate"
            )

    def capture(self, session: str) -> str:
        """框选消息区 + Ctrl+C，返回剪贴板原始文本。"""
        area, start, end, duration = self.drag_plan()
        drag = self._config.capture.drag
        if start == end:
            raise CopyFailed(f"框选起点与终点相同（message_area={area.as_tuple()}）")

        previous = ""
        if self._config.capture.restore_clipboard:
            try:
                previous = self._driver.clipboard_get()
            except CopyFailed:
                previous = ""

        # 真机经验：起点落在气泡间隙/空白处不会触发文本选择。
        # 首选配置比例，失败后换多个“左侧消息文字附近”的起点重试（无图像识别）。
        attempts: list[tuple[tuple[int, int], tuple[int, int]]] = [(start, end)]
        for from_ratio, to_ratio in _FALLBACK_DRAG_PLANS:
            fallback_start = (
                area.x + int(round(area.width * from_ratio[0])),
                area.y + int(round(area.height * from_ratio[1])),
            )
            fallback_end = (
                area.x + int(round(area.width * to_ratio[0])),
                area.y + int(round(area.height * to_ratio[1])),
            )
            if (fallback_start, fallback_end) not in attempts:
                attempts.append((fallback_start, fallback_end))

        text = ""
        last_sentinel = ""
        try:
            for index, (attempt_start, attempt_end) in enumerate(attempts):
                last_sentinel = f"__vrpa_clipboard_{uuid4().hex}__"
                self._driver.clipboard_set(last_sentinel)
                attempt_duration = float(duration) if index == 0 else max(float(duration), 0.6)
                self._driver.drag(
                    attempt_start,
                    attempt_end,
                    steps=drag.steps,
                    duration=attempt_duration,
                    jitter=float(drag.jitter_px),
                    hold_before=float(drag.hold_before),
                    hold_after=_sample_end_hold(),
                )
                self._driver.hotkey("ctrl", "c")
                self._sleep(self._config.capture.copy_wait)
                candidate = self._driver.clipboard_get()
                if candidate.strip() and candidate.strip() != last_sentinel:
                    text = candidate
                    break
        finally:
            if previous:
                self._driver.clipboard_set(previous)

        if not text.strip():
            raise CopyFailed(
                "剪贴板为空：Ctrl+C 未产生消息文本（所有框选起点均未命中；"
                f"message_area={area.as_tuple()}，尝试 {len(attempts)} 组拖拽）",
                hint="确认消息区有文本消息；用 `probe --chat 会话 --debug` 查看实际拖拽坐标",
            )
        return text


def _build_default_tree(config: Config) -> Any:
    from wechat_agent.perception.element_tree import WeChatElementTree

    return WeChatElementTree(config)
