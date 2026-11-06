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
_HOLD_AFTER_CHOICES = (2.0, 2.5, 3.0)
_HOLD_AFTER_MULTI_CHOICES = (3.0, 4.0, 5.0)
_HOLD_POISSON_LAMBDA = 1.0


def _sample_end_hold(*, multi: bool = False) -> float:
    """终点停留：普通 2~3s；多条（由下往上/越界）3/4/5s，泊松权重 + 抖动。"""
    choices = _HOLD_AFTER_MULTI_CHOICES if multi else _HOLD_AFTER_CHOICES
    jitter = 0.2 if multi else 0.1
    weights = []
    for index, _choice in enumerate(choices, start=1):
        weight = math.exp(-_HOLD_POISSON_LAMBDA) * (_HOLD_POISSON_LAMBDA**index) / math.factorial(index)
        weights.append(weight)
    base = random.choices(choices, weights=weights, k=1)[0]
    floor = 3.0 if multi else 2.0
    return round(max(floor, base + random.uniform(-jitter, jitter)), 3)


# 首次失败后的恢复轨迹：滚到底部，再从对方气泡下方拖到贴紧上边界。
# 起点落在头像列/气泡左侧，横向覆盖“头像-气泡”区；终点越过下边界。
_EDGE_DRAG_PLAN: tuple[tuple[float, float], tuple[float, float]] = ((0.02, 0.01), (0.95, 1.02))
# 恢复重试轨迹：略高起点，避免首条/末条气泡边缘选不中。
_RETRY_DRAG_PLAN: tuple[tuple[float, float], tuple[float, float]] = ((0.06, 0.03), (0.95, 1.00))


