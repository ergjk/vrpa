"""微信顶层窗口与客户端矩形（M2-01）。"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from vrpa.errors import WindowNotForeground, WindowNotFound
from vrpa.ports import Rect
from vrpa.vision.window import PywinautoWindowBackend, WindowBackend, WindowInfo

if TYPE_CHECKING:  # pragma: no cover
    from wechat_agent.core.config import Config

__all__ = ["WeChatWindow"]


class WeChatWindow:
    """微信主窗口定位 / 前台校验（真实后端延迟导入，测试可注入 FakeWindowBackend）。"""

    def __init__(
        self,
        config: Config,
        backend: WindowBackend | None = None,
        *,
        wait_timeout: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._backend = backend or PywinautoWindowBackend()
        self._wait_timeout = max(0.1, wait_timeout)
        self._sleep = sleep

    def find(self) -> WindowInfo:
        info = self._backend.find(
            title_regex=self._config.wechat.window_title_regex,
            process_names=self._config.wechat.process_names,
        )
        if info is None:
            raise WindowNotFound(
                f"未找到微信窗口（title~{self._config.wechat.window_title_regex!r}）",
                hint="确认微信 PC 已启动并登录；窗口未最小化",
            )
        return info

    def client_rect(self) -> Rect:
        return self.find().client_rect

    def is_foreground(self) -> bool:
        info = self.find()
        return bool(self._backend.is_foreground(info.hwnd))

    def foreground_process_name(self) -> str | None:
        """当前前台窗口的进程名（用于兼容微信 4.x 多顶层窗口）。"""
        try:
            import win32gui  # type: ignore[import-untyped]

            from vrpa.vision.window import _process_name

            hwnd = int(win32gui.GetForegroundWindow())
            if not hwnd:
                return None
            _thread_id, pid = win32gui.GetWindowThreadProcessId(hwnd)
            return _process_name(int(pid))
        except Exception:  # noqa: BLE001
            return None

    def ensure_foreground(self) -> WindowInfo:
        info = self.find()
        if self._backend.is_foreground(info.hwnd):
            return info
        self._backend.activate(info.hwnd)
        attempts = max(1, int(self._wait_timeout / 0.1))
        for _ in range(attempts):
            if self._backend.is_foreground(info.hwnd):
                return info
            self._sleep(0.1)
        raise WindowNotForeground(
            f"微信窗口未能置前（hwnd={info.hwnd}）",
            hint="检查是否有其它窗口抢占焦点，或窗口被最小化",
        )
