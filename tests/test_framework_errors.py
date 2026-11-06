"""M0-F-02 框架异常测试（dsh_rpa.errors）。

覆盖：框架基类、退出码映射、SessionSwitchFailed 语义、to_dict 脱敏、
平台无关性（框架包不得出现平台名 / 不得 import 应用层）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dsh_rpa import INTERFACE_VERSION, __version__
from dsh_rpa.errors import (
    ERROR_CLASSES,
    EXIT_CODE_MAP,
    AgentFrameworkError,
    ConfigError,
    CopyFailed,
    DBError,
    ElementNotVisible,
    ExitCode,
    InternalError,
    Interrupted,
    LLMError,
    ProfileMismatch,
    RedlineViolation,
    SessionSwitchFailed,
    TreeConfigError,
    UsageError,
    VerifyFailed,
    WindowNotForeground,
    WindowNotFound,
    exit_code_for,
    format_exception_chain,
)

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "dsh_rpa"

EXPECTED_EXIT_CODES: dict[type[AgentFrameworkError], int] = {
    UsageError: 2,
    ConfigError: 2,
    ElementNotVisible: 3,
    TreeConfigError: 3,
    WindowNotFound: 3,
    WindowNotForeground: 3,
    SessionSwitchFailed: 3,
    CopyFailed: 3,
    VerifyFailed: 4,
    LLMError: 5,
    DBError: 6,
    ProfileMismatch: 7,
    RedlineViolation: 8,
    InternalError: 1,
    Interrupted: 130,
}


def test_framework_metadata() -> None:
    assert __version__ == "0.1.0"
    assert INTERFACE_VERSION == "1.0"


def test_framework_error_hierarchy() -> None:
    for cls in EXPECTED_EXIT_CODES:
        assert issubclass(cls, AgentFrameworkError)
    assert set(ERROR_CLASSES) == set(EXPECTED_EXIT_CODES)
    assert AgentFrameworkError not in ERROR_CLASSES


def test_exit_code_map_and_uniqueness() -> None:
    for cls, expected in EXPECTED_EXIT_CODES.items():
        assert cls.exit_code == expected
        assert isinstance(cls.code, str) and cls.code
    assert EXIT_CODE_MAP == EXPECTED_EXIT_CODES
    codes = [cls.code for cls in ERROR_CLASSES]
    assert len(codes) == len(set(codes))


def test_session_switch_failed_semantics() -> None:
    exc = SessionSwitchFailed("会话校验失败", context={"chat": "张三"})
    assert exc.code == "SESSION_SWITCH_FAILED"
    assert exc.exit_code == ExitCode.ELEMENT_NOT_VISIBLE
    assert "会话" in str(exc)


def test_repr_and_to_dict_masked() -> None:
    exc = LLMError(
        "失败 13812345678",
        context={"api_key": "sk-abcdef123456", "phone": "13812345678"},
    )
    assert "LLMError" in repr(exc)
    payload = exc.to_dict()
    text = json.dumps(payload, ensure_ascii=False)
    assert payload["code"] == "LLM_ERROR"
    assert payload["is_control_flow"] is False
    assert "13812345678" not in text
    assert "sk-abcdef123456" not in text
    assert "event" not in payload  # to_dict 不含 event；to_audit 才注入


def test_interrupted_flag_and_exit_code() -> None:
    exc = Interrupted("急停")
    assert exc.is_control_flow is True
    assert exc.exit_code == ExitCode.INTERRUPTED
    assert exc.to_audit()["event"] == "error"


def test_exit_code_for_and_chain_format() -> None:
    assert exit_code_for(SessionSwitchFailed("x")) == 3
    assert exit_code_for(ValueError("x")) == 1
    try:
        raise RuntimeError("inner")
    except RuntimeError as exc:
        text = format_exception_chain(exc)
    assert "RuntimeError" in text


def test_framework_error_accepts_custom_hint() -> None:
    exc = CopyFailed("x", hint="自定义")
    assert exc.hint == "自定义"
    assert CopyFailed("x").hint is not None


@pytest.mark.parametrize("path", sorted(PACKAGE_DIR.rglob("*.py")), ids=lambda p: p.name)
def test_framework_package_is_platform_neutral(path: Path) -> None:
    """红线：框架包不得出现平台名（含中文），也不得 import 应用层。"""
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    for forbidden in ("wechat", "dingtalk", "微信", "钉钉"):
        assert forbidden not in lowered, f"{path.name} 出现平台名 {forbidden!r}"
    assert "from wechat_agent" not in text
    assert "import wechat_agent" not in text
