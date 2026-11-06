"""校准向导核心（M1-04，平台无关）。

交互层（框选 GUI / 截图）由调用方注入：
    - ``screen``：屏幕图像源（真实桌面或测试静态图）；
    - ``selector``：给定整屏图像，返回用户框选的绝对 ``Rect``。

校准产物：锚点裁剪图（PNG）+ profile JSON（含父元素关系与阈值），
最后回验结构，确保「校准完即可定位」。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2

from vrpa.errors import TreeConfigError
from vrpa.ports import Rect
from vrpa.vision.matcher import Image
from vrpa.vision.profile import AnchorSpec, ElementSpec, Profile, save_profile
from vrpa.vision.screen import ScreenSource

__all__ = ["CalibrationResult", "CalibrationSession", "RegionSelector"]

RegionSelector = Callable[[Image], Rect]


@dataclass(frozen=True)
class CalibrationResult:
    """校准完成结果。"""

    profile_path: Path
    profile: Profile
    element_ids: tuple[str, ...]


class CalibrationSession:
    """逐元素校准：框选 -> 存锚点图 -> 写 profile -> 回验。"""

    def __init__(
        self,
        profile_path: Path | str,
        screen: ScreenSource,
        selector: RegionSelector,
        *,
        profile_name: str,
        anchors_root: Path | str,
        dpi_scale: float = 1.0,
    ) -> None:
        self._profile_path = Path(profile_path)
        self._screen = screen
        self._selector = selector
        self._profile_name = profile_name
        self._anchors_root = Path(anchors_root)
        self._dpi_scale = dpi_scale
        self._elements: dict[str, ElementSpec] = {}
        self._image: Image | None = None

    @property
    def element_ids(self) -> tuple[str, ...]:
        return tuple(self._elements)

    def calibrate(
        self,
        element_id: str,
        *,
        role: str = "anchor",
        purpose: str = "click",
        parent: str | None = None,
        threshold: float = 0.88,
    ) -> Rect:
        """框选元素 -> 保存锚点图 -> 记录元素；返回框选的绝对矩形。"""
        if not element_id.strip():
            raise TreeConfigError("element_id 不能为空")
        if parent is not None and parent not in self._elements:
            raise TreeConfigError(f"父元素 {parent!r} 尚未校准（请先校准父元素）")
        if not 0.0 < threshold <= 1.0:
            raise TreeConfigError(f"threshold 必须在 (0, 1]：{threshold}")

        image = self._capture()
        rect = self._normalize_rect(self._selector(image), image)
        self._anchors_root.mkdir(parents=True, exist_ok=True)
        anchor_rel = f"{element_id}.png"
        crop = image[rect.y : rect.bottom, rect.x : rect.right]
        if crop.size == 0:
            raise TreeConfigError(f"元素 {element_id} 框选区域为空")
        target = self._anchors_root / anchor_rel
        if not cv2.imwrite(str(target), crop):
            raise TreeConfigError(f"锚点图写入失败：{target}")

        self._elements[element_id] = ElementSpec(
            element_id=element_id,
            role=role,
            purpose=purpose,
            parent=parent,
            anchors=(AnchorSpec(path=anchor_rel, threshold=threshold),),
            meta={
                "calibrated_at": datetime.now().isoformat(timespec="seconds"),
                "anchor_size": [rect.width, rect.height],
            },
        )
        return rect

    def remove(self, element_id: str) -> bool:
        return self._elements.pop(element_id, None) is not None

    def finalize(self) -> CalibrationResult:
        """写出 profile 并回验（结构 + 锚点文件存在）。"""
        if not self._elements:
            raise TreeConfigError("尚未校准任何元素")
        image = self._capture()
        height, width = image.shape[:2]
        profile = Profile(
            schema=1,
            profile=self._profile_name,
            width=width,
            height=height,
            dpi_scale=self._dpi_scale,
            elements=dict(self._elements),
            anchors_root=self._anchors_root,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        problems = profile.validate(check_anchor_files=True)
        if problems:
            raise TreeConfigError("校准结果校验失败：" + "；".join(problems[:6]))
        save_profile(profile, self._profile_path)
        return CalibrationResult(
            profile_path=self._profile_path,
            profile=profile,
            element_ids=tuple(profile.elements),
        )

    # ------------------------------------------------------------ 内部
    def _capture(self) -> Image:
        if self._image is None:
            self._image = self._screen.capture()
        return self._image

    @staticmethod
    def _normalize_rect(rect: Rect, image: Image) -> Rect:
        height, width = image.shape[:2]
        if rect.width <= 0 or rect.height <= 0:
            raise TreeConfigError(f"框选区域宽高必须为正：{rect.width}x{rect.height}")
        if rect.x < 0 or rect.y < 0 or rect.right > width or rect.bottom > height:
            raise TreeConfigError(f"框选区域越界：{rect.as_tuple()}（图像 {width}x{height}）")
        return rect
