"""控制层接口骨架（V1.0 不监听网络；远程控制 V1.1 实现）。

安全定位：
    - V1.0 只提供进程内 ``LocalControlTransport``；
    - ``RemoteControlPolicy`` 预置“默认拒绝、只允许状态/暂停/恢复/停止”；
    - 远程发送默认禁止，必须显式开启 + 二次确认；
    - 不在 URL/日志中放置 token，token 比较使用常量时间。
"""

from __future__ import annotations

import hmac
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

__all__ = [
    "ControlAction",
    "ControlDenied",
    "ControlRequest",
    "ControlResponse",
    "ControlStatus",
    "ControlTransport",
    "LocalControlTransport",
    "RemoteControlPolicy",
    "SessionController",
    "status_summary",
]


class ControlAction(StrEnum):
    STATUS = "status"
    START_DRY_RUN = "start_dry_run"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    SEND_ONCE = "send_once"


class ControlDenied(Exception):
    """控制请求被安全策略拒绝（不触达运行时）。"""


@dataclass(frozen=True)
class ControlStatus:
    """可远程展示的只读状态（不含消息内容/密钥）。"""

    state: str
    dry_run: bool
    allow_real_send: bool
    chat: str = ""
    queue_left: int = 0
    sent_count: int = 0
    last_error: str = ""
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass(frozen=True)
class ControlRequest:
    action: ControlAction
    token: str = ""
    confirmed: bool = False
    chat: str = ""
    text: str = ""


@dataclass(frozen=True)
class ControlResponse:
    ok: bool
    detail: str = ""
    status: ControlStatus | None = None


@dataclass(frozen=True)
class RemoteControlPolicy:
    """V1.1 远程控制策略；V1.0 不启动任何监听。"""

    enabled: bool = False
    bind_host: str = "127.0.0.1"
    require_tls: bool = True
    token: str = ""
    allowed_actions: frozenset[ControlAction] = frozenset(
        {ControlAction.STATUS, ControlAction.PAUSE, ControlAction.RESUME, ControlAction.STOP}
    )
    allow_send: bool = False
    allowed_chats: frozenset[str] = frozenset()
    allow_remote_start: bool = False
    max_requests_per_minute: int = 30


class SessionController(Protocol):
    """UI/CLI/未来远程共用的控制器接口。"""

    def status(self) -> ControlStatus: ...

    def start_dry_run(self, chat: str) -> ControlResponse: ...

    def pause(self) -> ControlResponse: ...

    def resume(self) -> ControlResponse: ...

    def stop(self) -> ControlResponse: ...

    def send_once(self, chat: str, text: str, *, confirmed: bool = False) -> ControlResponse: ...


class ControlTransport(Protocol):
    """控制传输层；V1.0 只有进程内实现，V1.1 可加 HTTP/命名管道。"""

    def request(self, request: ControlRequest) -> ControlResponse: ...


def authorize(request: ControlRequest, policy: RemoteControlPolicy) -> None:
    """远程请求授权；任何不确定都拒绝。"""
    if not policy.enabled:
        raise ControlDenied("远程控制未启用")
    if request.action not in policy.allowed_actions:
        raise ControlDenied(f"动作 {request.action.value!r} 不在允许列表")
    if request.action in {ControlAction.SEND_ONCE} and not policy.allow_send:
        raise ControlDenied("远程发送默认禁止")
    if request.action is ControlAction.SEND_ONCE and request.chat not in policy.allowed_chats:
        raise ControlDenied(f"会话 {request.chat!r} 不在远程发送允许列表")
    if request.action in {ControlAction.START_DRY_RUN} and not policy.allow_remote_start:
        raise ControlDenied("远程启动默认禁止")
    if not policy.token:
        raise ControlDenied("远程控制缺少 token 配置")
    if not request.token or not hmac.compare_digest(request.token, policy.token):
        raise ControlDenied("token 校验失败")
    if request.action is ControlAction.SEND_ONCE and not request.confirmed:
        raise ControlDenied("远程发送缺少二次确认")


class LocalControlTransport:
    """进程内传输：直接调用 SessionController，不监听端口。"""

    def __init__(
        self,
        controller: SessionController,
        *,
        policy: RemoteControlPolicy | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._controller = controller
        self._policy = policy
        self._sleep = sleep

    def request(self, request: ControlRequest) -> ControlResponse:
        if self._policy is not None:
            authorize(request, self._policy)
        if request.action is ControlAction.STATUS:
            return ControlResponse(ok=True, status=self._controller.status())
        if request.action is ControlAction.START_DRY_RUN:
            return self._controller.start_dry_run(request.chat)
        if request.action is ControlAction.PAUSE:
            return self._controller.pause()
        if request.action is ControlAction.RESUME:
            return self._controller.resume()
        if request.action is ControlAction.STOP:
            return self._controller.stop()
        if request.action is ControlAction.SEND_ONCE:
            return self._controller.send_once(request.chat, request.text, confirmed=request.confirmed)
        raise ControlDenied(f"未知动作：{request.action!r}")


def status_summary(status: ControlStatus) -> dict[str, object]:
    """把状态转为可审计的纯量字典（不含消息内容/密钥）。"""
    return {
        "state": status.state,
        "dry_run": status.dry_run,
        "allow_real_send": status.allow_real_send,
        "chat": status.chat,
        "queue_left": status.queue_left,
        "sent_count": status.sent_count,
        "last_error": status.last_error,
        "updated_at": status.updated_at,
    }
