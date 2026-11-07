"""编排循环（M4-04/06，平台无关）：轮询 -> 采集 -> 去重入库 -> 排队 -> 拟人延迟 -> 发送。

纪律：
    - 所有 UI / 键鼠 / LLM 依赖均通过端口注入；测试与 ``--simulate`` 全用 Fake；
    - ``dry_run`` 由执行器决定（FakeExecutor 恒为 dry_run），循环本身不发真实输入；
    - 控制通道（暂停/恢复/停止/接管）在每次动作前优先处理，拟人等待可被立即打断。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Protocol

from vrpa.errors import (
    CopyFailed,
    ElementNotVisible,
    ProfileMismatch,
    SessionSwitchFailed,
    WindowNotForeground,
    WindowNotFound,
)
from vrpa.ports import Brain, Executor, IncomingMessage, Message
from vrpa.scheduling.delay import Humanizer
from vrpa.scheduling.machine import CircuitBreaker, RunState, RunStateMachine
from vrpa.scheduling.queue import MessageQueue, QueuedMessage
from vrpa.scheduling.scheduler import Scheduler

__all__ = ["ControlChannel", "ControlCommand", "Orchestrator", "RunReport", "TickResult"]


class IngestOutcome(Protocol):
    """pipeline.ingest 的返回结构（应用层实现）。"""

    inserted: Any
    queued: Any
    duplicates: int


class PipelinePort(Protocol):
    """入库闭环协议（vrpa 不依赖具体应用实现）。"""

    def ingest(self, chat: str, incoming: Any) -> IngestOutcome: ...

    def writeback(self, chat: str, text: str) -> int: ...


RECOVERABLE_ERRORS = (
    CopyFailed,
    SessionSwitchFailed,
    ElementNotVisible,
    WindowNotFound,
    WindowNotForeground,
    ProfileMismatch,
)


@dataclass(frozen=True)
class ControlCommand:
    """控制通道命令（M4-06）。"""

    action: str  # pause | resume | stop | takeover
    chat: str | None = None
    text: str | None = None
    reason: str = ""


class ControlChannel:
    """线程安全控制通道：命令队列 + 打断事件。"""

    def __init__(self) -> None:
        self._commands: deque[ControlCommand] = deque()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._interrupt_event = threading.Event()

    def submit(self, command: ControlCommand) -> None:
        with self._lock:
            self._commands.append(command)

    def drain(self) -> tuple[ControlCommand, ...]:
        with self._lock:
            commands = tuple(self._commands)
            self._commands.clear()
            return commands

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    @property
    def interrupt_event(self) -> threading.Event:
        return self._interrupt_event

    def pause(self) -> None:
        self._interrupt_event.set()

    def resume(self) -> None:
        self._interrupt_event.clear()

    def request_stop(self) -> None:
        self._interrupt_event.set()
        self._stop_event.set()

    @property
    def stop_requested(self) -> bool:
        return self._stop_event.is_set()


@dataclass(frozen=True)
class TickResult:
    """单次 tick 结果（可 JSON 化）。"""

    tick: int
    state: str
    captured: int = 0
    ingested: int = 0
    duplicates: int = 0
    queued: int = 0
    replies: tuple[str, ...] = ()
    failures: int = 0
    breaker: str = "closed"
    events: tuple[str, ...] = ()
    phase_ms: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class RunReport:
    """一次编排运行报告。"""

    ticks: int
    state: str
    replies: tuple[str, ...] = ()
    sent: tuple[tuple[str, str], ...] = ()
    duplicates: int = 0
    failures: int = 0
    events: tuple[str, ...] = ()
    breaker: str = "closed"
    queue_left: int = 0
    tick_results: tuple[TickResult, ...] = ()


class Orchestrator:
    """轮询编排器（单线程 tick，控制通道可跨线程投递命令）。"""

    def __init__(
        self,
        config: object,
        *,
        perception: object,
        parser: object,
        pipeline: PipelinePort,
        brain: Brain,
        executor: Executor,
        humanizer: Humanizer,
        scheduler: Scheduler,
        queue: MessageQueue | None = None,
        machine: RunStateMachine | None = None,
        breaker: CircuitBreaker | None = None,
        control: ControlChannel | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_replies_per_tick: int = 1,
        memory_job: Any | None = None,
        pending_store: Any | None = None,
    ) -> None:
        self._config = config
        self._perception = perception
        self._parser = parser
        self._pipeline = pipeline
        self._brain = brain
        self._executor = executor
        self._humanizer = humanizer
        self._scheduler = scheduler
        self._queue = queue if queue is not None else MessageQueue()
        self._machine = machine or RunStateMachine()
        self._breaker = breaker or CircuitBreaker()
        self._control = control or ControlChannel()
        self._sleep = sleep
        self._max_replies = max(1, max_replies_per_tick)
        self._memory_job = memory_job
        self._pending_store = pending_store
        self._tick = 0
        self._chat_index = 0
        self._events: list[str] = []

    # ------------------------------------------------------------ 公开
    @property
    def machine(self) -> RunStateMachine:
        return self._machine

    @property
    def breaker(self) -> CircuitBreaker:
        return self._breaker

    @property
    def queue(self) -> MessageQueue:
        return self._queue

    @property
    def control(self) -> ControlChannel:
        return self._control

    def start(self) -> None:
        if self._machine.state is RunState.IDLE:
            self._machine.start()

    def submit(self, command: ControlCommand) -> None:
        self._control.submit(command)

    def run(self, chats: Sequence[str], *, max_ticks: int = 10) -> RunReport:
        self.start()
        tick_results: list[TickResult] = []
        replies: list[str] = []
        sent: list[tuple[str, str]] = []
        duplicates = 0
        failures = 0
        for _ in range(max_ticks):
            result = self.tick(chats)
            tick_results.append(result)
            replies.extend(result.replies)
            duplicates += result.duplicates
            failures += result.failures
            if result.replies:
                sent.extend((chat, reply) for chat in [self._last_chat] for reply in result.replies)
            if self._machine.state is RunState.STOPPED or self._control.stop_requested:
                break
        events = tuple(self._events)
        return RunReport(
            ticks=len(tick_results),
            state=self._machine.state.value,
            replies=tuple(replies),
            sent=tuple(sent),
            duplicates=duplicates,
            failures=failures,
            events=events,
            breaker=self._breaker.state.value,
            queue_left=len(self._queue),
            tick_results=tuple(tick_results),
        )

    def tick(self, chats: Sequence[str]) -> TickResult:
        self._tick += 1
        events: list[str] = []
        self._apply_control(events)
        if self._machine.state is not RunState.RUNNING:
            return self._result(events)

        chat = self._next_chat(chats, events)
        if chat is None:
            return self._result(events)
        self._last_chat = chat

        captured = ingested = duplicates = 0
        failures = 0
        phase: dict[str, float] = {}
        try:
            started = time.perf_counter()
            raw = self._perception.capture(chat)  # type: ignore[attr-defined]
            phase["capture_ms"] = round((time.perf_counter() - started) * 1000, 1)
            started = time.perf_counter()
            incoming = self._parser.parse(raw) if hasattr(self._parser, "parse") else ()
            ingest = self._pipeline.ingest(chat, incoming)
            phase["ingest_ms"] = round((time.perf_counter() - started) * 1000, 1)
            captured = len(incoming)
            ingested = len(ingest.inserted)
            duplicates = ingest.duplicates
            for record in ingest.queued:
                if self._pending_store is not None:
                    with suppress(Exception):
                        self._pending_store.add_pending_reply(chat, record.id, record.content)
                self._queue.push(
                    QueuedMessage(
                        chat=chat,
                        content=record.content,
                        message_id=record.id,
                        priority=5,
                    )
                )
            events.append(f"ingest:{chat}:{ingested}")
            if self._memory_job is not None and ingest.inserted:
                try:
                    self._memory_job.enqueue(
                        chat,
                        [
                            Message(
                                direction=str(record.direction),
                                content=str(record.content),
                                role=str(record.role or "user"),
                                sender=record.sender,
                                ts=record.ts,
                                source=str(record.source),
                                status=str(record.status),
                            )
                            for record in ingest.inserted
                        ],
                        dedupe_key=f"{chat}:{ingest.inserted[-1].id}",
                    )
                    events.append("memory_queued")
                except Exception as exc:  # noqa: BLE001 - 提炼不可阻塞主链路
                    events.append(f"memory_enqueue_failed:{type(exc).__name__}")
        except RECOVERABLE_ERRORS as exc:
            failures += 1
            self._breaker.record_failure()
            events.append(f"capture_failed:{type(exc).__name__}")
            if self._breaker.state.value == "open":
                self._machine.pause(reason="circuit_open")
                events.append("breaker_open->paused")

        replies: list[str] = []
        if self._machine.state is RunState.RUNNING:
            started = time.perf_counter()
            replies = self._drain_replies(events, failures)
            phase["reply_ms"] = round((time.perf_counter() - started) * 1000, 1)
            failures += sum(1 for event in events if event.startswith("send_failed:"))
        return self._result(
            events,
            captured=captured,
            ingested=ingested,
            duplicates=duplicates,
            replies=tuple(replies),
            failures=failures,
            phase_ms=phase,
        )

    # ------------------------------------------------------------ 内部
    def _result(
        self,
        events: list[str],
        *,
        captured: int = 0,
        ingested: int = 0,
        duplicates: int = 0,
        replies: tuple[str, ...] = (),
        failures: int = 0,
        phase_ms: dict[str, float] | None = None,
    ) -> TickResult:
        return TickResult(
            tick=self._tick,
            state=self._machine.state.value,
            captured=captured,
            ingested=ingested,
            duplicates=duplicates,
            queued=len(self._queue),
            replies=replies,
            failures=failures,
            breaker=self._breaker.state.value,
            events=tuple(events),
            phase_ms=phase_ms or {},
        )

    def _apply_control(self, events: list[str]) -> None:
        for command in self._control.drain():
            if command.action == "pause":
                self._control.pause()
                if self._machine.state is RunState.RUNNING:
                    self._machine.pause(reason=command.reason or "manual_pause")
                    events.append("pause")
            elif command.action == "resume":
                self._control.resume()
                if self._machine.state is RunState.PAUSED:
                    self._machine.resume()
                    events.append("resume")
            elif command.action == "stop":
                self._control.request_stop()
                with suppress(Exception):
                    self._machine.stop()
                events.append("stop")
            elif command.action == "takeover" and command.chat and command.text:
                self._handle_takeover(command, events)

    def _handle_takeover(self, command: ControlCommand, events: list[str]) -> None:
        chat, text = command.chat, command.text
        if not chat or not text:
            events.append("takeover_ignored")
            return
        try:
            outcome = self._executor.send(chat, text, trigger="override")
        except Exception as exc:  # noqa: BLE001 - 接管失败不阻塞主循环
            events.append(f"takeover_failed:{type(exc).__name__}")
            return
        self._pipeline.writeback(chat, text)
        events.append("takeover")
        self._events.append(f"takeover:{command.chat}:{outcome.stage}")

    def _drain_replies(self, events: list[str], failures: int) -> list[str]:
        replies: list[str] = []
        for _ in range(self._max_replies):
            if not self._breaker.allow():
                events.append("breaker_blocked")
                break
            item = self._queue.pop()
            if item is None:
                break
            decision = self._scheduler.check(item.chat)
            if not decision.allowed:
                events.append(f"scheduler_blocked:{decision.reason}")
                self._queue.push(item)
                break
            try:
                result = self._brain.generate(
                    [{"role": "user", "content": item.content}],
                    session=item.chat,
                )
                if not self._humanizer.human_send(result.text, cancel=self._control.interrupt_event):
                    events.append("send_interrupted")
                    self._queue.push(item)
                    break
                outcome = self._executor.send(item.chat, result.text, trigger="auto")
                if not outcome.ok:
                    raise RuntimeError(f"发送失败：{outcome.stage}")
                self._pipeline.writeback(item.chat, result.text)
                if self._pending_store is not None and item.message_id is not None:
                    with suppress(Exception):
                        self._pending_store.complete_pending_reply(item.chat, item.message_id)
                self._scheduler.note_send(item.chat)
                self._breaker.record_success()
                replies.append(result.text)
                self._events.append(f"reply:{item.chat}:{result.text}")
            except RECOVERABLE_ERRORS as exc:
                failures += 1
                self._breaker.record_failure()
                events.append(f"send_failed:{type(exc).__name__}")
                self._queue.push(item)
                if self._breaker.state.value == "open":
                    self._machine.pause(reason="circuit_open")
                    events.append("breaker_open->paused")
                break
            except Exception as exc:  # noqa: BLE001 - LLM 等失败同样熔断
                failures += 1
                self._breaker.record_failure()
                events.append(f"reply_failed:{type(exc).__name__}:{str(exc)[:160]}")
                self._queue.push(item)
                break
        return replies

    def _next_chat(self, chats: Sequence[str], events: list[str]) -> str | None:
        if not chats:
            return None
        chat = chats[self._chat_index % len(chats)]
        self._chat_index += 1
        return chat


_ = IncomingMessage
