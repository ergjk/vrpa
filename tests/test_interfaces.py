"""M0-05 接口契约与红线 R1/R3 静态扫描测试。

覆盖：
    1. V1.0 五个核心 Protocol 存在且可 runtime_checkable 检查；
    2. Fake 后端满足协议；缺失方法必须被 isinstance 拒绝；
    3. 所有协议方法体必须是 `...`（空实现），DTO 为 frozen dataclass；
    4. V1.1/V1.2 五个保留接口存在且为空；
    5. 红线 R1：保留接口名只允许出现在 core/interfaces.py；
    6. 红线 R3：interfaces.py 不 import 任何视觉/自动化/LLM 第三方库，也不 import 其它业务模块。

运行：python -m pytest tests/test_interfaces.py -q
"""

from __future__ import annotations

import ast
import inspect
import re
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from wechat_agent.core import interfaces as iface
from wechat_agent.core.interfaces import (
    CORE_PROTOCOLS,
    FUTURE_FEATURES,
    FUTURE_INTERFACES,
    FUTURE_POLICY,
    INTERFACE_VERSION,
    Brain,
    ChatMessage,
    Executor,
    IncomingMessage,
    LLMResult,
    MemoryHub,
    MemoryItem,
    Perception,
    Rect,
    SendOutcome,
    UiaTree,
)

PACKAGE_DIR = Path(iface.__file__).resolve().parent.parent
INTERFACES_FILE = PACKAGE_DIR / "core" / "interfaces.py"

EXPECTED_METHODS: dict[str, set[str]] = {
    "UiaTree": {"element_ids", "locate", "validate", "invalidate", "profile_name"},
    "Perception": {"activate", "ensure_chat", "capture"},
    "Executor": {"send", "clear_input", "is_dry_run"},
    "Brain": {"generate", "ping"},
    "MemoryHub": {
        "recent_hashes",
        "insert_messages",
        "writeback",
        "history",
        "recall",
        "add_memory",
        "forget",
    },
}


# ---------------------------------------------------------------- Fake 后端
class FakeUiaTree:
    def element_ids(self) -> tuple[str, ...]:
        return ("main_window", "message_area", "input_box")

    def locate(self, element_id: str) -> Rect:
        return Rect(10, 20, 100, 40)

    def validate(self) -> bool:
        return True

    def invalidate(self) -> None:
        return None

    def profile_name(self) -> str:
        return "1920x1080@1.0"


class FakePerception:
    def activate(self) -> None:
        return None

    def ensure_chat(self, chat: str) -> None:
        return None

    def capture(self, chat: str) -> str:
        return "张三: 你好"


class FakeExecutor:
    def send(self, chat: str, text: str, *, trigger: str = "auto") -> SendOutcome:
        return SendOutcome(ok=True, stage="dry_run", detail=text)

    def clear_input(self) -> str:
        return ""

    def is_dry_run(self) -> bool:
        return True


class FakeBrain:
    def generate(self, messages, *, chat: str | None = None) -> LLMResult:
        return LLMResult(text="ok", usage={"total_tokens": 1})

    def ping(self) -> float:
        return 1.0


class FakeMemoryHub:
    def recent_hashes(self, chat: str, limit: int) -> list[str]:
        return []

    def insert_messages(self, chat: str, messages) -> int:
        return len(messages)

    def writeback(self, chat: str, text: str) -> int:
        return 1

    def history(self, chat: str, limit: int) -> list[ChatMessage]:
        return []

    def recall(self, chat: str | None, query: str, top_k: int) -> list[MemoryItem]:
        return []

    def add_memory(self, item: MemoryItem) -> int:
        return 1

    def forget(self, memory_id: int) -> bool:
        return True


class PartialPerception:
    """只实现了一个方法，不应满足 Perception。"""

    def capture(self, chat: str) -> str:
        return ""


# ---------------------------------------------------------------- 协议测试
def test_interface_version() -> None:
    assert INTERFACE_VERSION == 1
    assert "DO NOT IMPLEMENT" in FUTURE_POLICY


def test_core_protocols_registered_and_are_protocols() -> None:
    assert set(CORE_PROTOCOLS) == set(EXPECTED_METHODS)
    for name, proto in CORE_PROTOCOLS.items():
        assert getattr(proto, "_is_protocol", False), name
        assert getattr(proto, "_is_runtime_protocol", False), name


def test_protocol_method_names() -> None:
    for name, expected in EXPECTED_METHODS.items():
        proto = CORE_PROTOCOLS[name]
        methods = {n for n, v in vars(proto).items() if inspect.isfunction(v) and not n.startswith("__")}
        assert methods == expected, f"{name} 方法集不符：{methods} != {expected}"


@pytest.mark.parametrize(
    ("fake", "proto"),
    [
        (FakeUiaTree(), UiaTree),
        (FakePerception(), Perception),
        (FakeExecutor(), Executor),
        (FakeBrain(), Brain),
        (FakeMemoryHub(), MemoryHub),
    ],
)
def test_fake_satisfies_protocol(fake: object, proto: type) -> None:
    assert isinstance(fake, proto)


