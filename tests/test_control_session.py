"""控制层接口与远程授权策略测试（不启动网络）。"""

from __future__ import annotations

import pytest

from wechat_agent.control.session import (
    ControlAction,
    ControlDenied,
    ControlRequest,
    ControlResponse,
    ControlStatus,
    LocalControlTransport,
    RemoteControlPolicy,
    authorize,
    status_summary,
)

STATUS = ControlStatus(state="running", dry_run=True, allow_real_send=False, chat="王衢665", queue_left=2)


class _FakeController:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def status(self) -> ControlStatus:
        self.calls.append("status")
        return STATUS

    def start_dry_run(self, chat: str) -> ControlResponse:
        self.calls.append(f"dry:{chat}")
        return ControlResponse(ok=True, status=STATUS)

    def pause(self) -> ControlResponse:
        self.calls.append("pause")
        return ControlResponse(ok=True)

    def resume(self) -> ControlResponse:
        self.calls.append("resume")
        return ControlResponse(ok=True)

    def stop(self) -> ControlResponse:
        self.calls.append("stop")
        return ControlResponse(ok=True)

    def send_once(self, chat: str, text: str, *, confirmed: bool = False) -> ControlResponse:
        self.calls.append(f"send:{chat}:{confirmed}")
        return ControlResponse(ok=True)


def _policy(**overrides: object) -> RemoteControlPolicy:
    data: dict[str, object] = {"enabled": True, "token": "secret-token"}
    data.update(overrides)
    return RemoteControlPolicy(**data)  # type: ignore[arg-type]


def test_remote_disabled_denies_everything() -> None:
    with pytest.raises(ControlDenied, match="未启用"):
        authorize(ControlRequest(ControlAction.STATUS, token="secret-token"), RemoteControlPolicy())


def test_remote_requires_correct_token() -> None:
    policy = _policy()
    with pytest.raises(ControlDenied, match="token"):
        authorize(ControlRequest(ControlAction.STATUS, token="wrong"), policy)
    authorize(ControlRequest(ControlAction.STATUS, token="secret-token"), policy)


def test_remote_send_disabled_by_default() -> None:
    with pytest.raises(ControlDenied, match="远程发送默认禁止"):
        authorize(
            ControlRequest(ControlAction.SEND_ONCE, token="secret-token", confirmed=True),
            _policy(allowed_actions=frozenset({ControlAction.SEND_ONCE})),
        )


def test_remote_send_requires_confirmation_and_allowlist() -> None:
    policy = _policy(
        allow_send=True,
        allowed_chats=frozenset({"王衢665"}),
        allowed_actions=frozenset({ControlAction.STATUS, ControlAction.SEND_ONCE}),
    )
    with pytest.raises(ControlDenied, match="二次确认"):
        authorize(ControlRequest(ControlAction.SEND_ONCE, token="secret-token", chat="王衢665"), policy)
    authorize(ControlRequest(ControlAction.SEND_ONCE, token="secret-token", chat="王衢665", confirmed=True), policy)


def test_remote_start_disabled_by_default() -> None:
    with pytest.raises(ControlDenied, match="远程启动默认禁止"):
        authorize(
            ControlRequest(ControlAction.START_DRY_RUN, token="secret-token"),
            _policy(allowed_actions=frozenset({ControlAction.START_DRY_RUN})),
        )


def test_local_transport_dispatch() -> None:
    controller = _FakeController()
    transport = LocalControlTransport(controller)
    assert transport.request(ControlRequest(ControlAction.STATUS)).status == STATUS
    assert transport.request(ControlRequest(ControlAction.PAUSE)).ok
    assert transport.request(ControlRequest(ControlAction.RESUME)).ok
    assert transport.request(ControlRequest(ControlAction.STOP)).ok
    assert transport.request(ControlRequest(ControlAction.START_DRY_RUN, chat="王衢665")).ok
    assert controller.calls == ["status", "pause", "resume", "stop", "dry:王衢665"]


def test_local_transport_enforces_policy() -> None:
    controller = _FakeController()
    transport = LocalControlTransport(controller, policy=_policy())
    with pytest.raises(ControlDenied, match="token"):
        transport.request(ControlRequest(ControlAction.STATUS, token="wrong"))
    assert controller.calls == []


def test_status_summary_has_no_secrets_or_content() -> None:
    summary = status_summary(STATUS)
    assert summary["chat"] == "王衢665"
    assert "token" not in summary
    assert "text" not in summary
