"""知识接入（应用层）：data/knowledge 目录 + 检索门面构造。"""

from __future__ import annotations

from vrpa.knowledge import FileKnowledgeProvider, KnowledgeBase
from wechat_agent.knowledge.provider import build_knowledge_base, knowledge_root

__all__ = ["FileKnowledgeProvider", "KnowledgeBase", "build_knowledge_base", "knowledge_root"]
