"""控制台完整指令集 + NLU 路由（M6-02）。

安全：``/say`` 默认走 dry_run 执行器；真实发送必须 executor 显式授权。
"""

from __future__ import annotations

import shlex
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from vrpa.scheduling.loop import ControlChannel, ControlCommand

__all__ = ["CommandRouter", "ConsoleReply"]

_HELP = (
    "可用指令：\n"
    "  /help                     帮助\n"
    "  /status                   运行状态\n"
    "  /pause | /resume | /stop  暂停 / 恢复 / 停止\n"
    "  /say <会话> <内容>        发送（dry_run 默认，真实需授权）\n"
    "  /takeover <会话> <内容>   人工接管（控制通道）\n"
    "  /knowledge <子命令>       list | reload | add\n"
    "  /plugin list              插件列表\n"
    "  /quit                     退出控制台\n"
    "也支持自然语言：暂停 / 恢复 / 状态 / 发送给张三：你好 / 接管张三：你好"
)


@dataclass(frozen=True)
class ConsoleReply:
    text: str
    ok: bool = True
    should_exit: bool = False


class CommandRouter:
    """斜杠指令 + 自然语言路由。"""

    def __init__(
        self,
        *,
        executor: object | None = None,
        control: ControlChannel | None = None,
        knowledge: object | None = None,
        plugins: object | None = None,
        status_provider: Callable[[], Mapping[str, object]] | None = None,
    ) -> None:
        self._executor = executor
        self._control = control
        self._knowledge = knowledge
        self._plugins = plugins
        self._status_provider = status_provider

    def dispatch(self, line: str) -> ConsoleReply:
        text = line.strip()
        if not text:
            return ConsoleReply("请输入指令（/help 查看用法）", ok=False)
        if not text.startswith("/"):
            routed = self.route_natural(text)
            if routed is None:
                return ConsoleReply("未识别指令；输入 /help 查看用法", ok=False)
            return self._dispatch_command(routed)
        return self._dispatch_command(text)

    # ------------------------------------------------------------ NLU
    def route_natural(self, text: str) -> str | None:
        normalized = text.strip().rstrip("。！!")
        simple = {
            "暂停": "/pause",
            "暂停一下": "/pause",
            "停一下": "/pause",
            "继续": "/resume",
            "恢复": "/resume",
            "继续运行": "/resume",
            "状态": "/status",
            "现状": "/status",
            "运行状态": "/status",
            "怎么样了": "/status",
            "帮助": "/help",
            "退出": "/quit",
            "关闭": "/quit",
            "知识列表": "/knowledge list",
            "插件列表": "/plugin list",
        }
        if normalized in simple:
            return simple[normalized]
        if normalized in {"停止", "停止运行", "结束"}:
            return "/stop"
        for prefix, command in (("发送给", "say"), ("接管", "takeover")):
            if normalized.startswith(prefix) and "：" in normalized:
                chat, _, content = normalized[len(prefix) :].partition("：")
                if chat.strip() and content.strip():
                    return f"/{command} {chat.strip()} {content.strip()}"
            if normalized.startswith(prefix) and ":" in normalized:
                chat, _, content = normalized[len(prefix) :].partition(":")
                if chat.strip() and content.strip():
                    return f"/{command} {chat.strip()} {content.strip()}"
        return None

    # ------------------------------------------------------------ 指令
    def _dispatch_command(self, line: str) -> ConsoleReply:
        try:
            parts = shlex.split(line)
        except ValueError:
            return ConsoleReply("指令解析失败（引号不匹配）", ok=False)
        if not parts:
            return ConsoleReply("空指令", ok=False)
        command = parts[0].lower()
        args = parts[1:]
        if command in {"/help", "help"}:
            return ConsoleReply(_HELP)
        if command == "/quit":
            return ConsoleReply("控制台退出", should_exit=True)
        if command == "/status":
            return ConsoleReply(self._status_text())
        if command in {"/pause", "/resume", "/stop"}:
            return self._control_command(command)
        if command == "/say":
            return self._say(args)
        if command == "/takeover":
            return self._takeover(args)
        if command == "/knowledge":
            if self._knowledge is None:
                return ConsoleReply("知识控制台未接入", ok=False)
            return ConsoleReply(str(self._knowledge.handle("/knowledge " + " ".join(args))))
        if command == "/plugin":
            if self._plugins is None:
                return ConsoleReply("插件管理器未接入", ok=False)
            metas = self._plugins.plugins()
            return ConsoleReply("插件：" + (", ".join(f"{meta.name}@{meta.version}" for meta in metas) or "（无）"))
        return ConsoleReply(f"未知指令：{parts[0]}（/help 查看用法）", ok=False)

    def _control_command(self, command: str) -> ConsoleReply:
        if self._control is None:
            return ConsoleReply("控制通道未接入", ok=False)
        action = command.lstrip("/")
        self._control.submit(ControlCommand(action=action))
        return ConsoleReply(f"已提交：{action}")

    def _say(self, args: list[str]) -> ConsoleReply:
        if self._executor is None:
            return ConsoleReply("执行器未接入", ok=False)
        if len(args) < 2:
            return ConsoleReply("用法：/say <会话> <内容>", ok=False)
        chat, content = args[0], " ".join(args[1:])
        outcome = self._executor.send(chat, content, trigger="console")  # type: ignore[attr-defined]
        detail = getattr(outcome, "stage", "")
        return ConsoleReply(f"发送结果：{detail}")

    def _takeover(self, args: list[str]) -> ConsoleReply:
        if self._control is None:
            return ConsoleReply("控制通道未接入", ok=False)
        if len(args) < 2:
            return ConsoleReply("用法：/takeover <会话> <内容>", ok=False)
        self._control.submit(ControlCommand(action="takeover", chat=args[0], text=" ".join(args[1:])))
        return ConsoleReply("已提交接管")

    def _status_text(self) -> str:
        if self._status_provider is not None:
            data = dict(self._status_provider())
        else:
            data = {}
            if self._executor is not None:
                data["dry_run"] = bool(self._executor.is_dry_run())  # type: ignore[attr-defined]
        if not data:
            return "状态：暂无数据"
        return "状态：" + "  ".join(f"{key}={value}" for key, value in data.items())
