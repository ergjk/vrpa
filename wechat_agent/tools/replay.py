"""`replay` 命令（M3-07）：去重离线回放与 golden 校验。

用法：
    python -m wechat_agent replay --scenario tests/fixtures/dedup_scenarios/basic_overlap.json
    python -m wechat_agent replay --scenario ... --json

场景 JSON 结构：
    {
      "chat": "测试会话",
      "policy": "ignore",                # 可选：ignore | queue_confirm
      "dedup_window": 200,               # 可选
      "known":   [{"content": "...", "direction": "in", "sender": "张三"}],
      "captured":[{"content": "...", "sender": "张三", "ts": "10:00"}],
      "expected": {"queued": [...], "self_messages": [...], "duplicates": 2, "reason": "ok",
                   "alignment": {"reason": "tail_anchor", "overlap": 2, "added_count": 1}}
    }
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from vrpa.errors import TreeConfigError
from vrpa.memory.db import init_databases
from vrpa.memory.history import HistoryStore
from vrpa.ports import IncomingMessage
from wechat_agent.memory.pipeline import MessagePipeline

__all__ = ["load_scenario", "replay_scenario", "run_replay"]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m wechat_agent replay",
        description="去重离线回放（本地临时库，不污染 data/）",
    )
    parser.add_argument("--scenario", required=True, help="场景 JSON 文件")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    return parser.parse_args(list(argv))


def load_scenario(path: Path | str) -> dict[str, Any]:
    scenario_path = Path(path)
    if not scenario_path.is_file():
        raise TreeConfigError(f"场景文件不存在：{scenario_path}")
    try:
        data = json.loads(scenario_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TreeConfigError(f"场景 JSON 无法解析：{exc}") from exc
    if not isinstance(data, dict) or "chat" not in data:
        raise TreeConfigError("场景缺少 chat 字段")
    return data


def replay_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """在临时双库上回放一个场景，返回与 expected 可直接比较的结果。"""
    chat = str(scenario["chat"])
    known = scenario.get("known") or []
    captured = scenario.get("captured") or []
    with tempfile.TemporaryDirectory(prefix="vrpa_replay_") as tmp:
        databases = init_databases(Path(tmp))
        try:
            history = HistoryStore(databases)
            history.ensure_chat(chat)
            for item in known:
                history.append(
                    chat,
                    str(item.get("content", "")),
                    direction=str(item.get("direction", "in")),
                    sender=item.get("sender"),
                    role=item.get("role"),
                    ts=item.get("ts"),
                    source=str(item.get("source", "replay_seed")),
                )
            pipeline = MessagePipeline(
                history,
                dedup_window=int(scenario.get("dedup_window", 200)),
                low_confidence_policy=str(scenario.get("policy", "ignore")),
            )
            incoming = [
                IncomingMessage(
                    content=str(item.get("content", "")),
                    sender=item.get("sender"),
                    ts=item.get("ts"),
                )
                for item in captured
            ]
            result = pipeline.ingest(chat, incoming)
            return {
                "chat": chat,
                "reason": result.reason,
                "duplicates": result.duplicates,
                "inserted": [record.content for record in result.inserted],
                "queued": [record.content for record in result.queued],
                "self_messages": [record.content for record in result.self_messages],
                "alignment": {
                    "reason": result.alignment.reason,
                    "overlap": result.alignment.overlap,
                    "added_count": result.alignment.added_count,
                    "anchored": result.alignment.anchored,
                    "confidence": result.alignment.confidence,
                },
            }
        finally:
            databases.close()


def run_replay(argv: Sequence[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    try:
        scenario = load_scenario(args.scenario)
        payload = replay_scenario(scenario)
    except TreeConfigError as exc:
        print(f"REPLAY ERROR: {exc}", file=sys.stderr)
        return 2

    expected = scenario.get("expected")
    passed: bool | None = None
    if isinstance(expected, dict):
        passed = _match_expected(payload, expected)

    if args.json:
        output = {**payload, "expected": expected, "passed": passed}
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"chat      : {payload['chat']}")
        print(f"reason    : {payload['reason']}  alignment={payload['alignment']['reason']}")
        print(f"duplicates: {payload['duplicates']}  inserted={len(payload['inserted'])}")
        print(f"queued    : {payload['queued']}")
        print(f"self      : {payload['self_messages']}")
        if passed is not None:
            print(f"golden    : {'PASS' if passed else 'FAIL'}")
        print("RESULT: OK" if passed in (True, None) else "RESULT: FAIL")

    if passed is False:
        return 3
    return 0


def _match_expected(payload: dict[str, Any], expected: dict[str, Any]) -> bool:
    """只比较 expected 中声明的字段（子集匹配）。"""
    for key, value in expected.items():
        if key == "alignment" and isinstance(value, dict):
            actual = payload.get("alignment") or {}
            for sub_key, sub_value in value.items():
                if actual.get(sub_key) != sub_value:
                    return False
            continue
        if payload.get(key) != value:
            return False
    return True
