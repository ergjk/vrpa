"""通用 profile 元素树：按 JSON profile 定位元素（平台无关，M0-F-05）。

设计：元素定位算法在 M1 交付；本模块只负责 profile 读取/校验/缓存与
严格失败语义（找不到元素必须抛 ``ElementNotVisible``，禁止坐标兜底）。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from vrpa.errors import ElementNotVisible, TreeConfigError
from vrpa.ports import Rect

__all__ = ["ProfileElementTree"]


class ProfileElementTree:
    """基于 profile JSON 的元素树（平台无关）。"""

    def __init__(self, profile_path: Path, profile_name: str, element_ids: Sequence[str]) -> None:
        self._profile_path = profile_path
        self._profile_name = profile_name
        self._element_ids = tuple(element_ids)
        self._cache: dict[str, Rect] = {}

    def element_ids(self) -> tuple[str, ...]:
        return self._element_ids

    def locate(self, element_id: str) -> Rect:
        cached = self._cache.get(element_id)
        if cached is not None:
            return cached
        profile = self._load_profile()
        elements = profile.get("elements")
        if not isinstance(elements, dict):
            raise TreeConfigError(f"profile 缺少 elements 映射：{self._profile_path}")
        raw = elements.get(element_id)
        rect_value = raw.get("rect") if isinstance(raw, dict) else None
        if isinstance(rect_value, list) and len(rect_value) == 4:
            rect = Rect(int(rect_value[0]), int(rect_value[1]), int(rect_value[2]), int(rect_value[3]))
            self._cache[element_id] = rect
            return rect
        raise ElementNotVisible(f"元素 {element_id} 尚未校准（profile={self._profile_path}；M1 交付锚点匹配）")

    def validate(self) -> bool:
        try:
            profile = self._load_profile()
        except (TreeConfigError, ElementNotVisible):
            return False
        elements = profile.get("elements")
        if not isinstance(elements, dict):
            return False
        return all(element_id in elements for element_id in self._element_ids)

    def invalidate(self) -> None:
        self._cache.clear()

    def profile_name(self) -> str:
        return self._profile_name

    def _load_profile(self) -> dict[str, Any]:
        path = self._profile_path
        if not path.is_file():
            raise ElementNotVisible(f"profile 不存在：{path}（M1 执行 calibrate 生成）")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TreeConfigError(f"无法解析 profile（{path}）：{exc}") from exc
        if not isinstance(data, dict):
            raise TreeConfigError(f"profile 顶层必须是映射：{path}")
        return data
