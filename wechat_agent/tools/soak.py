"""浸泡测试（M6-05）：重复跑 ``--simulate`` 全链路，纯 Fake、零真实键鼠。"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence

__all__ = ["run_soak"]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m wechat_agent soak", description="浸泡测试（simulate）")
    parser.add_argument("--config", default=None)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(list(argv))


def run_soak(argv: Sequence[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    from wechat_agent.core.config import load_config
    from wechat_agent.tools.run import simulate

    config = load_config(args.config)
    iterations = max(1, int(args.iterations))
    started = time.perf_counter()
    replies: list[str] = []
    states: list[str] = []
    failures = 0
    duplicates = 0
    for index in range(iterations):
        scenario = {
            "chats": ["张三"],
            "captures": {
                "张三": [
                    f"10:00 张三: 浸泡消息 {index}",
                    f"10:00 张三: 浸泡消息 {index}",
                ]
            },
            "replies": {"张三": [f"浸泡回复 {index}"]},
            "ticks": 2,
        }
        payload = simulate(scenario, config)
        replies.extend(payload["replies"])
        states.append(str(payload["state"]))
        failures += int(payload["failures"])
        duplicates += int(payload["duplicates"])
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    ok = failures == 0 and all(state == "running" for state in states)
    report = {
        "ok": ok,
        "iterations": iterations,
        "replies": len(replies),
        "states": sorted(set(states)),
        "failures": failures,
        "duplicates": duplicates,
        "duration_ms": duration_ms,
        "dry_run": True,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"iterations: {iterations}  replies={len(replies)}  failures={failures}")
        print(f"states    : {sorted(set(states))}  duration={duration_ms}ms  dry_run=True")
        print("RESULT: OK" if ok else "RESULT: FAIL")
    return 0 if ok else 1
