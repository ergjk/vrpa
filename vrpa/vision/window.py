"""顶层窗口与客户端矩形（M2-01，平台无关）。

``WindowBackend`` 抽象真实窗口系统；测试注入 ``FakeWindowBackend``（vrpa.testing.fakes），
因此纯代码测试不需要真实客户端/桌面。
"""

from __future__ import annotations

import ctypes
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from vrpa.errors import WindowNotForeground, WindowNotFound
from vrpa.ports import Rect

__all__ = ["PywinautoWindowBackend", "WindowBackend", "WindowInfo"]


@dataclass(frozen=True)
class WindowInfo:
    """顶层窗口信息（屏幕绝对坐标）。"""

    hwnd: int
    title: str
    rect: Rect
    client_rect: Rect
    process_name: str | None = None


@runtime_checkable
class WindowBackend(Protocol):
    """窗口系统后端协议。"""

    def find(self, *, title_regex: str, process_names: Sequence[str]) -> WindowInfo | None:
        """按标题正则 + 进程名查找可见窗口。"""
        ...

    def activate(self, hwnd: int) -> None:
        """把窗口置于前台；失败即抛 WindowNotForeground。"""
        ...

    def is_foreground(self, hwnd: int) -> bool:
        """窗口是否为当前前台窗口。"""
        ...


def _process_name(pid: int) -> str | None:
    """用 Win32 API 取进程可执行文件名（不引入 psutil）。"""
    if sys.platform != "win32":
        return None
    process_query_limited_information = 0x1000
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return None
        try:
            buffer = ctypes.create_unicode_buffer(260)
            size = ctypes.c_ulong(260)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return buffer.value.rsplit("\\", 1)[-1]
        finally:
            kernel32.CloseHandle(handle)
    except OSError:
        return None
    return None


def _rect_from_ltrb(left: int, top: int, right: int, bottom: int) -> Rect:
    return Rect(int(left), int(top), max(1, int(right - left)), max(1, int(bottom - top)))


class PywinautoWindowBackend:
    """pywinauto 实现（延迟导入；无桌面/缺依赖时抛 WindowNotFound）。"""

    def __init__(self) -> None:
        self._desktops: dict[str, Any] = {}

    def _desktop_instance(self, backend: str = "uia") -> Any:
        if backend not in self._desktops:
            try:
                from pywinauto import Desktop  # type: ignore[import-untyped]
            except ModuleNotFoundError as exc:
                raise WindowNotFound("缺少 pywinauto 依赖：无法枚举窗口") from exc
            self._desktops[backend] = Desktop(backend=backend)
        return self._desktops[backend]

    def find(self, *, title_regex: str, process_names: Sequence[str]) -> WindowInfo | None:
        try:
            pattern = re.compile(title_regex)
        except re.error as exc:
            raise WindowNotFound(f"窗口标题正则非法：{exc}") from exc
        # 真实机兼容：部分新版客户端 UIA 枚举为空，需降级 win32 枚举。
        errors: list[Exception] = []
        for backend in ("win32", "uia"):
            try:
                desktop = self._desktop_instance(backend)
            except WindowNotFound:
                raise
            try:
                windows = list(desktop.windows(visible_only=True, enabled_only=True))
            except Exception as exc:  # noqa: BLE001 - 单个后端失败则尝试下一个
                errors.append(exc)
                continue
            for window in windows:
                title = str(window.window_text() or "")
                if not pattern.search(title):
                    continue
                info = self._info(window, title)
                if process_names and info.process_name and info.process_name not in process_names:
                    continue
                return info
        if len(errors) >= 2:  # noqa: PLR2004 - 两个后端都失败才视为枚举异常
            raise WindowNotFound(f"枚举窗口失败：{errors[-1]}") from errors[-1]
        return None

    def activate(self, hwnd: int) -> None:
        try:
            import contextlib

            import win32api  # type: ignore[import-untyped]
            import win32con  # type: ignore[import-untyped]
            import win32gui  # type: ignore[import-untyped]
            import win32process  # type: ignore[import-untyped]

            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            if int(win32gui.GetForegroundWindow()) != int(hwnd):
                # 前台锁：模拟 Alt 解锁，并同时绑定当前/前台/目标窗口线程。
                win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
                win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
                current_thread = win32api.GetCurrentThreadId()
                foreground = win32gui.GetForegroundWindow()
                foreground_thread = win32process.GetWindowThreadProcessId(foreground)[0]
                target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
                attached: list[int] = []
                for thread_id in {foreground_thread, target_thread}:
                    if thread_id and win32process.AttachThreadInput(current_thread, thread_id, True):
                        attached.append(thread_id)
                try:
                    win32gui.BringWindowToTop(hwnd)
                    win32gui.SetForegroundWindow(hwnd)
                    win32gui.SetFocus(hwnd)
                finally:
                    for thread_id in attached:
                        win32process.AttachThreadInput(current_thread, thread_id, False)
            if int(win32gui.GetForegroundWindow()) != int(hwnd):
                with contextlib.suppress(Exception):
                    win32gui.SwitchToThisWindow(hwnd, True)
            if int(win32gui.GetForegroundWindow()) != int(hwnd):
                raise WindowNotForeground(f"激活窗口失败（hwnd={hwnd}）：前台锁未解除")
        except WindowNotForeground:
            raise
        except Exception as exc:  # noqa: BLE001
            raise WindowNotForeground(f"激活窗口失败（hwnd={hwnd}）：{exc}") from exc

    def is_foreground(self, hwnd: int) -> bool:
        try:
            import win32gui

            return int(win32gui.GetForegroundWindow()) == int(hwnd)
        except Exception:  # noqa: BLE001
            return False

    def _info(self, window: Any, title: str) -> WindowInfo:
        hwnd = int(getattr(window, "handle", 0) or 0)
        rectangle = window.rectangle()
        rect = _rect_from_ltrb(rectangle.left, rectangle.top, rectangle.right, rectangle.bottom)
        client_rect = rect
        try:
            import win32gui

            _left, _top, right, bottom = win32gui.GetClientRect(hwnd)
            origin_x, origin_y = win32gui.ClientToScreen(hwnd, (0, 0))
            client_rect = _rect_from_ltrb(origin_x, origin_y, origin_x + right, origin_y + bottom)
        except Exception:  # noqa: BLE001 - 客户端矩形取不到时退化为窗口矩形
            client_rect = rect
        process_name = None
        try:
            process_name = _process_name(int(window.process_id()))
        except Exception:  # noqa: BLE001
            process_name = None
        return WindowInfo(hwnd=hwnd, title=title, rect=rect, client_rect=client_rect, process_name=process_name)
