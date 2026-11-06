"""文件知识 Provider（接入端 A：data/knowledge/ 静态只读目录，mtime 热加载）。"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from vrpa.knowledge import KnowledgeChunk

__all__ = ["FileKnowledgeProvider"]


class FileKnowledgeProvider:
    """目录布局：

    ``<global_dir>/*.md``              -> scope=global
    ``<chats_dir>/<chat_id>/*.md``     -> scope=chat
    """

    def __init__(self, global_dir: Path | str, chats_dir: Path | str) -> None:
        self._global_dir = Path(global_dir)
        self._chats_dir = Path(chats_dir)
        self._signature: tuple[tuple[str, float, int], ...] = ()
        self._cache: tuple[KnowledgeChunk, ...] = ()

    @property
    def global_dir(self) -> Path:
        return self._global_dir

    @property
    def chats_dir(self) -> Path:
        return self._chats_dir

    def reload(self) -> None:
        self._signature = ()
        self._cache = ()

    def chunks(self, chat_id: str | None = None) -> Sequence[KnowledgeChunk]:
        files = self._files(chat_id)
        signature = tuple(
            (str(path), path.stat().st_mtime, path.stat().st_size) for path, _scope in files if path.is_file()
        )
        if signature == self._signature and self._cache:
            return self._cache
        chunks: list[KnowledgeChunk] = []
        for path, scope in files:
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError:
                continue
            title, content = _split_title(raw, path)
            if content.strip():
                chunks.append(KnowledgeChunk(scope=scope, title=title, content=content.strip(), source=str(path)))
        self._signature = signature
        self._cache = tuple(chunks)
        return self._cache

    def _files(self, chat_id: str | None) -> list[tuple[Path, str]]:
        files: list[tuple[Path, str]] = []
        if self._global_dir.is_dir():
            files.extend((path, "global") for path in sorted(self._global_dir.glob("*.md")))
        if chat_id and self._chats_dir.is_dir():
            chat_dir = self._chats_dir / chat_id
            if chat_dir.is_dir():
                files.extend((path, "chat") for path in sorted(chat_dir.glob("*.md")))
        return files


def _split_title(raw: str, path: Path) -> tuple[str, str]:
    lines = raw.splitlines()
    if lines and lines[0].lstrip().startswith("# "):
        return lines[0].lstrip()[2:].strip() or path.stem, "\n".join(lines[1:])
    return path.stem, raw
