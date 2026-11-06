"""框架端口（Ports）与跨层 DTO：平台无关的最小能力契约。

设计依据：docs/ADR/0003-interface-stability.md
    - 端口只约束**行为语义**，不约束实现技术路线（元素定位可以换算法、解析可以换策略）；
    - 平台差异全部由 ``PlatformAdapter`` 实现注入；
    - 本模块零第三方依赖、零平台名。

端口清单：
    ElementTree   元素定位（失败必须抛 ElementNotVisible，禁止坐标兜底）
    Perception    会话切换 + 消息采集（消息内容只能来自采集通道）
    Executor      发送（必须完成发送前三重校验）
    Brain         推理（失败必须抛 LLMError）
    MemoryStore   记忆读写（写回幂等、历史按旧到新返回）

M0-F-04 只落地契约与测试套件；应用层现有接口的迁移在 M0-F-05 完成。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "Brain",
    "ElementTree",
    "Executor",
    "IncomingMessage",
    "LLMResult",
    "MemoryItem",
    "MemoryStore",
    "Message",
    "Perception",
    "Ports",
    "Rect",
    "SendOutcome",
]


# ============================================================================
# DTO
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
class Message:
    """一条已入库消息（流水库结构对齐）。"""

    direction: str  # in | out | self | system
    content: str
    role: str = "user"  # user | assistant | system
    sender: str | None = None
    ts: str | None = None
    source: str = "capture"  # capture | writeback | override | plugin
    status: str = "ok"  # ok | recalled | pending_confirm | failed


@dataclass(frozen=True)
class IncomingMessage:
    """采集/解析后的新增消息候选。"""

    content: str
    sender: str | None = None
    ts: str | None = None
    confidence: float = 1.0
    reason: str = ""


@dataclass(frozen=True)
class SendOutcome:
    """执行层发送结果（用于审计与熔断计数）。"""

    ok: bool
    stage: str  # sent | dry_run | verify_failed | element_missing | skipped
    detail: str = ""
    trace_id: str = "-"


@dataclass(frozen=True)
class LLMResult:
    """推理层输出（含用量与延迟）。"""

    text: str
    model: str = ""
    usage: Mapping[str, int] = field(default_factory=dict)
    latency_ms: float = 0.0


@dataclass(frozen=True)
class MemoryItem:
    """核心档案库条目。"""

    content: str
    category: str = "event"
    chat: str | None = None
    key: str | None = None
    confidence: float = 0.7
    importance: float = 0.5
    memory_id: int | None = None


# ============================================================================
# 端口协议
# ============================================================================
@runtime_checkable
class ElementTree(Protocol):
    """元素树：只回答「点哪里 / 输到哪」，不读取消息内容。"""

    def element_ids(self) -> Sequence[str]:
        """已校准的元素 id 列表。"""
        ...

    def locate(self, element_id: str) -> Rect:
        """锚点匹配 -> 屏幕绝对坐标；失败必须抛 ElementNotVisible（禁止兜底）。"""
        ...

    def validate(self) -> bool:
        """现场严格校验全部 required 元素。"""
        ...

    def invalidate(self) -> None:
        """任何界面动作后立即失效缓存。"""
        ...

    def profile_name(self) -> str:
        """当前 profile 名（如 分辨率@DPI）。"""
        ...


@runtime_checkable
class Perception(Protocol):
    """感知层：消息内容的唯一来源是采集通道。"""

    def activate(self) -> None:
        """激活目标窗口并校验前台。"""
        ...

    def switch_session(self, session: str) -> None:
        """切换会话并校验；失败抛 SessionSwitchFailed。"""
        ...

    def capture(self, session: str) -> str:
        """采集当前会话原始文本（剪贴板/接口）；失败抛 CopyFailed。"""
        ...


@runtime_checkable
class Executor(Protocol):
    """执行层：发送与三重校验。"""

    def send(self, session: str, text: str, *, trigger: str = "auto") -> SendOutcome:
        """trigger: auto | override | plugin | retry（写入审计）。"""
        ...

    def clear_input(self) -> str:
        """清空输入框并返回清空前内容。"""
        ...

    def is_dry_run(self) -> bool:
        """当前是否干跑（不真实发送）。"""
        ...


@runtime_checkable
class Brain(Protocol):
    """推理层。"""

    def generate(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        session: str | None = None,
    ) -> LLMResult:
        """输入 OpenAI 兼容 messages，输出结果；失败抛 LLMError。"""
        ...

    def ping(self) -> float:
        """连通性探测，返回延迟毫秒；失败抛 LLMError。"""
        ...


@runtime_checkable
class MemoryStore(Protocol):
    """记忆层门面（流水库 + 档案库）。"""

    def recent_hashes(self, session: str, limit: int) -> Sequence[str]:
        """最近 N 条消息哈希（旧 -> 新）。"""
        ...

    def insert_messages(self, session: str, messages: Sequence[IncomingMessage]) -> int:
        """批量入库，返回新增条数。"""
        ...

    def writeback(self, session: str, text: str) -> int:
        """发送成功后状态回写，返回消息 id。"""
        ...

    def history(self, session: str, limit: int) -> Sequence[Message]:
        """最近 N 条流水（旧 -> 新）。"""
        ...

    def recall(self, session: str | None, query: str, top_k: int) -> Sequence[MemoryItem]:
        """档案库召回；session=None 表示跨会话全局。"""
        ...

    def add_memory(self, item: MemoryItem) -> int:
        """幂等 upsert 一条档案，返回 id。"""
        ...

    def forget(self, memory_id: int) -> bool:
        """软删一条档案，返回是否命中。"""
        ...


@dataclass(frozen=True)
class Ports:
    """适配器创建出的五端口集合。"""

    element_tree: ElementTree
    perception: Perception
    executor: Executor
    brain: Brain
    memory: MemoryStore

    def as_mapping(self) -> Mapping[str, Any]:
        return {
            "element_tree": self.element_tree,
            "perception": self.perception,
            "executor": self.executor,
            "brain": self.brain,
            "memory": self.memory,
        }
