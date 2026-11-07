"""`memory-extract`：处理异步记忆提炼任务队列（只读流水，写档案库）。"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from vrpa.errors import ConfigError, LLMError
from vrpa.memory.db import init_databases
from vrpa.memory.store import SQLiteMemoryStore
from wechat_agent.memory.job_factory import build_memory_extract_job

__all__ = ["run_memory_extract"]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m wechat_agent memory-extract",
        description="处理异步记忆提炼任务（LLM 人格筛选；无任务则立即退出）",
    )
    parser.add_argument("--config", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(list(argv))


def run_memory_extract(argv: Sequence[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    from wechat_agent.core.config import load_config

    config = load_config(args.config)
    databases = init_databases(config.data_dir)
    memory_store = SQLiteMemoryStore(config.data_dir)
    try:
        job = build_memory_extract_job(config, databases, memory_store)
        if job is None:
            print("缺少 DEEPSEEK_API_KEY，无法运行记忆筛选", file=sys.stderr)
            return 5
        processed = job.run_pending(limit=max(1, int(args.limit)))
        payload = {
            "ok": True,
            "processed": processed,
            "queue_left": len(job._queue.pending(limit=1000)),  # noqa: SLF001 - 只读统计
        }
    except (ConfigError, LLMError) as exc:
        print(f"MEMORY EXTRACT ERROR: {exc}", file=sys.stderr)
        return int(getattr(exc, "exit_code", 5))
    finally:
        memory_store.close()
        databases.close()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"processed={payload['processed']} queue_left={payload['queue_left']}")
    return 0
