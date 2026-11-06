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
        """把窗口置为前台。"""
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
        self._desktop: Any = None

    def _desktop_instance(self) -> Any:
        if self._desktop is None:
            try:
                from pywinauto import Desktop  # type: ignore[import-untyped]
            except ModuleNotFoundError as exc:
                raise WindowNotFound("缺少 pywinauto 依赖：无法枚举窗口") from exc
            self._desktop = Desktop(backend="uia")
        return self._desktop

    def find(self, *, title_regex: str, process_names: Sequence[str]) -> WindowInfo | None:
        try:
            pattern = re.compile(title_regex)
        except re.error as exc:
            raise WindowNotFound(f"窗口标题正则非法：{exc}") from exc
        try:
            desktop = self._desktop_instance()
            for window in desktop.windows(visible_only=True, enabled_only=True):
                title = str(window.window_text() or "")
                if not pattern.search(title):
                    continue
                info = self._info(window, title)
                if process_names and info.process_name and info.process_name not in process_names:
                    continue
                return info
        except WindowNotFound:
            raise
        except Exception as exc:  # noqa: BLE001 - 窗口系统异常统一映射
            raise WindowNotFound(f"枚举窗口失败：{exc}") from exc
        return None

    def activate(self, hwnd: int) -> None:
        try:
            import win32gui  # type: ignore[import-untyped]

            win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
            win32gui.SetForegroundWindow(hwnd)
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
