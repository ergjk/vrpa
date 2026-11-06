"""框架统一异常体系（平台无关）。

设计目标（M0-F-02 起为框架契约，见 docs/ADR/0003-interface-stability.md）：
    1. 全项目只抛 AgentFrameworkError 家族异常，禁止裸 Exception 冒到 CLI 层；
    2. 每个异常携带 exit_code，与 docs/行动清单-V1.0.md §1.2 的退出码契约一致；
    3. to_dict() / to_audit() 供 CLI --json 与审计日志使用（上下文自动脱敏）；
    4. Interrupted 与 KeyboardInterrupt 统一 130，并标记 is_control_flow，
       表示「控制流中断」——不落半成品消息、不计入连续失败、不触发熔断。

退出码（§1.2 契约 + 框架保留码）：
    0   成功
    1   未预期内部错误（仅 InternalError 兜底使用）
    2   配置 / 参数错误          -> UsageError / ConfigError
    3   元素定位 / 环境失败      -> ElementNotVisible / TreeConfigError / WindowNotFound /
                                    WindowNotForeground / SessionSwitchFailed / CopyFailed
    4   发送三重校验失败         -> VerifyFailed
    5   LLM 调用 / 输出失败      -> LLMError
    6   数据库 / 迁移失败        -> DBError
    7   分辨率 / DPI / 窗口与 profile 不符 -> ProfileMismatch
    8   红线违规（R1/R2/R3）     -> RedlineViolation
    130 用户中断（Ctrl+C / 急停 / 接管）-> Interrupted
"""

from __future__ import annotations

import traceback
from collections.abc import Mapping
from enum import IntEnum
from typing import Any

from dsh_rpa.logging import current_trace_id, redact_mapping

__all__ = [
    "ERROR_CLASSES",
    "EXIT_CODE_MAP",
    "AgentFrameworkError",
    "ConfigError",
    "DBError",
    "ElementNotVisible",
    "ExitCode",
    "InternalError",
    "Interrupted",
    "LLMError",
    "ProfileMismatch",
    "RedlineViolation",
    "SessionSwitchFailed",
    "TreeConfigError",
    "UsageError",
    "VerifyFailed",
    "WindowNotFound",
    "WindowNotForeground",
    "exit_code_for",
    "format_exception_chain",
]


class ExitCode(IntEnum):
    """进程退出码契约（CLI 唯一真源）。"""

    OK = 0
    INTERNAL = 1
    USAGE = 2
    ELEMENT_NOT_VISIBLE = 3
    VERIFY_FAILED = 4
    LLM_ERROR = 5
    DB_ERROR = 6
    PROFILE_MISMATCH = 7
    REDLINE_VIOLATION = 8
    INTERRUPTED = 130


