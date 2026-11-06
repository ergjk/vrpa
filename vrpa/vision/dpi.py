"""Windows DPI 感知（M6 真机适配）：统一截图与鼠标坐标到物理像素。

背景：200% 缩放下，DPI-unaware 进程的 pyautogui 鼠标坐标是逻辑像素，而
ImageGrab 截图可能是物理像素，导致“框选坐标看起来对、实际拖拽位置偏移”。
在 CLI 启动/真实驱动初始化时调用本模块，使截图与鼠标使用同一物理坐标系。
"""

from __future__ import annotations

import ctypes
import sys

__all__ = ["enable_dpi_awareness"]

_APPLIED = False


def enable_dpi_awareness() -> bool:
    """启用 Per-Monitor DPI 感知（幂等；非 Windows 返回 False）。"""
    global _APPLIED
    if _APPLIED:
        return True
    if sys.platform != "win32":
        return False
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        _APPLIED = True
        return True
    except Exception:  # noqa: BLE001 - 旧系统回退
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            _APPLIED = True
            return True
        except Exception:  # noqa: BLE001
            return False
