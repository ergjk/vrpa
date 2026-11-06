"""微信会话切换（M2-02）：定位搜索框 -> 粘贴会话名 -> 回车 -> 校验。"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING

from vrpa.errors import CopyFailed, ElementNotVisible, SessionSwitchFailed, TreeConfigError
from vrpa.vision.driver import Driver

if TYPE_CHECKING:  # pragma: no cover
    from wechat_agent.core.config import Config
    from wechat_agent.perception.window import WeChatWindow

__all__ = ["WeChatSessionSwitcher"]

_SWITCH_ELEMENT = {"search_box": "search_box", "session_list": "message_area"}


class WeChatSessionSwitcher:
    """按配置的 ``uia_tree.switch_chat`` 方式切换会话并校验。"""

    def __init__(
        self,
        config: Config,
        tree: object,
        driver: Driver,
        *,
        window: WeChatWindow | None = None,
        capture: Callable[[str], str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._tree = tree
        self._driver = driver
        self._window = window
        self._capture = capture
        self._sleep = sleep

    def ensure_chat(self, chat: str) -> None:
        if not chat.strip():
            raise SessionSwitchFailed("会话名不能为空")
        if self._window is not None:
            self._window.ensure_foreground()

        mode = self._config.wechat.switch_chat
        element_id = _SWITCH_ELEMENT.get(mode, "search_box")
        try:
            rect = self._tree.locate(element_id)  # type: ignore[attr-defined]
        except (ElementNotVisible, TreeConfigError) as exc:
            raise SessionSwitchFailed(f"无法定位会话切换入口 {element_id}：{exc}") from exc

        previous = ""
        try:
            previous = self._driver.clipboard_get()
        except CopyFailed:
            previous = ""
        try:
            self._driver.click(*rect.center)
            self._driver.hotkey("ctrl", "a")
            self._driver.clipboard_set(chat)
            self._driver.hotkey("ctrl", "v")
            self._driver.hotkey("enter")
            self._sleep(0.15)
        finally:
            if previous:
                self._driver.clipboard_set(previous)

        with suppress(Exception):
            self._tree.invalidate()  # type: ignore[attr-defined]
        self._verify(chat)

    # ------------------------------------------------------------ 内部
    def _verify(self, chat: str) -> None:
        if self._capture is not None:
            try:
                text = self._capture(chat)
            except (CopyFailed, ElementNotVisible, TreeConfigError) as exc:
                raise SessionSwitchFailed(f"切换后采集失败，无法确认会话 {chat!r}：{exc}") from exc
            if chat and chat not in text:
                raise SessionSwitchFailed(f"切换后采集内容未包含会话名 {chat!r}")
            return
        try:
            self._tree.locate("chat_title")  # type: ignore[attr-defined]
        except (ElementNotVisible, TreeConfigError) as exc:
            raise SessionSwitchFailed(f"切换后会话标题不可见：{exc}") from exc
