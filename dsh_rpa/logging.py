"""框架日志与审计（平台无关）：RotatingFileHandler、trace_id、JSONL 审计、脱敏。

命名空间与数据目录环境变量**可配置**（默认中性值），由应用层在包入口调用
``configure_logging_namespace()`` 注入；框架自身不硬编码任何平台名。

公开 API：
    setup_logging / shutdown_logging / get_logger / log_path
    new_trace_id / current_trace_id / bind_trace / trace_scope / TraceFilter
    redact / redact_mapping
    audit / setup_audit / audit_path / AuditLogger
    self_check（供 selftest 使用）
    configure_logging_namespace / get_namespace_config / logger_namespace
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import logging.handlers
import os
import re
import sys
import threading
import uuid
from collections import deque
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

__all__ = [
    "AUDIT_FILE_NAME",
    "LOG_BACKUP_COUNT",
    "LOG_FILE_NAME",
    "LOG_FORMAT",
    "LOG_MAX_BYTES",
    "TRACE_ID_LEN",
    "AuditLogger",
    "LoggingNamespace",
    "TraceFilter",
    "audit",
    "audit_path",
    "bind_trace",
    "configure_logging_namespace",
    "current_trace_id",
    "get_logger",
    "get_namespace_config",
    "log_path",
    "logger_namespace",
    "new_trace_id",
    "redact",
    "redact_mapping",
    "self_check",
    "setup_audit",
    "setup_logging",
    "shutdown_logging",
    "trace_scope",
]

LOG_FILE_NAME = "agent.log"
AUDIT_FILE_NAME = "audit.jsonl"
LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(trace_id)s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5
TRACE_ID_LEN = 8

_TRACE_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} (DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+\[[0-9a-f]{8}\]")
_LEVELS: dict[str, int] = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}

_trace_var: contextvars.ContextVar[str] = contextvars.ContextVar("dsh_trace_id", default="-")
_setup_lock = threading.RLock()
_state: dict[str, Any] = {}
_audit: AuditLogger | None = None


@dataclass(frozen=True)
class LoggingNamespace:
    """当前进程的日志命名空间与数据目录环境变量（按优先级）。"""

    name: str
    data_dir_envs: tuple[str, ...]


_runtime = LoggingNamespace(name="dsh_rpa", data_dir_envs=("DSH_RPA_DATA_DIR",))


def configure_logging_namespace(
    namespace: str,
    *,
    data_dir_env: str | Sequence[str] | None = None,
) -> LoggingNamespace:
    """配置日志命名空间（应用层在包入口调用）；返回旧配置便于测试恢复。"""
    global _runtime
    name = namespace.strip()
    if not name:
        raise ValueError("日志命名空间不能为空")
    if data_dir_env is None:
        envs = _runtime.data_dir_envs
    elif isinstance(data_dir_env, str):
        envs = (data_dir_env,)
    else:
        envs = tuple(data_dir_env)
    if not envs:
        raise ValueError("data_dir_env 不能为空")
    previous = _runtime
    _runtime = LoggingNamespace(name=name, data_dir_envs=envs)
    return previous


def get_namespace_config() -> LoggingNamespace:
    """读取当前命名空间配置（测试保存/恢复用）。"""
    return _runtime


def logger_namespace() -> str:
    return _runtime.name


# ============================================================================
# trace_id
# ============================================================================
def new_trace_id() -> str:
    """生成 8 位十六进制 trace_id（每轮采集/每次发送一条）。"""
    return uuid.uuid4().hex[:TRACE_ID_LEN]


def current_trace_id() -> str:
    """当前上下文的 trace_id；未绑定返回 "-"。"""
    return _trace_var.get()


def bind_trace(trace_id: str) -> contextvars.Token[str]:
    """手动绑定 trace_id；返回 token，调用方负责 reset。"""
    if not re.fullmatch(r"[0-9a-f]{8}", trace_id):
        raise ValueError(f"trace_id 必须是 8 位小写十六进制：{trace_id!r}")
    return _trace_var.set(trace_id)


@contextlib.contextmanager
def trace_scope(trace_id: str | None = None) -> Iterator[str]:
    """在 with 块内绑定 trace_id（不传则自动生成），退出时恢复外层。"""
    tid = new_trace_id() if trace_id is None else trace_id
    token = bind_trace(tid)
    try:
        yield tid
    finally:
        _trace_var.reset(token)


class TraceFilter(logging.Filter):
    """把当前 trace_id 注入 LogRecord；外部已显式设置则不覆盖。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "trace_id", None):
            record.trace_id = current_trace_id()
        return True


