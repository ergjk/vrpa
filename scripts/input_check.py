"""真机输入注入自检：移动鼠标 + 在记事本拖选复制（只做无害操作）。

用法：
    python scripts/input_check.py

先打开记事本并写入几行文字，然后运行；脚本会：
1. 打印屏幕尺寸；
2. 把鼠标移动到几个坐标（观察光标是否动）；
3. 在记事本里拖选一段文字并 Ctrl+C，检查剪贴板是否变化。
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import time  # noqa: E402


def main() -> int:
    from vrpa.vision.dpi import enable_dpi_awareness

    enable_dpi_awareness()
    import pyautogui  # type: ignore[import-untyped]

    print("screen =", pyautogui.size())
    print("before =", pyautogui.position())
    for point in ((300, 300), (1200, 700), (800, 500)):
        pyautogui.moveTo(point[0], point[1], duration=1.0)
        print("moved  =", point, "->", pyautogui.position())
        time.sleep(0.5)

    print("\n3 秒后将在记事本区域拖选（请确保记事本在前台且有几行文字）…")
    time.sleep(3)
    pyautogui.moveTo(300, 300, duration=0.5)
    pyautogui.dragTo(1200, 700, duration=1.0, button="left")
    pyautogui.hotkey("ctrl", "c")
    time.sleep(0.3)
    import pyperclip

    print("clipboard =", repr(pyperclip.paste()[:200]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
