"""微信感知层：``vrpa.ports.Perception`` 实现（M0-F-05 接线；采集在 M2 落地）。

红线 R3：消息内容唯一来源是「框选 + Ctrl+C」剪贴板文本；本模块在 M2 之前一律抛
``CopyFailed`` / ``SessionSwitchFailed``，绝不返回猜测内容。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vrpa.errors import CopyFailed, SessionSwitchFailed

if TYPE_CHECKING:  # pragma: no cover
    from wechat_agent.core.config import Config


class WeChatPerception:
    """微信窗口激活 / 会话切换 / 消息采集（M1-M2 实现）。"""

    def __init__(self, config: Config) -> None:
        self._config = config

    def activate(self) -> None:
        raise SessionSwitchFailed("M1 未实现：窗口激活与前台校验")

    def switch_session(self, session: str) -> None:
        raise SessionSwitchFailed(f"M1 未实现：会话切换（目标 {session!r}）")

    def capture(self, session: str) -> str:
        raise CopyFailed(f"M2 未实现：框选 + Ctrl+C 采集（会话 {session!r}）")
