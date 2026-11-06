"""微信执行层：``vrpa.ports.Executor`` 实现（M0-F-05 接线；真实发送在 M6 落地）。

当前阶段：
    - ``dry_run`` 时直接返回 ``SendOutcome(stage="dry_run")``，不触碰键鼠；
    - 非 dry_run 一律抛 ``VerifyFailed``（M6 之前绝不真实发送）；
    - 三重校验（会话 / 焦点 / 内容）在 M6 实现。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vrpa.errors import VerifyFailed
from vrpa.ports import SendOutcome

if TYPE_CHECKING:  # pragma: no cover
    from wechat_agent.core.config import Config


class WeChatExecutor:
    """微信发送执行器（干跑可用，真实发送 M6）。"""

    def __init__(self, config: Config) -> None:
        self._config = config

    def send(self, session: str, text: str, *, trigger: str = "auto") -> SendOutcome:
        if self._config.app.dry_run:
            return SendOutcome(ok=True, stage="dry_run", detail=text)
        raise VerifyFailed(f"M6 未实现：真实发送必须完成三重校验（session={session!r}, trigger={trigger!r}）")

    def clear_input(self) -> str:
        return ""

    def is_dry_run(self) -> bool:
        return self._config.app.dry_run
