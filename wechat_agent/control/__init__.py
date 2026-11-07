"""控制层：CLI 控制台、GUI 与未来远程控制共用的接口。"""

from wechat_agent.control.session import (
    ControlAction,
    ControlDenied,
    ControlRequest,
    ControlResponse,
    ControlStatus,
    ControlTransport,
    LocalControlTransport,
    RemoteControlPolicy,
    SessionController,
    authorize,
    status_summary,
)

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
    "authorize",
    "status_summary",
]
