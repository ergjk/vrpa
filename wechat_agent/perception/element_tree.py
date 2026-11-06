"""微信元素树：绑定应用 Config 的 profile 元素树（M0-F-05；锚点算法 M1 落地）。

通用 profile 加载/缓存/失败语义已上提 ``vrpa.element_tree.ProfileElementTree``；
本模块只保留微信的 required 元素集合与 Config 绑定。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vrpa.element_tree import ProfileElementTree

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
    """微信元素树（profile 路径/名称来自应用配置）。"""

    def __init__(self, config: Config) -> None:
        super().__init__(config.profile_path(), config.profile_name(), ELEMENT_IDS)