# ============================================================================
# 日志配置
# ============================================================================
def _coerce_level(level: str | int) -> int:
    if isinstance(level, bool):
        raise ValueError(f"非法日志级别：{level!r}")
    if isinstance(level, int):
        if level not in _LEVELS.values():
            raise ValueError(f"非法日志级别：{level!r}")
        return level
    key = str(level).strip().upper()
    if key not in _LEVELS:
        raise ValueError(f"非法日志级别：{level!r}（可选：{sorted(_LEVELS)}）")
    return _LEVELS[key]


def _build_formatter() -> logging.Formatter:
    return logging.Formatter(LOG_FORMAT, DATE_FORMAT, defaults={"trace_id": "-"})


def get_logger(name: str | None = None) -> logging.Logger:
    """取当前命名空间下的 logger。"""
    namespace = logger_namespace()
    if not name:
        return logging.getLogger(namespace)
    if name == namespace or name.startswith(f"{namespace}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{namespace}.{name}")


def _close_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        with contextlib.suppress(Exception):
            handler.flush()
        with contextlib.suppress(Exception):
            handler.close()


def setup_logging(
    log_dir: str | os.PathLike[str],
    level: str | int = "INFO",
    *,
    console: bool = True,
    force: bool = False,
    max_bytes: int = LOG_MAX_BYTES,
    backup_count: int = LOG_BACKUP_COUNT,
) -> logging.Logger:
    """配置当前命名空间 logger（幂等；force=True 时重建 handler）。"""
    valid_level = _coerce_level(level)
    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    log_path_ = directory / LOG_FILE_NAME
    resolved = str(log_path_.resolve())

    with _setup_lock:
        logger = get_logger()
        same_target = (
            _state.get("log_path") == resolved
            and _state.get("level") == valid_level
            and _state.get("console") == console
            and bool(logger.handlers)
        )
        if same_target and not force:
            return logger

        _close_handlers(logger)
        logger.setLevel(valid_level)
        logger.propagate = False

        formatter = _build_formatter()
        file_handler = logging.handlers.RotatingFileHandler(
            log_path_,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(valid_level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(TraceFilter())
        logger.addHandler(file_handler)

        if console:
            stream_handler = logging.StreamHandler(stream=sys.stderr)
            stream_handler.setLevel(valid_level)
            stream_handler.setFormatter(formatter)
            stream_handler.addFilter(TraceFilter())
            logger.addHandler(stream_handler)

        _state.update(
            log_path=resolved,
            level=valid_level,
            console=console,
            max_bytes=max_bytes,
            backup_count=backup_count,
        )
        _set_default_audit(directory)
        return logger


def shutdown_logging() -> None:
    """关闭并移除当前命名空间全部 handler，重置审计单例。"""
    global _audit
    with _setup_lock:
        logger = get_logger()
        _close_handlers(logger)
        logger.setLevel(logging.NOTSET)
        logger.propagate = True
        _state.clear()
        _audit = None


def log_path() -> Path | None:
    value = _state.get("log_path")
    return Path(value) if value else None


# ============================================================================
# 脱敏
# ============================================================================
_SK_RE = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")
_KV_RE = re.compile(
    r"(?i)\b(api[_-]?key|apikey|token|secret|password|passwd|pwd|authorization)\b"
    r"(\s*[:=]\s*)([^\s,;'\"}]{6,})"
)
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_ID18_RE = re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)")
_EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]{1,64})"
    r"@([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+)"
)


def _mask_keep(value: str, head: int, tail: int, *, mask_char: str = "*") -> str:
    """保留首/尾若干字符，中间打码；tail=0 表示不保留尾部。"""
    head = max(0, head)
    tail = max(0, tail)
    if len(value) <= head + tail:
        return mask_char * 3
    suffix = value[-tail:] if tail else ""
    return f"{value[:head]}{mask_char * (len(value) - head - tail)}{suffix}"


def redact(text: str) -> str:
    """对文本中的 API Key / 手机号 / 身份证 / 邮箱打码；其余内容原样保留。"""
    if not text or not isinstance(text, str):
        return text

    def _mask_kv(match: re.Match[str]) -> str:
        return f"{match.group(1)}{match.group(2)}***"

    def _mask_sk(match: re.Match[str]) -> str:
        return _mask_keep(match.group(0), 3, 4)

    def _mask_id(match: re.Match[str]) -> str:
        return _mask_keep(match.group(1), 6, 4)

    def _mask_phone(match: re.Match[str]) -> str:
        return _mask_keep(match.group(1), 3, 4)

    def _mask_email(match: re.Match[str]) -> str:
        return f"{_mask_keep(match.group(1), 2, 0)}@{match.group(2)}"

    result = _KV_RE.sub(_mask_kv, text)
    result = _SK_RE.sub(_mask_sk, result)
    result = _ID18_RE.sub(_mask_id, result)
    result = _PHONE_RE.sub(_mask_phone, result)
    result = _EMAIL_RE.sub(_mask_email, result)
    return result