class AgentFrameworkError(Exception):
    """框架异常基类：子类必须声明 code 与 exit_code。"""

    code: str = "ERROR"
    exit_code: int = int(ExitCode.USAGE)
    default_hint: str | None = None
    is_control_flow: bool = False

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        context: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.message = str(message)
        self.hint = hint if hint is not None else self.default_hint
        self.context: dict[str, Any] = dict(context or {})
        self.cause = cause
        self.trace_id = current_trace_id()

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(code={self.code!r}, exit_code={self.exit_code}, "
            f"message={self.message!r}, trace_id={self.trace_id!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        """结构化输出（JSON 可序列化；字符串自动脱敏）。"""
        data: dict[str, Any] = {
            "type": type(self).__name__,
            "code": self.code,
            "exit_code": self.exit_code,
            "is_control_flow": self.is_control_flow,
            "message": self.message,
            "hint": self.hint,
            "trace_id": self.trace_id,
            "context": dict(self.context),
        }
        if self.cause is not None:
            data["cause"] = {"type": type(self.cause).__name__, "message": str(self.cause)}
        result: dict[str, Any] = redact_mapping(data)
        return result

    def to_audit(self, *, event: str = "error") -> dict[str, Any]:
        """审计日志载荷：{"event": "error", ...to_dict()}。"""
        payload = self.to_dict()
        payload["event"] = event
        return payload


class UsageError(AgentFrameworkError):
    code = "USAGE_ERROR"
    exit_code = int(ExitCode.USAGE)
    default_hint = "运行 `--help` 查看用法。"


class ConfigError(AgentFrameworkError):
    code = "CONFIG_ERROR"
    exit_code = int(ExitCode.USAGE)
    default_hint = "检查 config.yaml；运行 `selftest` 定位问题。"


class ElementNotVisible(AgentFrameworkError):
    code = "ELEMENT_NOT_VISIBLE"
    exit_code = int(ExitCode.ELEMENT_NOT_VISIBLE)
    default_hint = "确认目标窗口未被弹窗遮挡；若界面已变化，请重跑校准（calibrate）。"


class TreeConfigError(AgentFrameworkError):
    code = "TREE_CONFIG_ERROR"
    exit_code = int(ExitCode.ELEMENT_NOT_VISIBLE)
    default_hint = "检查元素树 profile 与锚点图目录是否完整。"


class WindowNotFound(AgentFrameworkError):
    code = "WINDOW_NOT_FOUND"
    exit_code = int(ExitCode.ELEMENT_NOT_VISIBLE)
    default_hint = "确认目标客户端已启动且主窗口存在（见配置中的进程名）。"


class WindowNotForeground(AgentFrameworkError):
    code = "WINDOW_NOT_FOREGROUND"
    exit_code = int(ExitCode.ELEMENT_NOT_VISIBLE)
    default_hint = "目标窗口未能切到前台；检查是否有全屏程序/远程桌面占用。"


class SessionSwitchFailed(AgentFrameworkError):
    code = "SESSION_SWITCH_FAILED"
    exit_code = int(ExitCode.ELEMENT_NOT_VISIBLE)
    default_hint = "确认目标会话名正确、搜索入口可用；切换后必须做会话校验。"


class CopyFailed(AgentFrameworkError):
    code = "COPY_FAILED"
    exit_code = int(ExitCode.ELEMENT_NOT_VISIBLE)
    default_hint = "框选未选中文本；确认消息区无遮挡、目标窗口在前台。"


class VerifyFailed(AgentFrameworkError):
    code = "VERIFY_FAILED"
    exit_code = int(ExitCode.VERIFY_FAILED)
    default_hint = "发送前校验未通过（已清空输入框）；检查焦点/输入法/窗口标题。"


class LLMError(AgentFrameworkError):
    code = "LLM_ERROR"
    exit_code = int(ExitCode.LLM_ERROR)
    default_hint = "检查 API Key / 网络 / 额度。"


class DBError(AgentFrameworkError):
    code = "DB_ERROR"
    exit_code = int(ExitCode.DB_ERROR)
    default_hint = "运行 `db-check --repair` 检查双库结构。"


class ProfileMismatch(AgentFrameworkError):
    code = "PROFILE_MISMATCH"
    exit_code = int(ExitCode.PROFILE_MISMATCH)
    default_hint = "分辨率 / DPI / 窗口几何已变化，请重跑校准（calibrate）。"


class RedlineViolation(AgentFrameworkError):
    code = "REDLINE_VIOLATION"
    exit_code = int(ExitCode.REDLINE_VIOLATION)
    default_hint = "该操作触碰红线（R1 超前开发 / R2 Git 隔离 / R3 消息流边界），已拒绝执行。"


class InternalError(AgentFrameworkError):
    """未预期内部异常兜底（仅 CLI 最外层使用）。"""

    code = "INTERNAL_ERROR"
    exit_code = int(ExitCode.INTERNAL)
    default_hint = "未预期内部错误；设置环境变量 DSH_RPA_DEBUG=1（或应用同名变量）重跑以查看堆栈。"

    @classmethod
    def from_exception(
        cls,
        exc: BaseException,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> InternalError:
        payload: dict[str, Any] = dict(context or {})
        payload.setdefault("original_type", type(exc).__name__)
        payload.setdefault("original_module", type(exc).__module__)
        return cls(f"未预期异常：{exc!r}", context=payload, cause=exc)


class Interrupted(AgentFrameworkError):
    """控制流中断（急停 / 接管 / Ctrl+C）：不落半成品、不计失败、不触发熔断。"""

    code = "INTERRUPTED"
    exit_code = int(ExitCode.INTERRUPTED)
    default_hint = "已安全中断，未写入半成品消息。"
    is_control_flow = True


ERROR_CLASSES: tuple[type[AgentFrameworkError], ...] = (
    UsageError,
    ConfigError,
    ElementNotVisible,
    TreeConfigError,
    WindowNotFound,
    WindowNotForeground,
    SessionSwitchFailed,
    CopyFailed,
    VerifyFailed,
    LLMError,
    DBError,
    ProfileMismatch,
    RedlineViolation,
    InternalError,
    Interrupted,
)

EXIT_CODE_MAP: dict[type[AgentFrameworkError], int] = {error_cls: error_cls.exit_code for error_cls in ERROR_CLASSES}


def exit_code_for(exc: BaseException) -> int:
    """任意异常 -> 进程退出码（框架异常用自身码，否则 1 = 内部错误）。"""
    if isinstance(exc, AgentFrameworkError):
        return exc.exit_code
    return int(ExitCode.INTERNAL)


def format_exception_chain(exc: BaseException) -> str:
    """完整堆栈文本（仅 DEBUG 模式打印，避免污染正常 stderr）。"""
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
