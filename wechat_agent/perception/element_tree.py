"""微信元素树：绑定应用 Config 的 profile 元素树（M0-F-05；锚点算法 M1 落地）。

通用 profile 加载/缓存/失败语义已上提 ``vrpa.element_tree.ProfileElementTree``；
本模块只保留微信的 required 元素集合与 Config 绑定。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vrpa.element_tree import ProfileElementTree
from vrpa.errors import ElementNotVisible, TreeConfigError
from vrpa.ports import Rect

if TYPE_CHECKING:  # pragma: no cover
    from wechat_agent.core.config import Config

ELEMENT_IDS: tuple[str, ...] = (
    "main_window",
    "chat_title",
    "search_box",
    "message_area",
    "input_box",
    "send_button",
)

__all__ = ["ELEMENT_IDS", "WeChatElementTree"]


class WeChatElementTree(ProfileElementTree):
    """微信元素树：有锚点时走框架 AnchorLocator（M1-03），否则使用显式 rect。"""

    def __init__(self, config: Config) -> None:
        super().__init__(config.profile_path(), config.profile_name(), ELEMENT_IDS)
        self._config = config
        self._locator: object | None = None

    def _has_anchors(self) -> bool:
        try:
            profile = self._load_profile()
        except (ElementNotVisible, TreeConfigError):
            return False
        elements = profile.get("elements", {})
        return any(isinstance(value, dict) and value.get("anchors") for value in elements.values())

    def _anchor_locator(self) -> object:
        if self._locator is None:
            from wechat_agent.tools.vision import build_locator

            self._locator = build_locator(self._config)
        return self._locator

    def locate(self, element_id: str) -> Rect:
        if self._has_anchors():
            locator = self._anchor_locator()
            return locator.locate(element_id)  # type: ignore[attr-defined,no-any-return]
        return super().locate(element_id)

    def validate(self) -> bool:
        if self._has_anchors():
            locator = self._anchor_locator()
            return bool(locator.validate(required_ids=self.element_ids()).ok)  # type: ignore[attr-defined]
        return super().validate()

    def invalidate(self) -> None:
        super().invalidate()
        if self._locator is not None:
            self._locator.invalidate()  # type: ignore[attr-defined]
