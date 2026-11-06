"""Prompt 预算裁剪策略（M5-02）：全局配置 + ``sessions/<chat_id>/prompt.json`` 会话级覆盖。"""

from __future__ import annotations

import json
from pathlib import Path

__all__ = ["DEFAULT_TRIM_POLICY", "TRIM_POLICIES", "TrimPolicyResolver"]

DEFAULT_TRIM_POLICY = "history_first"
TRIM_POLICIES = ("history_first", "memory_first", "knowledge_first")
SESSION_POLICY_FILE = "prompt.json"


class TrimPolicyResolver:
    """解析会话级裁剪策略：``{"trim_policy": "knowledge_first"}``，非法/缺失回退全局。"""

    def __init__(
        self,
        global_policy: str = DEFAULT_TRIM_POLICY,
        sessions_root: Path | str | None = None,
    ) -> None:
        self._global = global_policy if global_policy in TRIM_POLICIES else DEFAULT_TRIM_POLICY
        self._sessions_root = Path(sessions_root) if sessions_root is not None else None

    @property
    def global_policy(self) -> str:
        return self._global

    def session_path(self, chat_id: str) -> Path | None:
        if self._sessions_root is None or not chat_id:
            return None
        return self._sessions_root / chat_id / SESSION_POLICY_FILE

    def resolve(self, chat_id: str | None = None) -> str:
        path = self.session_path(chat_id or "")
        if path is None or not path.is_file():
            return self._global
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._global
        value = data.get("trim_policy") if isinstance(data, dict) else None
        return value if value in TRIM_POLICIES else self._global
