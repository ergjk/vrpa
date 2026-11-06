"""微信记忆层适配器：把 ``vrpa.memory.store.SQLiteMemoryStore`` 绑定到应用 Config（M0-F-05）。

通用双库实现已上提框架；本模块只做「Config -> data_dir」的薄适配。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vrpa.memory.store import SQLiteMemoryStore, content_hash, normalize_text

if TYPE_CHECKING:  # pragma: no cover
    from wechat_agent.core.config import Config

__all__ = ["WeChatMemoryStore", "content_hash", "normalize_text"]


class WeChatMemoryStore(SQLiteMemoryStore):
    """微信应用版 MemoryStore（入参为应用 Config）。"""

    def __init__(self, config: Config) -> None:
        super().__init__(config.data_dir)
