"""运行报告（M6-05）：只读汇总双库与任务状态，生成 Markdown/JSON，不触发任何 UI。"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

__all__ = ["build_report", "render_markdown", "run_report"]


def _count(db_path: Path, sql: str) -> int:
    if not db_path.is_file():
        return 0
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            return int(connection.execute(sql).fetchone()[0])
        finally:
            connection.close()
    except sqlite3.Error:
        return 0


def build_report(config: Any) -> dict[str, Any]:
    data_dir = Path(config.data_dir)
    history = data_dir / "chat_history.db"
    memory = data_dir / "memory.db"
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dry_run": bool(config.app.dry_run),
        "model": config.llm.model,
        "prompt_trim_policy": config.llm.prompt_trim_policy,
        "databases": {
            "chats": _count(history, "SELECT COUNT(*) FROM chats"),
            "messages": _count(history, "SELECT COUNT(*) FROM messages"),
            "tasks": _count(history, "SELECT COUNT(*) FROM tasks"),
            "tasks_pending": _count(history, "SELECT COUNT(*) FROM tasks WHERE state='pending'"),
            "tasks_done": _count(history, "SELECT COUNT(*) FROM tasks WHERE state='done'"),
            "tasks_failed": _count(history, "SELECT COUNT(*) FROM tasks WHERE state='failed'"),
            "memories": _count(memory, "SELECT COUNT(*) FROM memories WHERE deleted=0"),
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    db = payload["databases"]
    return "\n".join(
        [
            "# 运行报告",
            "",
            f"- 生成时间：{payload['generated_at']}",
            f"- dry_run：{payload['dry_run']}",
            f"- 模型：{payload['model']}（trim_policy={payload['prompt_trim_policy']}）",
            "",
            "## 双库统计",
            "",
            f"- 会话：{db['chats']}，消息：{db['messages']}，记忆：{db['memories']}",
            f"- 任务：总 {db['tasks']} / pending {db['tasks_pending']} / done {db['tasks_done']} / failed {db['tasks_failed']}",
            "",
            "> 本报告只读生成，不含任何真实键鼠操作。",
            "",
        ]
    )


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m wechat_agent report", description="运行报告（只读）")
    parser.add_argument("--config", default=None)
    parser.add_argument("--output", default=None, help="Markdown 输出路径")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(list(argv))


def run_report(argv: Sequence[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    from wechat_agent.core.config import load_config

    config = load_config(args.config)
    payload = build_report(config)
    output = (
        Path(args.output)
        if args.output
        else Path(config.data_dir) / "reports" / f"report_{datetime.now():%Y%m%d_%H%M%S}.md"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(payload), encoding="utf-8")
    payload["output"] = str(output)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"report : {output}")
        print(f"dry_run: {payload['dry_run']}  messages={payload['databases']['messages']}")
        print("RESULT: OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run_report(sys.argv[1:]))