def test_partial_implementation_rejected() -> None:
    assert not isinstance(PartialPerception(), Perception)


def test_all_protocol_bodies_are_empty_in_source() -> None:
    """红线 R1：协议类体只允许「docstring + 方法签名」，方法体只允许 `...`。

    说明：CPython 会优化掉裸 `...` 语句，因此用 AST 读源码判空比查 co_consts 可靠。
    """
    protocols = {**CORE_PROTOCOLS, **FUTURE_INTERFACES}
    source = INTERFACES_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    seen: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name not in protocols:
            continue
        seen.add(node.name)
        for statement in node.body:
            if (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and (statement.value.value is Ellipsis or isinstance(statement.value.value, str))
            ):
                continue
            assert isinstance(statement, ast.FunctionDef), (
                f"{node.name} 类体出现非协议声明：{ast.dump(statement)[:80]}（红线 R1）"
            )
            for inner in statement.body:
                if not (
                    isinstance(inner, ast.Expr)
                    and isinstance(inner.value, ast.Constant)
                    and (inner.value.value is Ellipsis or isinstance(inner.value.value, str))
                ):
                    raise AssertionError(f"{node.name}.{statement.name} 含实现体（红线 R1：仅允许 `...`）")
    assert seen == set(protocols), f"未在源码中找到协议类：{set(protocols) - seen}"


# ---------------------------------------------------------------- DTO 测试
def test_rect_basics_and_validation() -> None:
    rect = Rect(100, 200, 80, 40)
    assert rect.center == (140, 220)
    assert rect.right == 180 and rect.bottom == 240
    assert rect.as_tuple() == (100, 200, 80, 40)
    assert rect.contains(100, 200) and not rect.contains(180, 240)
    with pytest.raises(ValueError):
        Rect(0, 0, 0, 10)
    with pytest.raises(TypeError):
        Rect(0, 0, 10, 10.5)  # type: ignore[arg-type]


def test_dtos_are_frozen() -> None:
    rect = Rect(0, 0, 10, 10)
    with pytest.raises(FrozenInstanceError):
        rect.x = 1  # type: ignore[misc]


def test_dto_defaults() -> None:
    message = ChatMessage(direction="in", content="你好")
    assert message.role == "user"
    assert message.source == "rpa_capture"
    assert message.status == "ok"
    assert IncomingMessage(content="hi").confidence == 1.0
    assert SendOutcome(ok=True, stage="sent").trace_id == "-"
    assert dict(LLMResult(text="hi").usage) == {}
    item = MemoryItem(content="喜欢猫")
    assert item.category == "event" and item.memory_id is None


def test_send_outcome_stages_documented() -> None:
    for stage in ("sent", "dry_run", "verify_failed", "element_missing", "skipped"):
        assert SendOutcome(ok=False, stage=stage).stage == stage


# ---------------------------------------------------------------- 红线测试
def _package_py_files() -> list[Path]:
    return [p for p in PACKAGE_DIR.rglob("*.py") if "__pycache__" not in p.parts]


def test_r1_future_interfaces_only_in_interfaces_module() -> None:
    """红线 R1：V1.1/V1.2 接口名不得出现在其它业务模块（禁止超前实现/接线）。"""
    pattern = re.compile(r"\b(" + "|".join(FUTURE_INTERFACES) + r")\b")
    offenders: dict[str, list[str]] = {}
    for path in _package_py_files():
        if path == INTERFACES_FILE:
            continue
        text = path.read_text(encoding="utf-8")
        hits = sorted({match.group(1) for match in pattern.finditer(text)})
        if hits:
            offenders[str(path.relative_to(PACKAGE_DIR))] = hits
    assert offenders == {}, f"红线 R1 违规：{offenders}"


def test_future_interface_catalog_complete() -> None:
    assert set(FUTURE_INTERFACES) == set(FUTURE_FEATURES)
    for name, proto in FUTURE_INTERFACES.items():
        assert getattr(proto, "_is_protocol", False), name
        methods = [n for n, v in vars(proto).items() if inspect.isfunction(v)]
        assert methods, f"保留接口 {name} 必须至少声明一个方法签名"
        assert FUTURE_FEATURES[name].startswith(("V1.1", "V1.2")), FUTURE_FEATURES[name]


def test_r3_interfaces_module_is_pure() -> None:
    """红线 R3/R1：interfaces.py 不得 import 视觉/自动化/LLM 依赖或其它业务模块。"""
    text = INTERFACES_FILE.read_text(encoding="utf-8")
    forbidden_modules = ("cv2", "numpy", "pyautogui", "pywinauto", "pyperclip", "openai", "pynput")
    for module in forbidden_modules:
        assert re.search(rf"(?m)^\s*(import|from)\s+{module}\b", text) is None, module
    assert re.search(r"(?m)^\s*(import|from)\s+wechat_agent\b", text) is None, (
        "interfaces.py 不允许 import 其它 wechat_agent 模块（零依赖纪律）"
    )
