"""微信会话切换（M2-02）：定位搜索框 -> 粘贴会话名 -> 回车 -> 校验。"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING

from vrpa.errors import CopyFailed, ElementNotVisible, SessionSwitchFailed, TreeConfigError
from vrpa.vision.driver import Driver
from wechat_agent.identity import IdentityMap, load_identity

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
        identity: IdentityMap | None = None,
    ) -> None:
        self._config = config
        self._tree = tree
        self._driver = driver
        self._window = window
        self._capture = capture
        self._sleep = sleep
        self._identity = identity

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
            if chat and chat in text:
                return
            identity = self._identity if self._identity is not None else load_identity(self._config.data_dir)
            if self._identity is None:
                self._identity = identity
            nicknames = identity.nicknames_for(chat)
            if nicknames:
                if any(nickname in text for nickname in nicknames):
                    return
                raise SessionSwitchFailed(
                    f"切换后采集内容未包含会话名 {chat!r} 的已知昵称 {nicknames}；"
                    "请在 data/identity.toml 更新对方昵称映射"
                )
            if self._config.capture.title_verify == "search_text":
                raise SessionSwitchFailed(f"切换后采集内容未包含会话名 {chat!r}")
            raise SessionSwitchFailed(
                f"切换后采集内容未包含会话名 {chat!r}；微信 4.x 剪贴板只有昵称时，"
                "请在 data/identity.toml 配置该会话的 nicknames 映射"
            )
            return
        try:
            self._tree.locate("chat_title")  # type: ignore[attr-defined]
        except (ElementNotVisible, TreeConfigError) as exc:
            raise SessionSwitchFailed(f"切换后会话标题不可见：{exc}") from exc
