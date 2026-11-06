"""知识接入端 A（M5-02）：直接读取 ``data/knowledge/`` 静态只读 md。

目录布局：
    data/knowledge/global/*.md          全局知识
    data/knowledge/chats/<chat_id>/*.md 专属知识
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from vrpa.knowledge import FileKnowledgeProvider, KnowledgeBase

if TYPE_CHECKING:  # pragma: no cover
    from wechat_agent.core.config import Config

KNOWLEDGE_MAX_CHUNKS = 6
KNOWLEDGE_MAX_CHARS = 2000


def knowledge_root(config: Config) -> Path:
    return config.data_dir / "knowledge"


def build_knowledge_base(config: Config) -> KnowledgeBase:
    root = knowledge_root(config)
    provider = FileKnowledgeProvider(root / "global", root / "chats")
    return KnowledgeBase(provider, max_chunks=KNOWLEDGE_MAX_CHUNKS, max_chars=KNOWLEDGE_MAX_CHARS)
