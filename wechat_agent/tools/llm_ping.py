"""`llm-ping` 命令（M5-05）：LLM 连通性诊断（不产生 Completions 计费）。"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from vrpa.errors import LLMError
from vrpa.llm.client import LLMClient

__all__ = ["run_llm_ping"]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m wechat_agent llm-ping",
        description="LLM 连通性检查（GET /models，不调用付费 Completions）",
    )
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    return parser.parse_args(list(argv))


def run_llm_ping(argv: Sequence[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    from wechat_agent.core.config import load_config

    config = load_config(args.config)
    api_key = config.api_key()
    if not api_key:
        message = "DEEPSEEK_API_KEY 未设置，无法检查 LLM 连通性"
        if args.json:
            print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
        else:
            print(f"LLM ERROR: {message}", file=sys.stderr)
        return 5

    client = LLMClient(
        api_key=api_key,
        base_url=config.llm.base_url,
        model=config.llm.model,
        timeout=config.llm.timeout,
        retries=config.llm.retries,
    )
    try:
        latency = client.ping()
    except LLMError as exc:
        message = exc.message if hasattr(exc, "message") else str(exc)
        if args.json:
            print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
        else:
            print(f"LLM ERROR: {message}", file=sys.stderr)
        return 5

    payload = {
        "ok": True,
        "provider": config.llm.provider,
        "model": config.llm.model,
        "base_url": config.llm.base_url,
        "latency_ms": round(latency, 1),
        "stats": client.stats.as_dict(),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"provider : {payload['provider']}")
        print(f"model    : {payload['model']}")
        print(f"base_url : {payload['base_url']}")
        print(f"latency  : {payload['latency_ms']} ms")
        print("RESULT: OK")
    return 0
