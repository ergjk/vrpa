"""微信感知层（M2-02/03）：窗口激活、会话切换、框选 + Ctrl+C 采集。

红线 R3：消息内容唯一来源 = 「框选 + Ctrl+C」剪贴板文本；本模块不做任何图像识别。
真实鼠标/键盘/窗口由 Driver/WindowBackend 注入；单元测试全部使用 Fakes。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from vrpa.errors import CopyFailed, ElementNotVisible, TreeConfigError
from vrpa.vision.driver import Driver, PyAutoGuiDriver
from wechat_agent.perception.session import WeChatSessionSwitcher
from wechat_agent.perception.window import WeChatWindow

if TYPE_CHECKING:  # pragma: no cover
    from wechat_agent.core.config import Config

__all__ = ["WeChatPerception"]


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

    def switch_session(self, session: str) -> None:
        self._session.ensure_chat(session)

    def capture(self, session: str) -> str:
        """框选消息区 + Ctrl+C，返回剪贴板原始文本。"""
        self._window.ensure_foreground()
        try:
            area = self._tree.locate("message_area")
        except (ElementNotVisible, TreeConfigError) as exc:
            raise ElementNotVisible(f"无法定位消息区：{exc}") from exc

        drag = self._config.capture.drag
        start = (
            area.x + int(round(area.width * drag.from_x)),
            area.y + int(round(area.height * drag.from_y)),
        )
        end = (
            area.x + int(round(area.width * drag.to_x)),
            area.y + int(round(area.height * drag.to_y)),
        )
        if start == end:
            raise CopyFailed(f"框选起点与终点相同（message_area={area.as_tuple()}）")

        previous = ""
        if self._config.capture.restore_clipboard:
            try:
                previous = self._driver.clipboard_get()
            except CopyFailed:
                previous = ""

        try:
            self._driver.drag(start, end, steps=drag.steps, duration=drag.duration)
            self._driver.hotkey("ctrl", "c")
            self._sleep(self._config.capture.copy_wait)
            text = self._driver.clipboard_get()
        finally:
            if previous:
                self._driver.clipboard_set(previous)

        if not text.strip():
            raise CopyFailed(
                f"剪贴板为空：框选可能失败（会话 {session!r}）；运行 `python -m wechat_agent probe` 诊断",
                hint="确认消息区非空、框选未命中滚动条/头像，且复制等待时间足够",
            )
        return text


def _build_default_tree(config: Config) -> Any:
    from wechat_agent.perception.element_tree import WeChatElementTree

    return WeChatElementTree(config)
