"""鼠标 / 键盘 / 剪贴板驱动（M2-02/03，平台无关）。

真实实现延迟导入 pyautogui / pyperclip；测试注入 ``FakeDriver``（vrpa.testing.fakes），
因此采集相关单测不触碰真实键鼠与剪贴板。
"""

from __future__ import annotations

import sys
import time
from typing import Protocol, runtime_checkable

from vrpa.errors import CopyFailed

__all__ = ["Driver", "PyAutoGuiDriver"]


@runtime_checkable
class Driver(Protocol):
    """RPA 输入输出驱动协议（只做输入模拟与剪贴板读写）。"""

    def click(self, x: int, y: int) -> None:
        """鼠标左键单击屏幕绝对坐标。"""
        ...

    def drag(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        *,
        steps: int = 18,
        duration: float = 0.45,
    ) -> None:
        """按住左键从 start 拖到 end（模拟人手）。"""
        ...

    def hotkey(self, *keys: str) -> None:
        """组合键，如 hotkey("ctrl", "c")。"""
        ...

    def type_text(self, text: str) -> None:
        """键入 ASCII 文本（中文走剪贴板粘贴）。"""
        ...

    def clipboard_get(self) -> str:
        """读取剪贴板文本。"""
        ...

    def clipboard_set(self, text: str) -> None:
        """写入剪贴板文本。"""
        ...


class PyAutoGuiDriver:
    """pyautogui + pyperclip 实现（延迟导入）。"""

    def __init__(self, *, pause: float = 0.02) -> None:
        self._pause = pause

    def click(self, x: int, y: int) -> None:
        import pyautogui  # type: ignore[import-untyped]

        pyautogui.moveTo(x, y, duration=self._pause)
        pyautogui.click()

    def drag(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        *,
        steps: int = 18,
        duration: float = 0.45,
    ) -> None:
        import pyautogui

        if steps < 4:
            raise CopyFailed(f"拖拽 steps 过小：{steps}")
        pyautogui.moveTo(start[0], start[1], duration=self._pause)
        pyautogui.dragTo(end[0], end[1], duration=max(0.05, duration), button="left")

    def hotkey(self, *keys: str) -> None:
        import pyautogui

        pyautogui.hotkey(*keys)

    def type_text(self, text: str) -> None:
        import pyautogui

        pyautogui.write(text, interval=self._pause)

    def clipboard_get(self) -> str:
        try:
            import pyperclip  # type: ignore[import-untyped]

            return str(pyperclip.paste())
        except Exception as exc:  # noqa: BLE001 - 剪贴板不可用统一映射
            raise CopyFailed(f"读取剪贴板失败：{exc}") from exc

    def clipboard_set(self, text: str) -> None:
        try:
            import pyperclip

            pyperclip.copy(text)
        except Exception as exc:  # noqa: BLE001
            raise CopyFailed(f"写入剪贴板失败：{exc}") from exc
        if sys.platform != "win32":  # pragma: no cover - 仅 Windows 为目标平台
            time.sleep(0.05)
