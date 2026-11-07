"""受控真实发送循环：``run --live``（默认关闭，单轮最多 1 条，失败即停）。"""

from __future__ import annotations

import contextlib
import ctypes
import json
import sys
import time
from typing import Any

from vrpa.errors import AgentFrameworkError, ConfigError
from vrpa.memory.db import init_databases
from vrpa.memory.history import HistoryStore
from vrpa.memory.store import SQLiteMemoryStore
from vrpa.scheduling.delay import Humanizer
from vrpa.scheduling.loop import ControlChannel, Orchestrator
from vrpa.scheduling.machine import CircuitBreaker, RunStateMachine
from vrpa.scheduling.queue import MessageQueue, QueuedMessage
from vrpa.scheduling.scheduler import Scheduler
from vrpa.vision.driver import PyAutoGuiDriver
from wechat_agent.act.executor import WeChatExecutor
from wechat_agent.brain.client import WeChatBrain
from wechat_agent.core.next_action import explain_failure, explain_reason
from wechat_agent.identity import load_identity
from wechat_agent.memory.job_factory import build_memory_extract_job
from wechat_agent.memory.pipeline import MessagePipeline
from wechat_agent.perception.capture import WeChatPerception
from wechat_agent.perception.element_tree import WeChatElementTree
from wechat_agent.perception.parser import WeChatParser
from wechat_agent.perception.window import WeChatWindow
from wechat_agent.tools.run_real import _GuardedPerception

__all__ = ["run_live"]


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def _refuse(reason: str) -> int:
    print(f"LIVE SERIES REFUSED: {reason}", file=sys.stderr)
    return 2


def run_live(args: Any) -> int:
    if not args.chat:
        return _refuse("--live 需要 --chat 目标会话")
    if not getattr(args, "i_understand_risk", False):
        return _refuse("真实发送循环必须显式传入 --i-understand-risk")
    max_sends = int(getattr(args, "max_sends", 0) or 0)
    if max_sends < 1:
        return _refuse("--max-sends 必须 >= 1（首版禁止无限循环）")
    if not _is_admin():
        return _refuse("真实发送循环需要管理员 PowerShell（否则输入注入会被丢弃）")

    from wechat_agent.core.config import load_config

    config = load_config(args.config)
    if config.app.dry_run:
        return _refuse("app.dry_run=true；请先显式改为 false")
    if not config.safety.allow_real_send:
        return _refuse("safety.allow_real_send=false；真实发送总开关未开启")
    if args.chat not in tuple(config.safety.real_send_allowlist):
        return _refuse(f"会话 {args.chat!r} 不在 real_send_allowlist={list(config.safety.real_send_allowlist)}")

    interval = max(0.0, float(getattr(args, "interval", 30.0) or 0.0))
    databases = init_databases(config.data_dir)
    memory_store = SQLiteMemoryStore(config.data_dir)
    tree = WeChatElementTree(config)
    window = WeChatWindow(config)
    driver = PyAutoGuiDriver()
    parser = WeChatParser()
    perception = WeChatPerception(
        config,
        tree=tree,
        driver=driver,
        window=window,
        verify_session_capture=False,
    )
    try:
        history = HistoryStore(databases)
        identity = load_identity(config.data_dir)
        pipeline = MessagePipeline(
            history,
            dedup_window=int(config.capture.dedup_recent_window),
            low_confidence_policy=str(config.capture.low_confidence_policy),
            identity=identity,
        )
        memory_job = build_memory_extract_job(config, databases, memory_store)
        guarded = _GuardedPerception(perception, history, parser)
        brain = WeChatBrain(config, memory=memory_store, identity=identity)

        def _capture_after_send(session: str) -> str:
            last = ""
            for _ in range(3):
                with contextlib.suppress(Exception):
                    perception.scroll_to_bottom()
                last = str(perception.capture(session))
                if last.strip():
                    return last
                time.sleep(0.8)
            return last

        executor = WeChatExecutor(
            config,
            window=window,
            driver=driver,
            capture=_capture_after_send,
            tree=tree,
            allow_real_send=True,
        )
        humanize = config.humanize
        humanizer = Humanizer(
            think_delay=tuple(humanize.think_delay),
            typing_ms_per_char=tuple(humanize.typing_ms_per_char),
            pre_send_delay=tuple(humanize.pre_send_delay),
            long_reply_extra=tuple(humanize.long_reply_extra),
        )
        queue = MessageQueue()
        orchestrator = Orchestrator(
            config,
            perception=guarded,
            parser=parser,
            pipeline=pipeline,
            brain=brain,
            executor=executor,
            humanizer=humanizer,
            scheduler=Scheduler(config.ratelimit),
            queue=queue,
            machine=RunStateMachine(),
            breaker=CircuitBreaker(max_consecutive_failures=1),
            control=ControlChannel(),
            memory_job=memory_job,
            pending_store=history,
        )
        perception.activate()
        perception.switch_session(args.chat)
        pending = history.pending_replies(args.chat, limit=max(5, max_sends * 2))
        for item in pending:
            queue.push(QueuedMessage(chat=args.chat, content=item.content, message_id=item.message_id))
        if pending:
            print(f"恢复未回复消息：{len(pending)} 条", file=sys.stderr)
        orchestrator.start()

        sent: list[str] = []
        events: list[str] = []
        failures = 0
        started = time.perf_counter()
        ticks = 0
        for _ in range(max_sends):
            result = orchestrator.tick([args.chat])
            ticks += 1
            sent.extend(result.replies)
            events.extend(result.events)
            failures += result.failures
            if failures > 0 or orchestrator.machine.state.value != "running":
                break
            if len(sent) >= max_sends:
                break
            time.sleep(interval)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        payload = {
            "ok": failures == 0 and len(sent) > 0,
            "mode": "live",
            "chat": args.chat,
            "dry_run": False,
            "max_sends": max_sends,
            "sent": sent,
            "sent_count": len(sent),
            "failures": failures,
            "ticks": ticks,
            "interval": interval,
            "state": orchestrator.machine.state.value,
            "queue_left": len(orchestrator.queue),
            "events": events,
            "recovered": len(pending),
            "next_action": explain_reason(" ".join(events)).next_action if failures else "",
            "elapsed_ms": elapsed_ms,
        }
    except (AgentFrameworkError, ConfigError) as exc:
        code = int(getattr(exc, "exit_code", 5))
        print(f"LIVE ERROR: {exc}", file=sys.stderr)
        print(f"NEXT: {explain_failure(code, str(exc)).next_action}", file=sys.stderr)
        return code
    finally:
        memory_store.close()
        databases.close()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"sent     : {payload['sent_count']}/{max_sends}  failures={payload['failures']}")
        print(f"state    : {payload['state']}  ticks={payload['ticks']}  queue={payload['queue_left']}")
        print("RESULT: OK" if payload["ok"] else "RESULT: FAIL")
    return 0 if payload["ok"] else 1
