"""VRPA-WeChat-Agent V1.0 —— 进程入口与 CLI 骨架。

里程碑：M0-01（骨架）、M0-02（selftest 接线）、M0-04（统一异常 -> 退出码）
职责：
    1. 子命令注册表（COMMANDS）与分发；
    2. 退出码契约（ExitCode，真源在 core/errors.py）——后续所有 DoD 都靠它判定；
    3. 全局异常兜底：AgentFrameworkError -> 自身 exit_code，KeyboardInterrupt / Interrupted -> 130，
       其他异常 -> InternalError(1)，均不打印裸堆栈（DEBUG 模式除外）。

本模块顶层只依赖标准库 + vrpa.errors；各子命令的第三方依赖一律在 handler 内延迟导入，
保证 `--help` / `--version` 在纯净环境（未装 PyYAML / RPA 依赖）也能运行。
"""

from __future__ import annotations

import os
import sys
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TextIO

from vrpa.errors import (
    AgentFrameworkError,
    ExitCode,
    InternalError,
    Interrupted,
)
from wechat_agent import __version__

__all__ = ["ExitCode", "Command", "COMMANDS", "register_handler", "print_help", "dispatch", "main"]


Handler = Callable[[Sequence[str]], int]


@dataclass(frozen=True)
class Command:
    """一条 CLI 子命令的元数据（handler=None 表示尚未交付）。"""

    name: str
    summary: str
    milestone: str
    unimplemented_exit: int = int(ExitCode.USAGE)
    handler: Handler | None = None


_COMMAND_SPECS = (
    ("selftest", "配置/日志/双库/依赖自检", "M0-02", int(ExitCode.USAGE)),
    ("doctor", "环境体检（依赖/DPI/多屏/窗口/写权限）", "M0-07", int(ExitCode.USAGE)),
    ("validate-tree", "校验假 UIA 树 profile 与锚点图", "M1-05", int(ExitCode.USAGE)),
    ("calibrate", "假 UIA 树校准向导（框选元素 + 锚点图 + 回验）", "M1-04", int(ExitCode.USAGE)),
    ("locate", "定位单个界面元素，打印坐标与匹配分数", "M1-03", int(ExitCode.ELEMENT_NOT_VISIBLE)),
    ("probe", "打印原始剪贴板文本（不入库、不回复）", "M2-05", int(ExitCode.USAGE)),
    ("replay", "离线回放 parser / dedup / flow 场景", "M2-04", int(ExitCode.USAGE)),
    ("db-check", "双库结构与迁移检查", "M0-06", int(ExitCode.USAGE)),
    ("llm-ping", "LLM 连通性检查 / 单轮问答", "M5-05", int(ExitCode.USAGE)),
    ("run", "主进程（真实 / --dry-run / --fake / --simulate）", "M4-06", int(ExitCode.USAGE)),
    ("send", "控制台接管发送（等价 /say）", "M6-01", int(ExitCode.USAGE)),
    ("plugin", "插件管理（list / run）", "M6-04", int(ExitCode.USAGE)),
    ("report", "浸泡/验收报告判定", "M6-05", int(ExitCode.USAGE)),
)

COMMANDS: dict[str, Command] = {
    name: Command(name, summary, milestone, exit_code) for name, summary, milestone, exit_code in _COMMAND_SPECS
}


def register_handler(name: str, handler: Handler) -> None:
    """为已注册子命令挂上实现（里程碑推进时调用；未知子命令直接报错，防止手误）。"""
    if name not in COMMANDS:
        raise KeyError(f"未注册的子命令：{name}")
    current = COMMANDS[name]
    COMMANDS[name] = Command(
        name=current.name,
        summary=current.summary,
        milestone=current.milestone,
        unimplemented_exit=current.unimplemented_exit,
        handler=handler,
    )


