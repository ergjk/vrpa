"""M0-04 统一异常体系单元测试。

覆盖：类层次、退出码映射与 docs §1.2 一致、code 唯一性、hint/context/cause、
to_dict 的 JSON 可序列化与脱敏、InternalError 包装、Interrupted 控制流标记、
config.ConfigError 与 errors.ConfigError 同一类、CLI 全局捕获的退出码（3/130/1）。

运行：python -m pytest tests/test_errors.py -q
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from wechat_agent import main as main_module
from wechat_agent.core.config import ConfigError as ConfigErrorFromConfig
from wechat_agent.core.errors import (
    ERROR_CLASSES,
    EXIT_CODE_MAP,
    ChatSwitchFailed,
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
    TreeConfigError,
    UsageError,
    VerifyFailed,
    WeChatAgentError,
    WindowNotForeground,
    WindowNotFound,
    exit_code_for,
    format_exception_chain,
)

EXPECTED_EXIT_CODES: dict[type[WeChatAgentError], int] = {
    UsageError: 2,
    ConfigError: 2,
    ElementNotVisible: 3,
    TreeConfigError: 3,
    WindowNotFound: 3,
    WindowNotForeground: 3,
    ChatSwitchFailed: 3,
    CopyFailed: 3,
    VerifyFailed: 4,
    LLMError: 5,
    DBError: 6,
    ProfileMismatch: 7,
    RedlineViolation: 8,
    InternalError: 1,
    Interrupted: 130,
}


def test_all_required_classes_are_subclasses() -> None:
    for cls in EXPECTED_EXIT_CODES:
        assert issubclass(cls, WeChatAgentError)
    assert set(ERROR_CLASSES) == set(EXPECTED_EXIT_CODES)
    assert WeChatAgentError not in ERROR_CLASSES


def test_exit_code_mapping_matches_contract() -> None:
    for cls, expected in EXPECTED_EXIT_CODES.items():
        assert cls.exit_code == expected
    assert EXIT_CODE_MAP == EXPECTED_EXIT_CODES


def test_exit_codes_within_documented_set() -> None:
    documented = {1, 2, 3, 4, 5, 6, 7, 8, 130}
    assert {cls.exit_code for cls in ERROR_CLASSES} <= documented
    # docs §1.2 的业务码必须全部有异常承接
    assert {2, 3, 4, 5, 6, 7, 8, 130} <= {cls.exit_code for cls in ERROR_CLASSES}


def test_error_codes_unique() -> None:
    codes = [cls.code for cls in ERROR_CLASSES]
    assert len(codes) == len(set(codes))


def test_message_hint_and_str() -> None:
    exc = ElementNotVisible("input_box 未找到", context={"score": 0.42})
    assert str(exc) == "input_box 未找到"
    assert exc.hint and "calibrate" in exc.hint
    assert exc.exit_code == ExitCode.ELEMENT_NOT_VISIBLE
    custom = CopyFailed("未选中", hint="自定义提示")
    assert custom.hint == "自定义提示"


def test_to_dict_json_serializable_and_masked() -> None:
    exc = LLMError(
        "调用失败 13812345678",
        context={"api_key": "sk-abcdef123456", "phone": "13812345678", "nested": [{"id": "110101199001011234"}]},
    )
    data = exc.to_dict()
    assert data["type"] == "LLMError"
    assert data["code"] == "LLM_ERROR"
    assert data["exit_code"] == 5
    assert data["is_control_flow"] is False
    text = json.dumps(data, ensure_ascii=False)
    assert "13812345678" not in text
    assert "sk-abcdef123456" not in text
    assert "110101199001011234" not in text


def test_to_audit_shape() -> None:
    payload = DBError("迁移失败", context={"db": "chat_history.db"}).to_audit()
    assert payload["event"] == "error"
    assert payload["code"] == "DB_ERROR"
    assert payload["exit_code"] == 6


def test_internal_error_from_exception() -> None:
    original = ValueError("boom")
    wrapped = InternalError.from_exception(original, context={"where": "test"})
    assert wrapped.exit_code == 1
    assert wrapped.cause is original
    data = wrapped.to_dict()
    assert data["context"]["original_type"] == "ValueError"
    assert data["context"]["where"] == "test"
    assert "boom" in data["message"]
    assert data["cause"] == {"type": "ValueError", "message": "boom"}


def test_interrupted_is_control_flow() -> None:
    exc = Interrupted("急停")
    assert exc.is_control_flow is True
    assert exc.exit_code == ExitCode.INTERRUPTED
    assert exc.to_dict()["exit_code"] == 130


def test_config_error_is_shared_with_config_module() -> None:
    assert ConfigErrorFromConfig is ConfigError


def test_exit_code_for() -> None:
    assert exit_code_for(ElementNotVisible("x")) == 3
    assert exit_code_for(Interrupted("x")) == 130
    assert exit_code_for(ValueError("x")) == 1


def test_trace_id_attached() -> None:
    from wechat_agent.core.logging import trace_scope

    with trace_scope("abcdef12"):
        assert ElementNotVisible("x").trace_id == "abcdef12"


def test_format_exception_chain() -> None:
    try:
        raise RuntimeError("inner")
    except RuntimeError as exc:
        text = format_exception_chain(exc)
    assert "RuntimeError" in text and "inner" in text


def _install_failing_handler(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    command = main_module.COMMANDS["selftest"]

    def boom(_argv: object) -> int:
        raise exc

    monkeypatch.setitem(main_module.COMMANDS, "selftest", replace(command, handler=boom))


def test_main_returns_error_exit_code(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _install_failing_handler(monkeypatch, ElementNotVisible("input_box", context={"score": 0.4}))
    code = main_module.main(["selftest"])
    captured = capsys.readouterr()
    assert code == 3
    assert "ELEMENT_NOT_VISIBLE" in captured.err
    assert "提示：" in captured.err


def test_main_returns_interrupted(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _install_failing_handler(monkeypatch, Interrupted("接管"))
    code = main_module.main(["selftest"])
    assert code == 130
    assert "已中断" in capsys.readouterr().err


def test_main_catches_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_argv: object) -> int:
        raise KeyboardInterrupt

    monkeypatch.setitem(main_module.COMMANDS, "selftest", replace(main_module.COMMANDS["selftest"], handler=boom))
    assert main_module.main(["selftest"]) == 130


def test_main_wraps_unexpected_exception(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _install_failing_handler(monkeypatch, RuntimeError("内部炸了"))
    code = main_module.main(["selftest"])
    captured = capsys.readouterr()
    assert code == 1
    assert "INTERNAL_ERROR" in captured.err
