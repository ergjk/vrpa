"""双库（chat_history / memory）连接、迁移、备份、自检与修复（平台无关框架能力，M0-06 落地）。

职责：
    connect()              打开连接：WAL / synchronous=NORMAL / foreign_keys=ON / busy_timeout
    migrate(conn, kind)    幂等迁移（schema_meta.version；当前 SCHEMA_VERSION=1）
    init_databases(dir)    建目录 -> 预迁移备份 -> 连接 -> 迁移 -> 返回 Databases
    backup_database()      sqlite3 backup API -> data/backup/<kind>-<ts>.db
    verify_schema()        校验必需表 / 索引 / 版本，返回缺失项（只检测不修复）
    repair_databases()     幂等重放 DDL（IF NOT EXISTS）+ FTS rebuild
    schema_report()        逐表列名 / 索引（db-check --schema 的数据源）

纪律：
- 表结构唯一真源 = schema.sql；本模块不写死任何业务 DDL；
- 迁移只允许「新增」，破坏性变更必须升版本号并显式迁移；
- 错误统一抛 DBError（退出码 6）。
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from vrpa.errors import DBError

SCHEMA_VERSION = 1
SCHEMA_FILE = Path(__file__).with_name("schema.sql")
DB_KINDS: tuple[str, ...] = ("chat_history", "memory")
DB_FILES: dict[str, str] = {"chat_history": "chat_history.db", "memory": "memory.db"}

REQUIRED_TABLES: dict[str, tuple[str, ...]] = {
    "chat_history": (
        "schema_meta",
        "chats",
        "messages",
        "messages_fts",
        "extract_cursor",
        "audit_log",
        "tasks",
        "runtime_state",
    ),
    "memory": ("schema_meta", "memories", "memories_fts", "conversation_summary"),
}

REQUIRED_INDEXES: dict[str, tuple[str, ...]] = {
    "chat_history": (
        "idx_msg_chat_hash",
        "idx_msg_chat_id",
        "idx_audit_chat_created",
        "idx_audit_trace",
        "idx_tasks_state_run",
    ),
    "memory": ("idx_mem_chat_cat", "uq_mem_upsert"),
}

_FTS_SHADOW_RE = re.compile(r"_fts_(data|idx|content|docsize|config)$")
_SECTION_RE = re.compile(r"^--\s*\[DB:\s*([a-z_]+)\]\s*$", re.MULTILINE)


# ============================================================================
# schema.sql 解析
# ============================================================================
def schema_sections() -> dict[str, str]:
    """读取 schema.sql 并按 `-- [DB: kind]` 分段；结果缓存。"""
    try:
        text = SCHEMA_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        raise DBError(f"无法读取 schema.sql（{SCHEMA_FILE}）：{exc}") from exc
    parts = _SECTION_RE.split(text)
    sections: dict[str, str] = {}
    for index in range(1, len(parts), 2):
        kind = parts[index].strip()
        body = parts[index + 1].strip()
        if kind not in DB_KINDS:
            raise DBError(f"schema.sql 中存在未知数据库段：[DB: {kind}]")
        sections[kind] = body
    missing = set(DB_KINDS) - set(sections)
    if missing:
        raise DBError(f"schema.sql 缺少数据库段：{sorted(missing)}")
    return sections


def _section_sql(kind: str) -> str:
    sections = schema_sections()
    try:
        return sections[kind]
    except KeyError as exc:
        raise DBError(f"未知数据库类型：{kind}") from exc


# ============================================================================
# 连接与迁移
# ============================================================================
def connect(path: str | Path) -> sqlite3.Connection:
    """打开 SQLite 连接并设置 WAL 等 PRAGMA（autocommit 模式）。"""
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(target), timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn
    except (sqlite3.Error, OSError) as exc:
        raise DBError(f"无法打开数据库（{target}）：{exc}") from exc


def _ensure_meta(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")


def _current_version(conn: sqlite3.Connection) -> int:
    _ensure_meta(conn)
    row = conn.execute("SELECT value FROM schema_meta WHERE key = 'version'").fetchone()
    return int(row["value"]) if row else 0


def _set_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('version', ?)",
        (str(version),),
    )


def migrate(conn: sqlite3.Connection, kind: str) -> int:
    """幂等迁移：version < 目标 -> 重放 DDL 并写入版本；version 一致 -> 幂等补齐。"""
    if kind not in DB_KINDS:
        raise DBError(f"未知数据库类型：{kind}")
    sql = _section_sql(kind)
    current = _current_version(conn)
    if current > SCHEMA_VERSION:
        raise DBError(f"{kind} 数据库版本 {current} 高于程序支持版本 {SCHEMA_VERSION}，请升级程序或使用匹配版本")
    try:
        # IF NOT EXISTS 幂等：既用于首次迁移，也用于修复误删的表/索引
        conn.executescript(sql)
        _set_version(conn, SCHEMA_VERSION)
    except sqlite3.Error as exc:
        raise DBError(f"{kind} 迁移失败（v{current} -> v{SCHEMA_VERSION}）：{exc}") from exc
    return SCHEMA_VERSION


def backup_database(conn: sqlite3.Connection, backup_dir: str | Path, kind: str) -> Path:
    """用 sqlite3 backup API 生成备份文件（WAL 安全；不依赖文件拷贝）。"""
    directory = Path(backup_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = directory / f"{kind}-{stamp}.db"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        destination = sqlite3.connect(str(target))
        try:
            conn.backup(destination)
        finally:
            destination.close()
    except (sqlite3.Error, OSError) as exc:
        raise DBError(f"备份 {kind} 失败：{exc}") from exc
    return target


@dataclass
class Databases:
    """两个数据库连接的门面；用完必须 close()（Windows 文件锁友好）。"""

    data_dir: Path
    history_path: Path
    memory_path: Path
    history: sqlite3.Connection
    memory: sqlite3.Connection

    def path(self, kind: str) -> Path:
        return self.history_path if kind == "chat_history" else self.memory_path

    def conn(self, kind: str) -> sqlite3.Connection:
        return self.history if kind == "chat_history" else self.memory

    def as_pairs(self) -> Iterator[tuple[str, sqlite3.Connection]]:
        for kind in DB_KINDS:
            yield kind, self.conn(kind)

    def schema_version(self, kind: str) -> int:
        return _current_version(self.conn(kind))

    def table_names(self, kind: str) -> tuple[str, ...]:
        return _user_tables(self.conn(kind))

    def close(self) -> None:
        errors: list[str] = []
        for name, conn in (("history", self.history), ("memory", self.memory)):
            try:
                conn.close()
            except sqlite3.Error as exc:  # pragma: no cover - 极端场景
                errors.append(f"{name}: {exc}")
        if errors:
            raise DBError("关闭数据库失败：" + "; ".join(errors))

    def __enter__(self) -> Databases:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


def init_databases(data_dir: str | Path) -> Databases:
    """建目录 -> 预迁移备份 -> 连接 -> 迁移，返回可用连接门面。"""
    directory = Path(data_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DBError(f"无法创建数据目录（{directory}）：{exc}") from exc

    backup_dir = directory / "backup"
    paths = {kind: directory / DB_FILES[kind] for kind in DB_KINDS}

    # 仅在需要升级时做预迁移备份
    for kind, path in paths.items():
        if not path.is_file() or path.stat().st_size == 0:
            continue
        conn = connect(path)
        try:
            if _current_version(conn) < SCHEMA_VERSION:
                backup_database(conn, backup_dir, kind)
        finally:
            conn.close()

    history = connect(paths["chat_history"])
    memory = connect(paths["memory"])
    try:
        migrate(history, "chat_history")
        migrate(memory, "memory")
    except Exception:
        history.close()
        memory.close()
        raise
    return Databases(
        data_dir=directory,
        history_path=paths["chat_history"],
        memory_path=paths["memory"],
        history=history,
        memory=memory,
    )


# ============================================================================
# 校验 / 修复 / 报告
# ============================================================================
def _raw_table_names(conn: sqlite3.Connection) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return tuple(row["name"] for row in rows)


def _user_tables(conn: sqlite3.Connection) -> tuple[str, ...]:
    """用户表（排除 FTS5 的 data/idx/content/docsize/config 影子表）。"""
    return tuple(name for name in _raw_table_names(conn) if not _FTS_SHADOW_RE.search(name))


def _index_names(conn: sqlite3.Connection) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_autoindex%' ORDER BY name"
    ).fetchall()
    return tuple(row["name"] for row in rows)


def verify_schema(conn: sqlite3.Connection, kind: str) -> list[str]:
    """只检测不修复：返回缺失表 / 缺失索引 / 版本不符等人类可读问题列表。"""
    problems: list[str] = []
    try:
        version = _current_version(conn)
    except sqlite3.Error as exc:
        return [f"读取 schema_meta 失败：{exc}"]
    if version != SCHEMA_VERSION:
        problems.append(f"schema version={version}（期望 {SCHEMA_VERSION}）")
    tables = set(_raw_table_names(conn))
    for table in REQUIRED_TABLES[kind]:
        if table not in tables:
            problems.append(f"缺表 {table}")
    indexes = set(_index_names(conn))
    for index in REQUIRED_INDEXES[kind]:
        if index not in indexes:
            problems.append(f"缺索引 {index}")
    return problems


def _rebuild_fts(conn: sqlite3.Connection, kind: str) -> list[str]:
    warnings: list[str] = []
    fts_tables = [name for name in REQUIRED_TABLES[kind] if name.endswith("_fts")]
    for table in fts_tables:
        try:
            conn.execute(f"INSERT INTO {table}({table}) VALUES ('rebuild')")
        except sqlite3.Error as exc:
            warnings.append(f"{table} rebuild 失败：{exc}")
    return warnings


def repair_databases(dbs: Databases) -> dict[str, list[str]]:
    """幂等重放 DDL + FTS rebuild；返回各库剩余问题（空表示已修复）。"""
    remaining: dict[str, list[str]] = {}
    for kind, conn in dbs.as_pairs():
        try:
            conn.executescript(_section_sql(kind))
            _rebuild_fts(conn, kind)
        except sqlite3.Error as exc:
            raise DBError(f"{kind} 修复失败：{exc}") from exc
        remaining[kind] = verify_schema(conn, kind)
    return remaining


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return []
    return [row["name"] for row in rows]


def schema_report(dbs: Databases) -> dict[str, Any]:
    """结构化报告：两库的版本 / 表与列 / 索引 / 问题列表。"""
    databases: dict[str, Any] = {}
    total_tables = 0
    all_problems: list[str] = []
    for kind, conn in dbs.as_pairs():
        tables = _user_tables(conn)
        total_tables += len(tables)
        columns = {table: _table_columns(conn, table) for table in tables}
        problems = verify_schema(conn, kind)
        all_problems.extend(f"{kind}: {problem}" for problem in problems)
        databases[kind] = {
            "path": str(dbs.path(kind)),
            "version": _current_version(conn),
            "tables": columns,
            "indexes": list(_index_names(conn)),
            "problems": problems,
        }
    return {
        "ok": not all_problems,
        "total_tables": total_tables,
        "databases": databases,
        "problems": all_problems,
    }


def render_schema_report(report: dict[str, Any], *, verbose: bool = False) -> str:
    lines = [f"== db-check（schema v{SCHEMA_VERSION}，共 {report['total_tables']} 张表）=="]
    for kind, info in report["databases"].items():
        status = "OK" if not info["problems"] else "FAIL"
        lines.append(f"[{status}] {kind}: {info['path']}  version={info['version']}")
        if verbose:
            for table, columns in info["tables"].items():
                lines.append(f"    {table}({', '.join(columns)})")
            lines.append(f"    indexes: {', '.join(info['indexes']) or '<none>'}")
        for problem in info["problems"]:
            lines.append(f"    ! {problem}")
    if report["problems"]:
        lines.append("RESULT: FAIL")
    else:
        lines.append("RESULT: OK")
    return "\n".join(lines)
