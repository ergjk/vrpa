"""知识接入端 B（M6 控制台预留）：``/knowledge list|reload|add`` 命令。

说明：命令只读写 ``data/knowledge/`` 静态文件，**绝不写入 memory.db**。
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from vrpa.knowledge import FileKnowledgeProvider, KnowledgeChunk

__all__ = ["KnowledgeConsole"]

_USAGE = (
    "用法：/knowledge list [chat]     列出知识（可指定会话）\n"
    "      /knowledge reload         立即热加载\n"
    "      /knowledge add global <标题> <内容>\n"
    "      /knowledge add chat <会话> <标题> <内容>"
)
_SAFE = re.compile(r"[^\w\u4e00-\u9fff.-]+")


class KnowledgeConsole:
    """控制台知识命令处理器（接入端 B 预留）。"""

    def __init__(self, knowledge_dir: Path | str, provider: FileKnowledgeProvider | None = None) -> None:
        self._root = Path(knowledge_dir)
        self._provider = provider or FileKnowledgeProvider(self._root / "global", self._root / "chats")

    @property
    def provider(self) -> FileKnowledgeProvider:
        return self._provider

    def handle(self, line: str) -> str:
        parts = line.strip().split()
        if len(parts) < 2 or parts[0].lower() != "/knowledge":
            return _USAGE
        command = parts[1].lower()
        if command == "list":
            chat = parts[2] if len(parts) > 2 else None
            chunks = self._provider.chunks(chat)
            if not chunks:
                return "（无知识）"
            return "\n".join(f"[{chunk.scope}] {chunk.title}  <- {chunk.source}" for chunk in chunks)
        if command == "reload":
            self._provider.reload()
            return f"知识已重载：{len(self._provider.chunks())} 块"
        if command == "add":
            return self._add(parts)
        return _USAGE

    def _add(self, parts: list[str]) -> str:
        if len(parts) < 5:
            return _USAGE
        scope = parts[2].lower()
        if scope == "global":
            title = parts[3]
            content = " ".join(parts[4:])
            target_dir = self._root / "global"
        elif scope == "chat":
            if len(parts) < 6:
                return _USAGE
            chat_id = parts[3]
            title = parts[4]
            content = " ".join(parts[5:])
            target_dir = self._root / "chats" / chat_id
        else:
            return _USAGE
        target_dir.mkdir(parents=True, exist_ok=True)
        slug = _SAFE.sub("_", title).strip("_")[:40] or "note"
        path = target_dir / f"{time.time_ns()}_{slug}.md"
        path.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
        self._provider.reload()
        return f"已写入 {path}（scope={scope}）"

    def chunks(self, chat_id: str | None = None) -> tuple[KnowledgeChunk, ...]:
        return tuple(self._provider.chunks(chat_id))
