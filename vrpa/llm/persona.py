"""人设热加载（M5-04，平台无关）：按文件 mtime 自动重载，读取失败保留旧版本。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

__all__ = ["DEFAULT_PERSONA", "PersonaLoader"]

DEFAULT_PERSONA = "你是一个真实、简洁、有温度的中文聊天助手。回复口语化，避免 Markdown 与长段落。"


class PersonaLoader:
    """人设文件加载器（线程内单实例；mtime 变化即热加载）。"""

    def __init__(
        self,
        path: Path | str,
        *,
        default: str = DEFAULT_PERSONA,
        mtime: Callable[[Path], float] | None = None,
    ) -> None:
        self._path = Path(path)
        self._default = default
        self._mtime_fn = mtime or (lambda target: target.stat().st_mtime if target.is_file() else -1.0)
        self._cached: str | None = None
        self._cached_mtime = -1.0
        self._version = 0

    @property
    def version(self) -> int:
        return self._version

    @property
    def path(self) -> Path:
        return self._path

    def load(self, *, force: bool = False) -> str:
        current_mtime = self._mtime_fn(self._path)
        if not force and self._cached is not None and current_mtime == self._cached_mtime:
            return self._cached
        try:
            content = self._path.read_text(encoding="utf-8").strip()
        except OSError:
            content = ""
        if not content:
            content = self._cached or self._default
        self._cached = content
        self._cached_mtime = current_mtime
        self._version += 1
        return content

    def reload(self) -> str:
        return self.load(force=True)
