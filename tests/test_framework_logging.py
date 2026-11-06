"""M0-F-02 框架日志测试（vrpa.logging）。

覆盖：命名空间注入/恢复与校验、日志格式、trace_id、审计 JSONL、环境变量回退、
脱敏、self_check。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from vrpa.logging import (
    AUDIT_FILE_NAME,
    LOG_FILE_NAME,
    audit,
    audit_path,
    bind_trace,
    configure_logging_namespace,
    current_trace_id,
    get_logger,
    get_namespace_config,
    logger_namespace,
    new_trace_id,
    redact,
    self_check,
    setup_logging,
    shutdown_logging,
    trace_scope,
)


@pytest.fixture()
def framework_ns():
    """切到框架测试命名空间，结束后恢复（避免污染应用层测试）。"""
    original = get_namespace_config()
    configure_logging_namespace("vrpa_test", data_dir_env=("VRPA_TEST_DATA",))
    shutdown_logging()
    try:
        yield
    finally:
        shutdown_logging()
        configure_logging_namespace(original.name, data_dir_env=original.data_dir_envs)


def test_namespace_configure_and_restore(framework_ns) -> None:
    assert logger_namespace() == "vrpa_test"
    assert get_logger("core.test").name == "vrpa_test.core.test"
    assert get_logger().name == "vrpa_test"


def test_namespace_validation(framework_ns) -> None:
    with pytest.raises(ValueError):
        configure_logging_namespace("   ")
    with pytest.raises(ValueError):
        configure_logging_namespace("x", data_dir_env=())
    assert logger_namespace() == "vrpa_test"


def test_setup_logging_format_with_namespace(tmp_path: Path, framework_ns) -> None:
    logger = setup_logging(tmp_path, console=False)
    with trace_scope("deadbeef"):
        logger.info("hello %s", "world")
    for handler in logger.handlers:
        handler.flush()
    line = (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8").strip().splitlines()[-1]
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} INFO\s+\[deadbeef\] \[vrpa_test\] hello world$", line)


def test_trace_scope_and_redact(framework_ns) -> None:
    assert current_trace_id() == "-"
    with trace_scope("cafebabe") as tid:
        assert tid == "cafebabe"
        assert current_trace_id() == "cafebabe"
        with trace_scope():
            assert re.fullmatch(r"[0-9a-f]{8}", new_trace_id())
        assert current_trace_id() == "cafebabe"
    assert current_trace_id() == "-"
    with pytest.raises(ValueError):
        bind_trace("NOTHEX")
    masked = redact("手机 13812345678 身份证 110101199001011234 key sk-abcdef123456")
    assert "13812345678" not in masked
    assert "110101199001011234" not in masked
    assert "sk-abcdef123456" not in masked


def test_audit_uses_namespace_env_fallback(tmp_path: Path, framework_ns, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VRPA_TEST_DATA", str(tmp_path))
    shutdown_logging()  # 重置审计单例，强制走环境变量解析路径
    with trace_scope("12345678"):
        record = audit({"event": "demo"})
    expected = tmp_path / "logs" / AUDIT_FILE_NAME
    assert record["trace_id"] == "12345678"
    assert audit_path() == expected
    payload = json.loads(expected.read_text(encoding="utf-8").strip())
    assert payload["event"] == "demo"
    assert payload["ts"]


def test_audit_fallback_without_env(tmp_path: Path, framework_ns, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VRPA_TEST_DATA", raising=False)
    monkeypatch.chdir(tmp_path)
    shutdown_logging()
    audit({"event": "fallback"})
    assert (tmp_path / "data" / "logs" / AUDIT_FILE_NAME).is_file()


def test_self_check_green(tmp_path: Path, framework_ns) -> None:
    report = self_check(tmp_path)
    assert report["ok"] is True, report
    names = {item["name"] for item in report["checks"]}
    assert {"log_file", "log_format", "log_trace_id", "audit_file", "audit_jsonl", "redact"} <= names


def test_shutdown_clears_handlers(tmp_path: Path, framework_ns) -> None:
    setup_logging(tmp_path, console=False)
    assert get_logger().handlers
    shutdown_logging()
    assert not get_logger().handlers
