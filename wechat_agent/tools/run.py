"""`run` 命令（M4-05/06）：``--simulate`` 全链路（Fake 后端 + dry_run，绝不触发真实键鼠）。

真实微信运行需要 M6 后端接入；当前只提供 simulate 模式用于全链路验收。
场景 JSON：chats / captures / replies / ticks / control / capture_failures / expected。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from vrpa.errors import CopyFailed, TreeConfigError
from vrpa.memory.db import init_databases
from vrpa.memory.history import HistoryStore
from vrpa.parsing import StrategyDispatcher
from vrpa.ports import LLMResult
from vrpa.scheduling.delay import Humanizer
from vrpa.scheduling.loop import ControlCommand, Orchestrator
from vrpa.scheduling.machine import CircuitBreaker, RunStateMachine
from vrpa.scheduling.queue import MessageQueue
from vrpa.scheduling.scheduler import Scheduler
from vrpa.testing.fakes import FakeExecutor
from wechat_agent.memory.pipeline import MessagePipeline
from wechat_agent.perception.parser import WeChatParser

__all__ = ["load_scenario", "run_run", "simulate"]

_ = (random, StrategyDispatcher, Humanizer)


class ScriptedPerception:
    """按会话脚本返回剪贴板文本；可模拟连续采集失败。"""

    def __init__(self, captures: dict[str, list[str]], *, failures: int = 0) -> None:
        self._captures = {chat: list(texts) for chat, texts in captures.items()}
        self._failures = failures
        self.calls = 0

    def capture(self, session: str) -> str:
        self.calls += 1
        if self._failures > 0:
            self._failures -= 1
            raise CopyFailed(f"simulate: 第 {self.calls} 次采集失败")
        queue = self._captures.get(session, [])
        return queue.pop(0) if queue else ""

    def activate(self) -> None:
        return None

    def switch_session(self, session: str) -> None:
        return None


class ScriptedBrain:
    """按会话返回脚本化回复（耗尽后用默认回复）。"""

    def __init__(self, replies: dict[str, list[str]], *, default: str = "模拟回复") -> None:
        self._replies = {chat: list(texts) for chat, texts in replies.items()}
        self._default = default
        self.calls = 0

    def generate(self, messages: Sequence[Any], *, session: str | None = None) -> LLMResult:
        self.calls += 1
        queue = self._replies.get(session or "", [])
        text = queue.pop(0) if queue else self._default
        return LLMResult(text=text, model="fake-model", usage={"total_tokens": len(text)}, latency_ms=0.1)

    def ping(self) -> float:
        return 0.1


class InstantHumanizer:
    """simulate 用：不等待，但仍响应打断事件。"""

    def human_send(self, text: str, *, cancel: Any = None) -> bool:
        return not (cancel is not None and cancel.is_set())


def load_scenario(path: Path | str) -> dict[str, Any]:
    scenario_path = Path(path)
    if not scenario_path.is_file():
        raise TreeConfigError(f"场景文件不存在：{scenario_path}")
    try:
        data = json.loads(scenario_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TreeConfigError(f"场景 JSON 无法解析：{exc}") from exc
    if not isinstance(data, dict) or "chats" not in data:
        raise TreeConfigError("场景缺少 chats 字段")
    return data


def _scheduler_for(config: Any) -> Scheduler:
    deterministic = replace(
        config.ratelimit,
        quiet_hours=(),
        per_chat_per_minute=100,
        per_chat_per_day=10000,
        global_per_hour=10000,
        cooldown_after_send=(0.0, 0.0),
    )
    return Scheduler(deterministic, rng=random.Random(0))


def simulate(scenario: dict[str, Any], config: Any, *, ticks: int | None = None) -> dict[str, Any]:
    """在临时双库上跑完整编排链路（Fake 后端、dry_run）。"""
    chats = [str(chat) for chat in scenario["chats"]]
    total_ticks = int(ticks if ticks is not None else scenario.get("ticks", 3))
    ttl = scenario.get("capture_failures", 0)
    if isinstance(ttl, dict):  # 兼容 {"total": 3}
        ttl = int(ttl.get("total", 0))
    failures = int(ttl or 0)
    perception = ScriptedPerception(scenario.get("captures") or {}, failures=failures)
    brain = ScriptedBrain(scenario.get("replies") or {})
    executor = FakeExecutor(dry_run=True)
    control_commands = scenario.get("control") or []

    with tempfile.TemporaryDirectory(prefix="vrpa_sim_") as tmp:
        databases = init_databases(Path(tmp))
        try:
            history = HistoryStore(databases)
            pipeline = MessagePipeline(history)
            orchestrator = Orchestrator(
                config,
                perception=perception,
                parser=WeChatParser(),
                pipeline=pipeline,
                brain=brain,
                executor=executor,
                humanizer=InstantHumanizer(),
                scheduler=_scheduler_for(config),
                queue=MessageQueue(),
                machine=RunStateMachine(),
                breaker=CircuitBreaker(max_consecutive_failures=3, clock=lambda: 0.0),
                control=None,
            )
            orchestrator.start()
            tick_results = []
            for tick in range(1, total_ticks + 1):
                for command in _commands_for_tick(control_commands, tick):
                    orchestrator.submit(
                        ControlCommand(
                            action=str(command.get("action", "")),
                            chat=command.get("chat"),
                            text=command.get("text"),
                            reason=str(command.get("reason", "")),
                        )
                    )
                tick_results.append(orchestrator.tick(chats))
            report = orchestrator.run(chats, max_ticks=0)
            history_rows = {chat: history.count(chat) for chat in chats if history.get_chat(chat)}
            payload = {
                "chats": chats,
                "ticks": len(tick_results),
                "state": report.state,
                "breaker": report.breaker,
                "replies": [reply for tick in tick_results for reply in tick.replies],
                "sent": [{"chat": chat, "text": text, "trigger": trigger} for chat, text, trigger in executor.sent],
                "writes": history_rows,
                "duplicates": sum(tick.duplicates for tick in tick_results),
                "failures": sum(tick.failures for tick in tick_results),
                "events": [event for tick in tick_results for event in tick.events],
                "queue_left": len(orchestrator.queue),
            }
            return payload
        finally:
            databases.close()


def _commands_for_tick(commands: Sequence[dict[str, Any]], tick: int) -> list[dict[str, Any]]:
    return [command for command in commands if int(command.get("tick", 0)) == tick]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m wechat_agent run",
        description="主进程编排：--simulate（Fake 全链路）/ --real（真实采集 dry-run，绝不真实发送）",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--simulate", action="store_true", help="Fake 后端模拟全链路")
    mode.add_argument("--real", action="store_true", help="真实采集 dry-run（仅 dry_run=true，绝不真实发送）")
    parser.add_argument("--scenario", default=None, help="模拟场景 JSON（仅 --simulate）")
    parser.add_argument("--chat", default=None, help="目标会话（仅 --real）")
    parser.add_argument("--llm", action="store_true", help="强制真实 LLM（仅 --real，需要 API Key）")
    parser.add_argument("--drag-from", default=None, help="--real 临时覆盖拖拽起点比例 x,y（如 0.10,0.85）")
    parser.add_argument("--drag-to", default=None, help="--real 临时覆盖拖拽终点比例 x,y（如 0.90,0.15）")
    parser.add_argument("--drag-duration", type=float, default=None, help="--real 临时覆盖拖拽时长（默认 0.9s）")
    parser.add_argument(
        "--multi", action="store_true", help="--real 多条采集：头像列顶部→越界底部（覆盖头像/气泡区）+ 更长终点停留"
    )
    parser.add_argument("--dump", default=None, help="--real 把每次采集的原始剪贴板文本写入文件（诊断用）")
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--ticks", type=int, default=None, help="tick 数（--real 默认 1）")
    parser.add_argument("--warmup", type=float, default=5.0, help="--real 启动倒计时秒数（切到微信）")
    parser.add_argument("--settle", type=float, default=1.5, help="--real 切会话后的稳定等待秒数")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    return parser.parse_args(list(argv))


def run_run(argv: Sequence[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    if args.real:
        from wechat_agent.tools.run_real import run_real

        return run_real(args)
    if not args.scenario:
        print("--simulate 需要 --scenario 场景文件", file=sys.stderr)
        return 2
    try:
        scenario = load_scenario(args.scenario)
        from wechat_agent.core.config import load_config

        config = load_config(args.config)
        payload = simulate(scenario, config, ticks=args.ticks)
    except TreeConfigError as exc:
        print(f"SIMULATE ERROR: {exc}", file=sys.stderr)
        return 2

    expected = scenario.get("expected")
    passed: bool | None = None
    if isinstance(expected, dict):
        passed = all(_subset(payload, key, value) for key, value in expected.items())
    payload["expected"] = expected
    payload["passed"] = passed
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"state     : {payload['state']}  breaker={payload['breaker']}")
        print(f"replies   : {payload['replies']}")
        print(f"sent      : {[(item['chat'], item['trigger']) for item in payload['sent']]}")
        print(
            f"duplicates: {payload['duplicates']}  failures={payload['failures']}  queue_left={payload['queue_left']}"
        )
        print(f"events    : {payload['events']}")
        if passed is not None:
            print(f"golden    : {'PASS' if passed else 'FAIL'}")
        print("RESULT: OK" if passed in (True, None) else "RESULT: FAIL")
    if passed is False:
        return 3
    return 0


def _subset(payload: dict[str, Any], key: str, expected: Any) -> bool:
    return payload.get(key) == expected