def print_help(stream: TextIO | None = None) -> None:
    """打印帮助：子命令表 + 退出码表 + 红线提醒。

    stream=None 时在调用瞬间解析 sys.stdout（默认参数会在 import 时绑定，
    导致 pytest capsys / 输出重定向不可捕获）。
    """
    target = sys.stdout if stream is None else stream
    lines = [
        f"VRPA-WeChat-Agent v{__version__} —— 微信 RPA 智能对话代理（Vision-RPA Edition）",
        "",
        "用法：",
        "    python -m wechat_agent <command> [options]",
        "    python -m wechat_agent --help | --version",
        "",
        "子命令（[已交付] 表示已实现，[规划中] 表示按里程碑交付）：",
    ]
    for cmd in COMMANDS.values():
        mark = "[已交付]" if cmd.handler is not None else "[规划中]"
        lines.append(f"  {mark} {cmd.name:<13} {cmd.summary}（{cmd.milestone}）")
    lines += [
        "",
        "退出码（core/errors.py 为唯一真源）：",
        "    0 成功 | 1 内部错误 | 2 配置/参数错误 | 3 元素定位失败 | 4 发送校验失败",
        "    5 LLM 失败 | 6 数据库失败 | 7 分辨率/DPI 不符 | 8 红线违规 | 130 用户中断",
        "",
        "红线（不得违反）：",
        "    R1 只做 V1.0；V1.1/V1.2 仅 core/interfaces.py 允许空接口",
        "    R2 Git 操作由主控官监督、Agent 执行（破坏性操作需明确指令）",
        "    R3 假 UIA 树只服务操作界面；消息流只走「框选 + Ctrl+C 剪贴板」",
        "",
        "文档：README.md / docs/技术方案-V1.0.md / docs/行动清单-V1.0.md",
    ]
    print("\n".join(lines), file=target)


def _cmd_selftest(argv: Sequence[str]) -> int:
    """M0-02：配置系统与数据目录自检。"""
    from wechat_agent.core.config import run_selftest

    return run_selftest(argv)


def _cmd_db_check(argv: Sequence[str]) -> int:
    """M0-06：双库结构与迁移检查（--schema / --repair / --json）。"""
    from wechat_agent.tools.db_check import run_db_check

    return run_db_check(argv)


def dispatch(argv: Sequence[str]) -> ExitCode:
    """按 argv 分发子命令；骨架阶段未接线的子命令返回其桩退出码。"""
    args = list(argv)

    if not args or args[0] in {"-h", "--help", "help"}:
        print_help()
        return ExitCode.OK

    if args[0] in {"-V", "--version", "version"}:
        print(f"wechat_agent {__version__}")
        return ExitCode.OK

    name, rest = args[0], args[1:]
    cmd = COMMANDS.get(name)
    if cmd is None:
        print(f"未知子命令：{name}", file=sys.stderr)
        print("运行 `python -m wechat_agent --help` 查看可用子命令。", file=sys.stderr)
        return ExitCode.USAGE

    if cmd.handler is None:
        print(f"[{cmd.name}] 尚未实现（计划 {cmd.milestone} 交付）。", file=sys.stderr)
        return ExitCode(cmd.unimplemented_exit)

    result = cmd.handler(rest)
    return result if isinstance(result, ExitCode) else ExitCode(result)


def _debug_enabled() -> bool:
    debug = os.environ.get("VRPA_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
    legacy = os.environ.get("WECHAT_AGENT_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
    return debug or legacy


def _print_failure(exc: AgentFrameworkError) -> None:
    """统一错误出口：code + message + hint（DEBUG 时另打堆栈）。"""
    print(f"[{exc.code}] {exc.message}", file=sys.stderr)
    if exc.hint:
        print(f"提示：{exc.hint}", file=sys.stderr)
    if _debug_enabled():
        cause = exc.cause if isinstance(exc, InternalError) and exc.cause is not None else exc
        print("--- traceback ---", file=sys.stderr)
        print("".join(traceback.format_exception(type(cause), cause, cause.__traceback__)), file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """进程主入口；把异常统一映射为退出码，绝不抛裸堆栈。"""
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        return int(dispatch(args))
    except KeyboardInterrupt:
        print("\n已中断（Ctrl+C），正在退出……", file=sys.stderr)
        return int(ExitCode.INTERRUPTED)
    except Interrupted as exc:
        print(f"\n已中断（{exc.message}），正在退出……", file=sys.stderr)
        return int(ExitCode.INTERRUPTED)
    except AgentFrameworkError as exc:
        _print_failure(exc)
        return int(exc.exit_code)
    except Exception as exc:  # noqa: BLE001 - 仅最外层兜底，避免裸堆栈
        internal = InternalError.from_exception(exc)
        _print_failure(internal)
        return int(internal.exit_code)


register_handler("selftest", _cmd_selftest)
register_handler("db-check", _cmd_db_check)


if __name__ == "__main__":
    raise SystemExit(main())
