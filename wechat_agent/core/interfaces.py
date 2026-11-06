"""应用层接口契约（M0-05；M0-F-05 已与 ``vrpa.ports`` 统一）。

本模块不再重复定义端口与 DTO，而是把框架契约按**应用语义**重命名导出：
    UiaTree     = vrpa.ports.ElementTree
    MemoryHub   = vrpa.ports.MemoryStore
    ChatMessage = vrpa.ports.Message
其余端口 / DTO（Perception / Executor / Brain / Rect / IncomingMessage /
SendOutcome / LLMResult / MemoryItem）与框架同名同源。

纪律：
    - 本文件只做别名与 V1.1/V1.2 预留接口，不再定义 V1.0 端口实现；
    - 红线 R1：V1.1/V1.2 接口名仅允许出现在本文件，且只允许空签名；
    - 零第三方依赖：仅 import ``vrpa.ports`` 与标准库。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from vrpa.ports import (
    Brain,
    ElementTree,
    Executor,
    IncomingMessage,
    LLMResult,
    MemoryItem,
    MemoryStore,
    Message,
    Perception,
    Ports,
    Rect,
    SendOutcome,
)

INTERFACE_VERSION = 1
FUTURE_POLICY = "V1.1/V1.2 reserved, DO NOT IMPLEMENT in V1.0 (red line R1)"
VERSION_NOTE = "接口契约版本 1（M0-05 冻结；M0-F-05 与 vrpa.ports 统一；变更需升 INTERFACE_VERSION 并同步 Fake 后端）"

# ============================================================================
# 应用语义别名（旧名保持可用，底层对象即框架契约）
# ============================================================================
UiaTree = ElementTree
MemoryHub = MemoryStore
ChatMessage = Message

CORE_PROTOCOLS: Mapping[str, type] = {
    "UiaTree": UiaTree,
    "Perception": Perception,
    "Executor": Executor,
    "Brain": Brain,
    "MemoryHub": MemoryHub,
}


# ============================================================================
# V1.1 / V1.2 保留空接口（红线 R1：仅签名，DO NOT IMPLEMENT in V1.0）
# ============================================================================
class RecallController(Protocol):
    """V1.1 预留：消息撤回（右键菜单 RPA + 2 分钟时限）。DO NOT IMPLEMENT in V1.0。"""

    def should_recall(self, draft: str, context: Mapping[str, Any]) -> bool: ...

    def recall_last(self, chat: str) -> bool: ...


class SelfReviewHook(Protocol):
    """V1.1 预留：发送前二次审查（Self-Reflection）。DO NOT IMPLEMENT in V1.0。"""

    def review(self, draft: str, chat: str) -> bool: ...


class EmojiRenderer(Protocol):
    """V1.1 预留：表情截图库匹配与发送。DO NOT IMPLEMENT in V1.0。"""

    def render(self, emotion: str) -> bytes | None: ...

    def send_emoji(self, chat: str, emotion: str) -> bool: ...


class MultimodalIO(Protocol):
    """V1.1/V1.2 预留：语音（TTS/虚拟声卡）与生图等多模态扩展。DO NOT IMPLEMENT in V1.0。"""

    def synthesize_voice(self, text: str) -> bytes | None: ...

    def generate_image(self, prompt: str) -> bytes | None: ...


class BehaviorClone(Protocol):
    """V1.2 预留：行为克隆（回复节奏/口癖/常用语学习）。DO NOT IMPLEMENT in V1.0。"""

    def learn(self, samples: Sequence[str]) -> None: ...

    def style(self, text: str) -> str: ...


FUTURE_INTERFACES: Mapping[str, type] = {
    "RecallController": RecallController,
    "SelfReviewHook": SelfReviewHook,
    "EmojiRenderer": EmojiRenderer,
    "MultimodalIO": MultimodalIO,
    "BehaviorClone": BehaviorClone,
}

FUTURE_FEATURES: Mapping[str, str] = {
    "RecallController": "V1.1 消息撤回与情绪模拟（右键菜单 RPA）",
    "SelfReviewHook": "V1.1 发送前二次审查（Self-Reflection）",
    "EmojiRenderer": "V1.1 动画表情（本地 emoji_lib 截图匹配）",
    "MultimodalIO": "V1.1/V1.2 语音 TTS 与生图等多模态输入输出",
    "BehaviorClone": "V1.2 行为克隆（节奏/口癖/常用语）",
}


__all__ = [
    "INTERFACE_VERSION",
    "FUTURE_POLICY",
    "VERSION_NOTE",
    "Rect",
    "ChatMessage",
    "IncomingMessage",
    "SendOutcome",
    "LLMResult",
    "MemoryItem",
    "UiaTree",
    "Perception",
    "Executor",
    "Brain",
    "MemoryHub",
    "Ports",
    "CORE_PROTOCOLS",
    "RecallController",
    "SelfReviewHook",
    "EmojiRenderer",
    "MultimodalIO",
    "BehaviorClone",
    "FUTURE_INTERFACES",
    "FUTURE_FEATURES",
]