def redact_mapping(value: Any) -> Any:
    """递归对 dict/list/tuple/str 做脱敏（用于审计记录整体脱敏）。"""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, Mapping):
        return {key: redact_mapping(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_mapping(item) for item in value]
    return value


# ============================================================================
# 审计
# ============================================================================
def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class AuditLogger:
    """追加写 JSONL 审计日志（每行一条 JSON，线程安全）。"""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def write(self, record: Mapping[str, Any]) -> dict[str, Any]:
        item = dict(record)
        item.setdefault("ts", _now_iso())
        item.setdefault("trace_id", current_trace_id())
        prepared: dict[str, Any] = redact_mapping(item)
        line = json.dumps(prepared, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
            handle.flush()
        return prepared


def _set_default_audit(log_dir: Path) -> None:
    global _audit
    _audit = AuditLogger(log_dir / AUDIT_FILE_NAME)


def setup_audit(log_dir: str | os.PathLike[str]) -> AuditLogger:
    """显式指定审计日志目录（默认随 setup_logging 一起配置）。"""
    global _audit
    with _setup_lock:
        _set_default_audit(Path(log_dir))
        assert _audit is not None
        return _audit


def _default_data_dir() -> Path:
    for env_name in _runtime.data_dir_envs:
        value = os.environ.get(env_name, "").strip()
        if value:
            return Path(value) / "logs"
    return Path("data") / "logs"


def audit(record: Mapping[str, Any]) -> dict[str, Any]:
    """写一条审计记录；未配置时落 <data_dir>/logs/audit.jsonl。"""
    global _audit
    with _setup_lock:
        if _audit is None:
            _set_default_audit(_default_data_dir())
        assert _audit is not None
        logger = _audit
    return logger.write(record)


def audit_path() -> Path | None:
    with _setup_lock:
        return _audit.path if _audit is not None else None


# ============================================================================
# selftest 支持
# ============================================================================
def _tail_lines(path: Path, count: int) -> list[str]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return [line.rstrip("\n") for line in deque(handle, maxlen=count)]


def self_check(log_dir: str | os.PathLike[str]) -> dict[str, Any]:
    """写日志 + 审计各一条并回读校验；返回 {"ok", "log_path", "audit_path", "checks"}。"""
    directory = Path(log_dir)
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    try:
        logger = setup_logging(directory, level="INFO", console=False, force=True)
        tid = new_trace_id()
        with trace_scope(tid):
            logger.info("logging self-check")
        for handler in logger.handlers:
            with contextlib.suppress(Exception):
                handler.flush()

        log_file = directory / LOG_FILE_NAME
        last_log = (_tail_lines(log_file, 5) or [""])[-1]
        add("log_file", log_file.is_file(), str(log_file))
        add("log_format", bool(_TRACE_RE.match(last_log)), last_log[:120] or "<空>")
        add("log_trace_id", tid in last_log, tid)

        item = audit({"event": "selftest", "detail": "audit self-check", "trace_id": tid})
        audit_file = directory / AUDIT_FILE_NAME
        add("audit_file", audit_file.is_file(), str(audit_file))
        add("audit_trace_id", item.get("trace_id") == tid, str(item.get("trace_id")))
        add(
            "audit_ts",
            isinstance(item.get("ts"), str) and "T" in str(item.get("ts")),
            str(item.get("ts")),
        )

        last_lines = _tail_lines(audit_file, 3)
        parsed_ok = False
        parse_detail = "无审计行"
        if last_lines:
            try:
                parsed = json.loads(last_lines[-1])
                parsed_ok = isinstance(parsed, dict) and parsed.get("trace_id") == tid
                parse_detail = json.dumps(parsed, ensure_ascii=False)[:120]
            except json.JSONDecodeError as exc:
                parse_detail = f"JSON 解析失败：{exc}"
        add("audit_jsonl", parsed_ok, parse_detail)

        sample = "手机 13812345678 身份证 110101199001011234 key sk-abcdef123456"
        masked = redact(sample)
        redact_ok = (
            "13812345678" not in masked and "110101199001011234" not in masked and "sk-abcdef123456" not in masked
        )
        add("redact", redact_ok, masked)
    except Exception as exc:  # noqa: BLE001 - 自检不得让上层崩溃
        add("logging_exception", False, repr(exc))

    return {
        "ok": all(item["ok"] for item in checks),
        "log_path": str(directory / LOG_FILE_NAME),
        "audit_path": str(directory / AUDIT_FILE_NAME),
        "checks": checks,
    }
