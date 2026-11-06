"""真实 dry-run 主链路（M6 联调）：真实采集/解析/去重入库/回复生成/dry_run 发送/回写。

安全边界：
    - 仅允许 ``config.app.dry_run = true``；否则拒绝运行；
    - 执行器固定 ``allow_real_send=False``，不会真实点击/回车/发送；
    - 采集仍走探针同款「框选 + Ctrl+C + 剪贴板哨兵」；
    - 未配置 LLM Key 时使用本地 EchoBrain（只验证链路，不调用外部 API）。
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from vrpa.errors import AgentFrameworkError, ConfigError
from vrpa.memory.db import init_databases
from vrpa.memory.history import HistoryStore
from vrpa.memory.store import SQLiteMemoryStore
from vrpa.ports import LLMResult
from vrpa.scheduling.loop import ControlChannel, Orchestrator
from vrpa.scheduling.machine import CircuitBreaker, RunStateMachine
from vrpa.scheduling.queue import MessageQueue
from vrpa.scheduling.scheduler import Scheduler
from wechat_agent.act.executor import WeChatExecutor
from wechat_agent.brain.client import WeChatBrain
from wechat_agent.memory.pipeline import MessagePipeline
from wechat_agent.perception.capture import WeChatPerception
from wechat_agent.perception.parser import WeChatParser

__all__ = ["EchoBrain", "execute_dry_run", "run_real"]


class EchoBrain:
    """无 LLM Key 时的本地替身：验证链路，不调用任何外部 API。"""

    def generate(self, messages: Sequence[Any], *, session: str | None = None) -> LLMResult:
        content = ""
        for message in messages:
            if message.get("role") == "user":
                content = str(message.get("content", ""))
        return LLMResult(
            text=f"[dry-run echo] {content[:60]}",
            model="echo",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            latency_ms=0.0,
        )

    def ping(self) -> float:
        return 0.0


def _permissive_scheduler(config: Any) -> Scheduler:
    """dry-run 不真实发送，限流/静默时段不应阻断链路验证。"""
    ratelimit = replace(
        config.ratelimit,
        quiet_hours=(),
        per_chat_per_minute=100000,
        per_chat_per_day=100000,
        global_per_hour=100000,
        cooldown_after_send=(0.0, 0.0),
    )
    return Scheduler(ratelimit)


class _InstantHumanizer:
    def human_send(self, text: str, *, cancel: Any = None) -> bool:
        return not (cancel is not None and cancel.is_set())


def execute_dry_run(
    config: Any,
    *,
    perception: Any,
    chat: str,
    ticks: int = 1,
    brain: Any | None = None,
    force_llm: bool = False,
    settle: float = 0.0,
    sleep: Any = time.sleep,
) -> dict[str, Any]:
    """跑一轮真实 dry-run，返回可审计结果（不发送真实消息）。"""
    if not config.app.dry_run:
        raise ConfigError("真实 dry-run 要求 app.dry_run=true（当前为 false，拒绝运行）")
    databases = init_databases(config.data_dir)
    memory_store = SQLiteMemoryStore(config.data_dir)
    try:
        history = HistoryStore(databases)
        pipeline = MessagePipeline(
            history,
            dedup_window=int(config.capture.dedup_recent_window),
            low_confidence_policy=str(config.capture.low_confidence_policy),
        )
        mode = "echo"
        if brain is None:
            if force_llm or config.api_key():
                if not config.api_key():
                    raise ConfigError("--llm 需要先配置 DEEPSEEK_API_KEY")
                brain = WeChatBrain(config, memory=memory_store)
                mode = "llm"
            else:
                brain = EchoBrain()
                print("未配置 DEEPSEEK_API_KEY：使用本地 EchoBrain（只验证链路，不调用外部 API）", file=sys.stderr)
        else:
            mode = "injected"

        executor = WeChatExecutor(config, allow_real_send=False)
        orchestrator = Orchestrator(
            config,
            perception=perception,
            parser=WeChatParser(),
            pipeline=pipeline,
            brain=brain,
            executor=executor,
            humanizer=_InstantHumanizer(),  # type: ignore[arg-type]
            scheduler=_permissive_scheduler(config),
            queue=MessageQueue(),
            machine=RunStateMachine(),
            breaker=CircuitBreaker(
                max_consecutive_failures=int(config.safety.max_consecutive_failures),
            ),
            control=ControlChannel(),
        )
        perception.activate()
        perception.switch_session(chat)
        if settle > 0:
            sleep(float(settle))
        report = orchestrator.run([chat], max_ticks=max(1, int(ticks)))
        return {
            "ok": report.failures == 0,
            "mode": mode,
            "chat": chat,
            "ticks": report.ticks,
            "state": report.state,
            "captured": sum(tick.captured for tick in report.tick_results),
            "ingested": sum(tick.ingested for tick in report.tick_results),
            "duplicates": report.duplicates,
            "queued_left": report.queue_left,
            "replies": list(report.replies),
            "writes": history.count(chat) if history.get_chat(chat) else 0,
            "failures": report.failures,
            "events": list(report.events),
            "dry_run": True,
        }
    finally:
        memory_store.close()
        databases.close()


def run_real(args: Any) -> int:
    """CLI：``run --real --chat 会话 [--llm] [--ticks N]``。"""
    from wechat_agent.core.config import load_config

    if not args.chat:
        print("--real 需要 --chat 目标会话", file=sys.stderr)
        return 2
    config = load_config(args.config)
    if not config.app.dry_run:
        print("真实 dry-run 要求 dry_run=true；真实发送尚未开放", file=sys.stderr)
        return 2
    warmup = max(0.0, float(getattr(args, "warmup", 5.0) or 0.0))
    if warmup > 0:
        print(f"准备倒计时：{warmup:.0f} 秒后开始真实 dry-run（请切到微信主窗口）", file=sys.stderr)
        remaining = warmup
        while remaining > 0:
            time.sleep(min(1.0, remaining))
            remaining -= 1.0
            if remaining > 0:
                print(f"  剩余 {remaining:.0f} 秒…", file=sys.stderr, flush=True)
    try:
        perception = WeChatPerception(config)
        payload = execute_dry_run(
            config,
            perception=perception,
            chat=str(args.chat),
            ticks=int(args.ticks or 1),
            force_llm=bool(getattr(args, "llm", False)),
            settle=float(getattr(args, "settle", 1.5)),
        )
    except AgentFrameworkError as exc:
        print(f"DRY-RUN ERROR: {exc}", file=sys.stderr)
        return int(exc.exit_code)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"mode     : {payload['mode']}  chat={payload['chat']}")
        print(f"captured : {payload['captured']}  ingested={payload['ingested']}  duplicates={payload['duplicates']}")
        print(f"replies  : {payload['replies']}")
        print(f"writes   : {payload['writes']}  failures={payload['failures']}  state={payload['state']}")
        print("RESULT: OK" if payload["ok"] else "RESULT: FAIL")
    return 0 if payload["ok"] else 1
