"""屏幕图像源（M1-02/03，平台无关）：真实截屏 / 静态图片注入。

测试与离线校验使用 ``ImageScreenSource``；真实运行使用 ``AutoScreenSource``
（延迟导入 pyautogui，避免无桌面环境导入即失败）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable

from numpy.typing import NDArray

from vrpa.errors import TreeConfigError
from vrpa.vision.matcher import Image, load_image

__all__ = ["AutoScreenSource", "ImageScreenSource", "ScreenSource"]


@runtime_checkable
class ScreenSource(Protocol):
    """屏幕图像源：返回 BGR uint8 图像。"""

    def capture(self) -> Image:
        """抓取一帧屏幕图像（分辨率与 profile 一致）。"""
        ...


class ImageScreenSource:
    """静态图片源（测试 / validate-tree --image 离线校验）。"""

    def __init__(self, image: NDArray[Any]) -> None:
        if image.size == 0:
            raise TreeConfigError("屏幕图像为空")
        self._image = image

    @classmethod
    def from_file(cls, path: Path | str) -> ImageScreenSource:
        return cls(load_image(path))

    def capture(self) -> Image:
        return cast(Image, self._image.copy())


class AutoScreenSource:
    """真实截屏源（延迟导入 pyautogui）。"""

    def capture(self) -> Image:
        try:
            import pyautogui  # type: ignore[import-untyped]
        except ModuleNotFoundError as exc:
            raise TreeConfigError("缺少 pyautogui 依赖：无法截屏（请安装 requirements.txt）") from exc
        try:
            screenshot = pyautogui.screenshot()
        except Exception as exc:  # noqa: BLE001 - 无桌面/权限问题统一转框架错误
            raise TreeConfigError(f"截屏失败：{exc}") from exc
        import numpy as np

        array = np.asarray(screenshot, dtype=np.uint8)
        if array.ndim == 3 and array.shape[2] >= 3:
            return cast(Image, array[:, :, :3][:, :, ::-1].copy())  # RGB -> BGR
        return array
