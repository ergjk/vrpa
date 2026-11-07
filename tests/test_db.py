"""M0-06 双库与迁移单元测试。

覆盖：schema.sql 分段解析、双库建表（12 张主表）、版本与 WAL、迁移幂等、升级前备份、
外键约束、FTS5 触发器同步、档案 upsert 唯一索引、verify/自愈、schema 报告、
db-check CLI（--schema/--repair/--json/未知参数）、坏路径 -> DBError。

运行：python -m pytest tests/test_db.py -q
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from vrpa.errors import DBError, exit_code_for
from vrpa.memory.db import (
    DB_KINDS,
    REQUIRED_INDEXES,
    REQUIRED_TABLES,
    SCHEMA_VERSION,
    connect,
    init_databases,
    schema_report,
    schema_sections,
    verify_schema,
)
from wechat_agent.tools.db_check import run_db_check


@pytest.fixture()
def dbs(tmp_path: Path):
    databases = init_databases(tmp_path)
    try:
        yield databases
    finally:
        databases.close()


def _insert_chat(conn: sqlite3.Connection, name: str = "张三") -> int:
    cursor = conn.execute("INSERT INTO chats(name, type) VALUES (?, 'private')", (name,))
    return int(cursor.lastrowid)


def _insert_message(conn: sqlite3.Connection, chat_id: int, text: str) -> int:
    cursor = conn.execute(
        "INSERT INTO messages(chat_id, direction, content, norm_text, content_hash, source) "
        "VALUES (?, 'in', ?, ?, ?, 'rpa_capture')",
        (chat_id, text, text, f"hash-{text}"),
    )
    return int(cursor.lastrowid)


def test_schema_sections_include_both_dbs() -> None:
    sections = schema_sections()
    assert set(sections) == set(DB_KINDS)
    assert "CREATE TABLE IF NOT EXISTS messages" in sections["chat_history"]
    assert "CREATE TABLE IF NOT EXISTS memories" in sections["memory"]


def test_init_creates_required_tables(dbs) -> None:
    for kind in DB_KINDS:
        tables = set(dbs.table_names(kind))
        missing = set(REQUIRED_TABLES[kind]) - tables
        assert not missing, f"{kind} 缺表：{missing}"
        indexes = {row["name"] for row in dbs.conn(kind).execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        missing_indexes = set(REQUIRED_INDEXES[kind]) - indexes
        assert not missing_indexes, f"{kind} 缺索引：{missing_indexes}"
    assert sum(len(dbs.table_names(kind)) for kind in DB_KINDS) == 13


def test_versions_and_wal(dbs) -> None:
    for kind, conn in dbs.as_pairs():
        assert dbs.schema_version(kind) == SCHEMA_VERSION
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal", f"{kind} journal_mode={mode}"


def test_init_is_idempotent(tmp_path: Path) -> None:
    first = init_databases(tmp_path)
    first.close()
    second = init_databases(tmp_path)
    check = second.history.execute("SELECT COUNT(*) AS n FROM schema_meta WHERE key = 'version'").fetchone()
    second.close()
    assert check["n"] == 1
    # 版本未变化时不应产生备份
    backup_dir = tmp_path / "backup"
    assert not backup_dir.exists() or not list(backup_dir.glob("*.db"))


def test_backup_created_on_upgrade(tmp_path: Path) -> None:
    initial = init_databases(tmp_path)
    initial.close()
    conn = connect(tmp_path / "chat_history.db")
    try:
        conn.execute("UPDATE schema_meta SET value = '0' WHERE key = 'version'")
    finally:
        conn.close()
    again = init_databases(tmp_path)
    again.close()
    backups = list((tmp_path / "backup").glob("chat_history-*.db"))
    assert backups, "升级前应生成预迁移备份"


def test_foreign_keys_enforced(dbs) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        dbs.history.execute(
            "INSERT INTO messages(chat_id, direction, content, norm_text, content_hash, source) "
            "VALUES (9999, 'in', 'x', 'x', 'h', 'rpa_capture')"
        )


def test_fts_trigger_sync(dbs) -> None:
    chat_id = _insert_chat(dbs.history)
    msg_id = _insert_message(dbs.history, chat_id, "你好世界")
    rows = dbs.history.execute("SELECT rowid FROM messages_fts WHERE messages_fts MATCH ?", ("你好世界",)).fetchall()
    assert [row["rowid"] for row in rows] == [msg_id]
    dbs.history.execute("DELETE FROM messages WHERE id = ?", (msg_id,))
    rows = dbs.history.execute("SELECT rowid FROM messages_fts WHERE messages_fts MATCH ?", ("你好世界",)).fetchall()
    assert rows == []


def test_memories_unique_upsert_index(dbs) -> None:
    dbs.memory.execute(
        "INSERT INTO memories(chat_id, category, mem_key, content) VALUES (1, 'preference', '饮料', '喜欢美式')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        dbs.memory.execute(
            "INSERT INTO memories(chat_id, category, mem_key, content) VALUES (1, 'preference', '饮料', '又喜欢拿铁')"
        )


def test_memories_fts_trigger_sync(dbs) -> None:
    dbs.memory.execute(
        "INSERT INTO memories(chat_id, category, mem_key, content) VALUES (1, 'profile', '城市', '住在杭州')"
    )
    rows = dbs.memory.execute("SELECT rowid FROM memories_fts WHERE memories_fts MATCH ?", ("住在杭州",)).fetchall()
    assert len(rows) == 1


def test_verify_detects_missing_index_and_init_heals(tmp_path: Path) -> None:
    initial = init_databases(tmp_path)
    initial.close()
    conn = connect(tmp_path / "chat_history.db")
    try:
        conn.execute("DROP INDEX IF EXISTS idx_msg_chat_hash")
        problems = verify_schema(conn, "chat_history")
    finally:
        conn.close()
    assert any("idx_msg_chat_hash" in problem for problem in problems)
    healed = init_databases(tmp_path)  # 幂等重放 DDL -> 自愈
    try:
        assert verify_schema(healed.history, "chat_history") == []
    finally:
        healed.close()


def test_schema_report(dbs) -> None:
    report = schema_report(dbs)
    assert report["ok"] is True
    assert report["total_tables"] == 13
    assert set(report["databases"]) == set(DB_KINDS)
    for kind in DB_KINDS:
        info = report["databases"][kind]
        assert info["version"] == SCHEMA_VERSION
        assert info["problems"] == []
        expected_table = "messages" if kind == "chat_history" else "memories"
        assert expected_table in info["tables"]


def test_db_check_schema(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = run_db_check(["--schema"], data_dir=tmp_path)
    out = capsys.readouterr().out
    assert code == 0
    assert "chat_history" in out and "memory" in out
    assert "RESULT: OK" in out


def test_db_check_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = run_db_check(["--json"], data_dir=tmp_path)
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True
    assert payload["total_tables"] == 13


def test_db_check_repair(tmp_path: Path) -> None:
    initial = init_databases(tmp_path)
    initial.close()
    conn = connect(tmp_path / "chat_history.db")
    try:
        conn.execute("DROP INDEX IF EXISTS idx_msg_chat_hash")
    finally:
        conn.close()
    assert run_db_check(["--repair"], data_dir=tmp_path) == 0


def test_db_check_unknown_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_db_check(["--bogus"], data_dir=tmp_path) == 2
    assert "未知选项" in capsys.readouterr().err


def test_init_bad_path_raises_db_error(tmp_path: Path) -> None:
    bad = tmp_path / "not_a_dir"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(DBError):
        init_databases(bad)
    assert exit_code_for(DBError("x")) == 6
