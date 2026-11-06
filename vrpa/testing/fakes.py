"""平台无关的 Fake 实现：供合规测试、契约自检与 M4 全链路注入。

设计目标：
    - 让「无目标客户端环境」也能跑通端口契约与编排流程；
    - 每个 Fake 都可通过构造参数注入失败场景（定位失败 / 会话切换失败 / 发送校验失败 / LLM 失败）；
    - 不依赖任何第三方库，不使用真实键鼠/网络。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from vrpa.config.plugin import PlatformMeta
from vrpa.errors import CopyFailed, ElementNotVisible, LLMError, SessionSwitchFailed, VerifyFailed
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

__all__ = [
    "FakeBrain",
    "FakeConfigPlugin",
    "FakeElementTree",
    "FakeExecutor",
    "FakeMemoryStore",
    "FakePerception",
    "FakePlatformAdapter",
    "FakePlatformOptions",
    "make_fake_ports",
]


class FakeElementTree:
    """内存元素树：默认返回固定矩形；``fail_locate=True`` 时模拟定位失败。"""

    def __init__(self, *, fail_locate: bool = False, rect: Rect | None = None) -> None:
        self.fail_locate = fail_locate
        self._rect = rect or Rect(10, 20, 100, 40)
        self.invalidated = 0

    def element_ids(self) -> tuple[str, ...]:
        return ("main_window", "message_area", "input_box")

    def locate(self, element_id: str) -> Rect:
        if self.fail_locate:
            raise ElementNotVisible(f"fake: 元素不可见 {element_id}")
        return self._rect

    def validate(self) -> bool:
        return True

    def invalidate(self) -> None:
        self.invalidated += 1

    def profile_name(self) -> str:
        return "fake@1.0"


class FakePerception:
    """脚本化采集：按顺序返回预置文本；用完复用最后一条。"""

    def __init__(self, scripted: Sequence[str] = (), *, fail_switch: bool = False) -> None:
        self.scripted = tuple(scripted)
        self.fail_switch = fail_switch
        self.activated = 0
        self.captures: list[str] = []
        self._index = 0

    def activate(self) -> None:
        self.activated += 1

    def switch_session(self, session: str) -> None:
        if self.fail_switch:
            raise SessionSwitchFailed(f"fake: 无法切换会话 {session}")

    def capture(self, session: str) -> str:
        if not self.scripted:
            raise CopyFailed("fake: 没有脚本化采集输出")
        index = min(self._index, len(self.scripted) - 1)
        text = self.scripted[index]
        self._index += 1
        self.captures.append(text)
        return text


class FakeExecutor:
    """记录发送内容；``fail_send=True`` 模拟发送前三重校验失败。"""

    def __init__(self, *, dry_run: bool = True, fail_send: bool = False) -> None:
        self.dry_run = dry_run
        self.fail_send = fail_send
        self.sent: list[tuple[str, str, str]] = []

    def send(self, session: str, text: str, *, trigger: str = "auto") -> SendOutcome:
        if self.fail_send:
            raise VerifyFailed("fake: 发送前三重校验失败")
        self.sent.append((session, text, trigger))
        stage = "dry_run" if self.dry_run else "sent"
        return SendOutcome(ok=True, stage=stage, detail=text)

    def clear_input(self) -> str:
        return ""

    def is_dry_run(self) -> bool:
        return self.dry_run


class FakeBrain:
    """固定回复；``fail=True`` 模拟上游失败。"""

    def __init__(self, reply: str = "fake reply", *, fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail

    def generate(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        session: str | None = None,
    ) -> LLMResult:
        if self.fail:
            raise LLMError("fake: LLM 调用失败")
        return LLMResult(
            text=self.reply,
            model="fake-model",
            usage={"total_tokens": len(self.reply)},
            latency_ms=1.0,
        )

    def ping(self) -> float:
        return 1.0


class FakeMemoryStore:
    """纯内存双库替身：流水 + 档案。"""

    def __init__(self) -> None:
        self.messages: list[Message] = []
        self.memories: list[MemoryItem] = []
        self._next_message_id = 1
        self._next_memory_id = 1

    def recent_hashes(self, session: str, limit: int) -> Sequence[str]:
        return tuple(f"hash-{index}" for index, _ in enumerate(self.messages[-limit:]))

    def insert_messages(self, session: str, messages: Sequence[IncomingMessage]) -> int:
        for item in messages:
            self.messages.append(Message(direction="in", content=item.content, sender=item.sender, ts=item.ts))
        return len(messages)

    def writeback(self, session: str, text: str) -> int:
        self.messages.append(Message(direction="out", role="assistant", content=text, source="writeback"))
        message_id = self._next_message_id
        self._next_message_id += 1
        return message_id

    def history(self, session: str, limit: int) -> Sequence[Message]:
        return tuple(self.messages[-limit:])

    def recall(self, session: str | None, query: str, top_k: int) -> Sequence[MemoryItem]:
        return tuple(self.memories[:top_k])

    def add_memory(self, item: MemoryItem) -> int:
        memory_id = self._next_memory_id
        self._next_memory_id += 1
        self.memories.append(
            MemoryItem(
                content=item.content,
                category=item.category,
                chat=item.chat,
                key=item.key,
                confidence=item.confidence,
                importance=item.importance,
                memory_id=memory_id,
            )
        )
        return memory_id

    def forget(self, memory_id: int) -> bool:
        remaining = [item for item in self.memories if item.memory_id != memory_id]
        hit = len(remaining) != len(self.memories)
        self.memories = remaining
        return hit


@dataclass(frozen=True)
class FakePlatformOptions:
    """Fake 平台的配置对象（任意结构，框架不解释）。"""

    enabled: bool = True


class FakeConfigPlugin:
    """Fake 平台配置插件（满足 ``PlatformPlugin`` 结构）。"""

    kind = "fake"
    legacy_sections: tuple[str, ...] = ()

    def meta(self) -> PlatformMeta:
        return PlatformMeta(kind=self.kind, display_name="Fake Platform", plugin_version="1.0")

    def default_options(self) -> Mapping[str, Any]:
        return {"enabled": True}

    def validate_options(self, options: Mapping[str, Any]) -> FakePlatformOptions:
        return FakePlatformOptions(enabled=bool(options.get("enabled", True)))

    def describe(self) -> str:
        return "fake platform config plugin"


def make_fake_ports(
    *,
    element_tree: ElementTree | None = None,
    perception: Perception | None = None,
    executor: Executor | None = None,
    brain: Brain | None = None,
    memory: MemoryStore | None = None,
) -> Ports:
    """构造一套可用的 Fake 端口（可按需替换单端口）。"""
    return Ports(
        element_tree=element_tree or FakeElementTree(),
        perception=perception or FakePerception(scripted=("visitor: hello",)),
        executor=executor or FakeExecutor(),
        brain=brain or FakeBrain(),
        memory=memory or FakeMemoryStore(),
    )


class FakePlatformAdapter:
    """Fake 平台适配器：满足 ``PlatformAdapter`` 结构，用于契约套件自检与示例。"""

    kind = "fake"
    display_name = "Fake RPA Platform"
    adapter_version = "1.0"

    def __init__(self, *, fail_ports: bool = False) -> None:
        self.fail_ports = fail_ports
        self._plugin = FakeConfigPlugin()

    def capabilities(self) -> frozenset[str]:
        return frozenset({"text_only"})

    def config_plugin(self) -> FakeConfigPlugin:
        return self._plugin

    def element_tree_profile_spec(self) -> Mapping[str, Any]:
        return {
            "schema": 1,
            "root": "main_window",
            "elements": ["main_window", "message_area", "input_box"],
        }

    def parser_pack(self) -> Mapping[str, Any]:
        return {"strategies": ["timestamp", "colon", "block"], "min_samples": 15}

    def create_ports(self, options: Any = None) -> Ports:
        if self.fail_ports:
            raise RuntimeError("fake: create_ports 失败")
        return make_fake_ports()

    def describe(self) -> str:
        return "fake platform adapter（文本采集 + 发送 + 推理 + 记忆）"
