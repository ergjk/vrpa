"""M0-03 日志与审计单元测试。

覆盖：trace_id 生成/绑定/嵌套恢复、日志行格式、RotatingFileHandler 参数、配置幂等与 force、
控制台 handler 开关、非法级别、审计 JSONL 追加与可解析、脱敏（手机号/身份证/API Key/邮箱/
键值对/递归）、self_check 全绿、shutdown 清理。

运行：python -m pytest tests/test_logging.py -q
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
from pathlib import Path

import pytest

from wechat_agent.core.logging import (
    AUDIT_FILE_NAME,
    LOG_BACKUP_COUNT,
    LOG_FILE_NAME,
    LOG_MAX_BYTES,
    audit,
    audit_path,
    bind_trace,
    current_trace_id,
    get_logger,
    new_trace_id,
    redact,
    redact_mapping,
    self_check,
    setup_logging,
    shutdown_logging,
    trace_scope,
)

pytestmark = pytest.mark.usefixtures("_isolate_logging")


@pytest.fixture(autouse=True)
def _isolate_logging():
    shutdown_logging()
    yield
    shutdown_logging()


def _log_text(tmp_path: Path) -> str:
    path = tmp_path / LOG_FILE_NAME
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _flush(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        handler.flush()


def test_new_trace_id_format() -> None:
    first, second = new_trace_id(), new_trace_id()
    assert re.fullmatch(r"[0-9a-f]{8}", first)
    assert first != second


def test_trace_scope_sets_and_restores() -> None:
    assert current_trace_id() == "-"
    with trace_scope("deadbeef") as tid:
        assert tid == "deadbeef"
        assert current_trace_id() == "deadbeef"
    assert current_trace_id() == "-"


def test_nested_trace_scope_restores_outer() -> None:
    with trace_scope("aaaaaaaa"):
        with trace_scope("bbbbbbbb"):
            assert current_trace_id() == "bbbbbbbb"
        assert current_trace_id() == "aaaaaaaa"


def test_bind_trace_validates() -> None:
    with pytest.raises(ValueError):
        bind_trace("XYZ")


def test_setup_logging_writes_formatted_line(tmp_path: Path) -> None:
    logger = setup_logging(tmp_path, console=False)
    assert logger.name == "wechat_agent"
    assert logger.propagate is False
    with trace_scope("cafebabe"):
        logger.info("hello %s", "world")
    _flush(logger)
    line = _log_text(tmp_path).strip().splitlines()[-1]
    assert re.match(
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} INFO\s+\[cafebabe\] \[wechat_agent\] hello world$",
        line,
    ), line


def test_rotating_handler_parameters(tmp_path: Path) -> None:
    logger = setup_logging(tmp_path, console=False)
    handlers = [h for h in logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert len(handlers) == 1
    assert handlers[0].maxBytes == LOG_MAX_BYTES == 10 * 1024 * 1024
    assert handlers[0].backupCount == LOG_BACKUP_COUNT == 5
    assert str(handlers[0].baseFilename).endswith(str(tmp_path / LOG_FILE_NAME))


def test_setup_logging_idempotent_and_force(tmp_path: Path) -> None:
    setup_logging(tmp_path, console=False)
    setup_logging(tmp_path, console=False)
    file_handlers = [h for h in get_logger().handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert len(file_handlers) == 1
    setup_logging(tmp_path, console=False, force=True)
    file_handlers = [h for h in get_logger().handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert len(file_handlers) == 1


def test_console_handler_optional(tmp_path: Path) -> None:
    setup_logging(tmp_path, console=False)
    assert len(get_logger().handlers) == 1
    setup_logging(tmp_path, console=True, force=True)
    assert len(get_logger().handlers) == 2


def test_invalid_level_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        setup_logging(tmp_path, level="verbose")


def test_audit_appends_jsonl(tmp_path: Path) -> None:
    setup_logging(tmp_path, console=False)
    with trace_scope("12345678"):
        first = audit({"event": "send", "content": "你好"})
        audit({"event": "recv", "content": "在吗"})
    assert first["event"] == "send"
    lines = (tmp_path / AUDIT_FILE_NAME).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        item = json.loads(line)
        assert item["trace_id"] == "12345678"
        assert item["ts"]
    assert audit_path() == tmp_path / AUDIT_FILE_NAME


def test_audit_redacts_sensitive(tmp_path: Path) -> None:
    setup_logging(tmp_path, console=False)
    audit(
        {
            "event": "send",
            "content": "手机 13812345678 身份证 110101199001011234",
            "meta": {
                "api_key": "sk-abcdef123456",
                "headers": {"authorization": "Bearer sk-zzzzzzzz9999"},
            },
        }
    )
    text = (tmp_path / AUDIT_FILE_NAME).read_text(encoding="utf-8")
    assert "13812345678" not in text
    assert "110101199001011234" not in text
    assert "sk-abcdef123456" not in text
    assert "sk-zzzzzzzz9999" not in text
    assert "sk-" in text


def test_redact_patterns() -> None:
    source = "手机 13812345678，身份证 110101199001011234，key sk-abcdef123456，邮箱 zhangsan@example.com"
    masked = redact(source)
    assert "13812345678" not in masked and "138****5678" in masked
    assert "110101199001011234" not in masked and "110101********" in masked
    assert "sk-abcdef123456" not in masked and "sk-***" in masked
    assert "zhangsan@example.com" not in masked and "@example.com" in masked
    plain = "今天天气不错，晚上 8 点见。"
    assert redact(plain) == plain


def test_redact_key_value_pairs() -> None:
    masked = redact("api_key=abcdef123456; password: hunter2hunter2")
    assert "abcdef123456" not in masked
    assert "hunter2hunter2" not in masked
    assert "api_key=" in masked


def test_redact_mapping_recursive() -> None:
    data = {"a": ["13812345678", {"b": "sk-abcdef123456"}], "c": 42}
    masked = redact_mapping(data)
    assert masked["a"][0] != "13812345678"
    assert masked["a"][1]["b"] != "sk-abcdef123456"
    assert masked["c"] == 42


def test_self_check_green(tmp_path: Path) -> None:
    report = self_check(tmp_path)
    assert report["ok"] is True, report
    assert Path(report["log_path"]).is_file()
    assert Path(report["audit_path"]).is_file()
    names = {item["name"] for item in report["checks"]}
    required = {
        "log_file",
        "log_format",
        "log_trace_id",
        "audit_file",
        "audit_jsonl",
        "audit_trace_id",
        "redact",
    }
    assert required <= names


def test_shutdown_clears_handlers(tmp_path: Path) -> None:
    setup_logging(tmp_path, console=False)
    assert get_logger().handlers
    shutdown_logging()
    assert not get_logger().handlers