def _start_outside_bubble(text_area: Rect, bubble_area: Rect) -> tuple[int, int] | None:
    """起点区 = 文本框区 - (文本框区 ∩ 气泡-头像区)，取剩余横向较宽区间的顶部中点。"""
    overlap_left = max(text_area.x, bubble_area.x)
    overlap_right = min(text_area.right, bubble_area.right)
    if overlap_right <= overlap_left:
        candidates = [(text_area.x, text_area.right)]
    else:
        candidates = []
        if overlap_left > text_area.x:
            candidates.append((text_area.x, overlap_left))
        if overlap_right < text_area.right:
            candidates.append((overlap_right, text_area.right))
    candidates = [span for span in candidates if span[1] > span[0]]
    if not candidates:
        return None
    left, right = max(candidates, key=lambda span: (span[1] - span[0], span[0]))
    return ((left + right) // 2, text_area.y + 2)


# 多条采集：终点越界（-5%），配合更长停留，尽量一次划到顶部。
_EDGE_MULTI_DRAG_PLAN: tuple[tuple[float, float], tuple[float, float]] = ((0.02, 0.01), (0.95, 1.03))


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
        self.last_capture_info: dict[str, object] = {}
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

    def scroll_to_bottom(self) -> None:
        """滚轮向下 + Ctrl+End 回到底部（陈旧窗口重试用）。"""
        area, _start, _end, _duration = self.drag_plan()
        clicks = int(self._config.capture.scroll_to_bottom_clicks)
        if clicks > 0:
            self._driver.scroll_at(area.center[0], area.center[1], -clicks)
            self._sleep(0.5)
        self._driver.click(area.x + 12, area.center[1])
        for _ in range(5):
            self._driver.hotkey("pagedown")
        self._driver.hotkey("ctrl", "end")
        self._sleep(0.5)

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

        # 真机规则：首次框选失败 -> 先把消息区滚到底部 -> 贴边由下往上重试一次；
        # 仍失败则放弃（不再盲试多个起点，避免选中旧消息/浪费一轮时间）。
        multi_message = end[1] < start[1] or drag.from_y < 0 or drag.from_y > 1 or drag.to_y < 0 or drag.to_y > 1
        start_source = "config"
        if multi_message:
            bubble_area = None
            try:
                bubble_area = self._tree.locate("bubble_avatar_area")
            except (ElementNotVisible, TreeConfigError):
                bubble_area = None
            if bubble_area is not None:
                computed = _start_outside_bubble(area, bubble_area)
                if computed is not None:
                    start = computed
                    start_source = "message_area-bubble_avatar_area"
            if start_source == "config":
                try:
                    start_area = self._tree.locate("drag_start_area")
                except (ElementNotVisible, TreeConfigError):
                    start_area = None
                if start_area is not None:
                    # 显式起点区：顶部中点
                    start = (start_area.center[0], start_area.y + 2)
                    start_source = "drag_start_area"
        retry_start = (
            area.x + int(round(area.width * _RETRY_DRAG_PLAN[0][0])),
            area.y + int(round(area.height * _RETRY_DRAG_PLAN[0][1])),
        )
        retry_end = (
            area.x + int(round(area.width * _RETRY_DRAG_PLAN[1][0])),
            area.y + int(round(area.height * _RETRY_DRAG_PLAN[1][1])),
        )
        attempts: list[tuple[tuple[int, int], tuple[int, int]]] = [(start, end)]
        if (retry_start, retry_end) != (start, end):
            attempts.append((retry_start, retry_end))

        scroll_clicks = int(self._config.capture.scroll_to_bottom_clicks)
        scroll_count = 0
        scroll_methods: list[str] = []
        self.last_capture_info = {
            "multi": multi_message,
            "attempts": len(attempts),
            "scroll_clicks": scroll_clicks,
            "scroll_count": 0,
            "scroll_methods": scroll_methods,
            "start_source": start_source,
        }

        def _reset_to_bottom() -> None:
            nonlocal scroll_count
            if scroll_clicks > 0:
                self._driver.scroll_at(area.center[0], area.center[1], -scroll_clicks)
                scroll_methods.append("wheel")
                scroll_count += 1
                self._sleep(0.4)
            # 键盘兜底：点击消息区空白处，PageDown 多次 + Ctrl+End 跳到最新
            self._driver.click(area.x + 12, area.center[1])
            for _ in range(5):
                self._driver.hotkey("pagedown")
            self._driver.hotkey("ctrl", "end")
            scroll_methods.append("pagedown")
            scroll_methods.append("ctrl+end")
            self._sleep(0.4)

        if multi_message:
            # 多条采集先从底部开始：保证最新消息一定在可视区内
            _reset_to_bottom()

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
                    hold_after=_sample_end_hold(multi=multi_message),
                )
                self._driver.hotkey("ctrl", "c")
                self._sleep(self._config.capture.copy_wait)
                candidate = self._driver.clipboard_get()
                if candidate.strip() and candidate.strip() != last_sentinel:
                    text = candidate
                    self.last_capture_info["attempt_used"] = index + 1
                    self.last_capture_info["scroll_count"] = scroll_count
                    self.last_capture_info["chars"] = len(text)
                    break
                if index == 0 and len(attempts) > 1:
                    # 首次没选中：滚到最底部，保证新消息在可视区，再试一次贴边轨迹
                    _reset_to_bottom()
        finally:
            if previous:
                self._driver.clipboard_set(previous)

        if not text.strip():
            self.last_capture_info["attempt_used"] = 0
            self.last_capture_info["scroll_count"] = scroll_count
            raise CopyFailed(
                "剪贴板为空：Ctrl+C 未产生消息文本（首次未选中且滚到底部重试仍未命中；"
                f"message_area={area.as_tuple()}，尝试 {len(attempts)} 组拖拽）",
                hint="确认消息区有文本消息；用 `probe --chat 会话 --debug` 查看实际拖拽坐标",
            )
        return text


def _build_default_tree(config: Config) -> Any:
    from wechat_agent.perception.element_tree import WeChatElementTree

    return WeChatElementTree(config)
