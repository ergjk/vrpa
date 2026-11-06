"""微信推理层：``vrpa.ports.Brain`` 实现（M0-F-05 接线；LLM 调用在 M5 落地）。

当前阶段：
    - ``ping()`` 只做“API Key 是否存在”的配置检查，不发网络请求；
    - ``generate()`` 抛 ``LLMError``（M5 前不允许产生不可审计的回复）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from vrpa.errors import LLMError
from vrpa.ports import LLMResult

if TYPE_CHECKING:  # pragma: no cover
    from wechat_agent.core.config import Config


class WeChatBrain:
    """微信推理客户端（M5 实现真实调用）。"""

    def __init__(self, config: Config) -> None:
        self._config = config

    def generate(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        session: str | None = None,
    ) -> LLMResult:
        raise LLMError(f"M5 未实现：LLM 调用（session={session!r}, messages={len(messages)} 条）")

    def ping(self) -> float:
        if not self._config.api_key():
            raise LLMError("DEEPSEEK_API_KEY 未设置（M5 前不阻塞 selftest）")
        return 0.0
