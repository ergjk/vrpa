"""V1.0 接口契约 + V1.1/V1.2 保留空接口（里程碑 M0-05）。

目的：
    1. 六层之间只通过本文件的 Protocol 通信；M4 可注入 Fake 后端，
       实现「无微信环境跑通全流程」（DoD 依赖于此）；
    2. 所有 DTO（Rect / ChatMessage / IncomingMessage / SendOutcome / LLMResult /
       MemoryItem）集中定义，避免各层重复造类型、避免字段漂移；
    3. 红线 R1 的落点：V1.1/V1.2 功能（撤回/二次审查/表情/语音/生图/行为克隆）
       只允许在本文件保留**空 Protocol**，禁止任何实现代码进入其它模块；
       由 tests/test_interfaces.py 的 R1 静态扫描强制。

本文件纪律：
- 只依赖标准库（typing / dataclasses）；不 import 任何其它 wechat_agent 模块，
  保证零依赖、可被任意层与测试安全导入；
- 所有协议方法只写签名与 docstring，函数体一律 `...`（不允许实现）；
- 所有 DTO 为 frozen dataclass。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

INTERFACE_VERSION = 1
FUTURE_POLICY = "V1.1/V1.2 reserved, DO NOT IMPLEMENT in V1.0 (red line R1)"

# 供 CLI --help / 文档引用的说明
VERSION_NOTE = "接口契约版本 1（M0-05 冻结；变更需升 INTERFACE_VERSION 并同步 Fake 后端）"


# ============================================================================
# DTO（跨层数据契约）
# ============================================================================
@dataclass(frozen=True)
class Rect:
    """屏幕绝对坐标矩形（像素，左上角原点，多屏可为负坐标）。"""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        for name, value in (("x", self.x), ("y", self.y), ("width", self.width), ("height", self.height)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"Rect.{name} 必须是整数，实际为 {value!r}")
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"Rect 宽高必须为正：{self.width}x{self.height}")

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)


@dataclass(frozen=True)
class ChatMessage:
    """流水库中的一条消息（role/direction 与 DB 对齐）。"""

    direction: str  # in | out | self | system
    content: str
    role: str = "user"  # user | assistant | system
    sender: str | None = None
    ts: str | None = None
    source: str = "rpa_capture"  # rpa_capture | self_writeback | console_override | plugin
    status: str = "ok"  # ok | recalled | pending_confirm | failed


@dataclass(frozen=True)
class IncomingMessage:
    """去重对齐后的「新增消息」候选（direction 由 MemoryHub/去重层判定）。"""

    content: str
    sender: str | None = None
    ts: str | None = None
    confidence: float = 1.0
    reason: str = ""  # anchor_high | anchor_single | count_diff | low_confidence ...


@dataclass(frozen=True)
class SendOutcome:
    """执行层发送结果（用于审计与熔断计数）。"""

    ok: bool
    stage: str  # sent | dry_run | verify_failed | element_missing | skipped
    detail: str = ""
    trace_id: str = "-"


@dataclass(frozen=True)
class LLMResult:
    """推理层输出（含用量，供 /status 与审计）。"""

    text: str
    model: str = ""
    usage: Mapping[str, int] = field(default_factory=dict)
    latency_ms: float = 0.0


@dataclass(frozen=True)
class MemoryItem:
    """核心档案库条目。"""

    content: str
    category: str = "event"  # profile | preference | event | relation | rule | summary
    chat: str | None = None  # None = 跨会话全局
    key: str | None = None
    confidence: float = 0.7
    importance: float = 0.5
    memory_id: int | None = None


# ============================================================================
# V1.0 核心协议（M1/M2/M3/M5/M6 实现；M4 注入 Fake）
# ============================================================================
@runtime_checkable
class UiaTree(Protocol):
    """假 UIA 树：只回答「点哪里/输到哪」，绝不读取消息内容（红线 R3）。"""

    def element_ids(self) -> Sequence[str]:
        """已校准的元素 id 列表（main_window/message_area/search_box/input_box...）。"""
        ...

    def locate(self, element_id: str) -> Rect:
        """锚点图匹配 -> 屏幕绝对坐标；失败抛 ElementNotVisible，禁止比例坐标兜底。"""
        ...

    def validate(self) -> bool:
        """现场严格校验全部 required 元素（validate-tree --strict 的底层实现）。"""
        ...

    def invalidate(self) -> None:
        """任何点击/滚动/粘贴/发送后立即失效缓存。"""
        ...

    def profile_name(self) -> str:
        """当前 profile 名（如 "2560x1440@1.25"）。"""
        ...


@runtime_checkable
class Perception(Protocol):
    """感知层：消息内容的**唯一**来源是 capture() 的「框选 + Ctrl+C」剪贴板文本。"""

    def activate(self) -> None:
        """激活微信主窗口并校验前台（失败抛 WindowNotFound/WindowNotForeground）。"""
        ...

    def ensure_chat(self, chat: str) -> None:
        """假 UIA 树定位搜索框 -> 粘贴会话名 -> 回车 -> 会话校验（失败抛 SessionSwitchFailed）。"""
        ...

    def capture(self, chat: str) -> str:
        """框选消息区 + Ctrl+C，返回剪贴板原始文本（失败抛 CopyFailed）。"""
        ...


@runtime_checkable
class Executor(Protocol):
    """执行层：定位输入框 -> 粘贴 -> 三重校验 -> 回车 -> 回写。dry_run 时只模拟。"""

    def send(self, chat: str, text: str, *, trigger: str = "auto") -> SendOutcome:
        """trigger: auto | override | plugin | retry（写入审计）。"""
        ...

    def clear_input(self) -> str:
        """清空输入框，返回清空前内容（供失败重试与审计）。"""
        ...

    def is_dry_run(self) -> bool:
        """当前是否干跑（不真实发送）。"""
        ...


@runtime_checkable
class Brain(Protocol):
    """推理层：接收已组装的 messages（OpenAI 兼容格式）并返回结果。"""

    def generate(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        chat: str | None = None,
    ) -> LLMResult:
        """messages: [{"role": "system|user|assistant", "content": "..."}]；失败抛 LLMError。"""
        ...

    def ping(self) -> float:
        """连通性探测，返回延迟毫秒；失败抛 LLMError。"""
        ...


@runtime_checkable
class MemoryHub(Protocol):
    """记忆层：双库（流水 chat_history / 档案 memory）统一门面。"""

    def recent_hashes(self, chat: str, limit: int) -> Sequence[str]:
        """流水库最近 N 条消息的 content_hash（旧 -> 新），供去重尾部锚点对齐。"""
        ...

    def insert_messages(self, chat: str, messages: Sequence[IncomingMessage]) -> int:
        """批量入库（含 direction 判定与 dedup_count 维护），返回新增条数。"""
        ...

    def writeback(self, chat: str, text: str) -> int:
        """发送成功后的状态回写（direction=out / role=assistant），返回 msg id。"""
        ...

    def history(self, chat: str, limit: int) -> Sequence[ChatMessage]:
        """取最近 N 条流水（旧 -> 新），用于 Prompt 组装。"""
        ...

    def recall(self, chat: str | None, query: str, top_k: int) -> Sequence[MemoryItem]:
        """档案库召回（chat=None 表示跨会话全局事实）。"""
        ...

    def add_memory(self, item: MemoryItem) -> int:
        """幂等 upsert 一条档案，返回 id。"""
        ...

    def forget(self, memory_id: int) -> bool:
        """软删一条档案（可撤销），返回是否命中。"""
        ...


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
    "CORE_PROTOCOLS",
    "RecallController",
    "SelfReviewHook",
    "EmojiRenderer",
    "MultimodalIO",
    "BehaviorClone",
    "FUTURE_INTERFACES",
    "FUTURE_FEATURES",
]
