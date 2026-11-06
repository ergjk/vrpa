"""应用层 db-check CLI；双库引擎已上提至 ``vrpa.memory.db``（M0-F-05）。

本模块只保留：
    - 应用侧 CLI 参数解析与配置解析（wechat_agent 专属）；
    - 引擎 API 的再导出，保持历史 import 路径可用。

新代码请直接 ``from vrpa.memory.db import ...``。
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from vrpa.memory.db import (  # noqa: F401 - re-export 引擎 API
    DB_FILES,
    DB_KINDS,
    REQUIRED_INDEXES,
    REQUIRED_TABLES,
    SCHEMA_FILE,
    SCHEMA_VERSION,
    Databases,
    backup_database,
    connect,
    init_databases,
    migrate,
    render_schema_report,
    repair_databases,
    schema_report,
    schema_sections,
    verify_schema,
)

_ALLOWED_FLAGS = ("--schema", "--repair", "--json")


def _parse_args(argv: Sequence[str]) -> tuple[bool, bool, bool, str | None]:
    verbose = repair = json_mode = False
    error: str | None = None
    for arg in argv:
        if arg == "--schema":
            verbose = True
        elif arg == "--repair":
            repair = True
        elif arg == "--json":
            json_mode = True
        else:
            error = f"参数错误：未知选项 {arg!r}（可用：--schema、--repair、--json）"
    return verbose, repair, json_mode, error


def _resolve_data_dir(data_dir: str | Path | None, config_path: str | None) -> Path:
    if data_dir is not None:
        return Path(data_dir)
    from wechat_agent.core.config import load_config

    return load_config(config_path).data_dir


def run_db_check(
    argv: Sequence[str],
    *,
    data_dir: str | Path | None = None,
    config_path: str | None = None,
) -> int:
    """db-check 入口；数据库异常由 DBError 冒泡给 main 映射为退出码 6。"""
    verbose, repair, json_mode, error = _parse_args(list(argv))
    if error:
        print(error, file=sys.stderr)
        return 2

    directory = _resolve_data_dir(data_dir, config_path)
    dbs = init_databases(directory)
    try:
        if repair:
            remaining = repair_databases(dbs)
            if any(remaining.values()):
                for kind, problems in remaining.items():
                    for problem in problems:
                        print(f"[repair] {kind} 仍存在问题：{problem}", file=sys.stderr)
        report = schema_report(dbs)
    finally:
        dbs.close()

    if json_mode:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_schema_report(report, verbose=verbose))
    return 0 if report["ok"] else 6
