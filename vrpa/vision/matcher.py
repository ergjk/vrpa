"""锚点图多尺度匹配引擎（M1-02，平台无关）。

算法：OpenCV ``TM_CCOEFF_NORMED`` 多尺度模板匹配（灰度 + 降采样加速），
返回绝对坐标与匹配分数；低于阈值一律返回 ``None``（由定位层抛 ElementNotVisible）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from vrpa.errors import TreeConfigError
from vrpa.ports import Rect

__all__ = ["AnchorMatcher", "MatchResult", "load_image"]

Image = NDArray[Any]

DEFAULT_SCALES: tuple[float, ...] = (0.9, 0.95, 1.0, 1.05, 1.1)
_MIN_TEMPLATE_SIDE = 8


def load_image(path: Path | str) -> Image:
    """读取锚点图（BGR）。"""
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise TreeConfigError(f"无法读取锚点图：{path}")
    return np.asarray(image, dtype=np.uint8)


@dataclass(frozen=True)
class MatchResult:
    """一次成功匹配：绝对矩形 + 分数 + 命中的缩放比例。"""

    rect: Rect
    score: float
    scale: float


class AnchorMatcher:
    """多尺度锚点匹配器。"""

    def __init__(
        self,
        *,
        threshold: float = 0.88,
        scales: Sequence[float] = DEFAULT_SCALES,
        grayscale: bool = True,
        max_side_px: int = 1600,
    ) -> None:
        if not 0.0 < threshold <= 1.0:
            raise TreeConfigError(f"threshold 必须在 (0, 1]：{threshold}")
        if max_side_px < 64:
            raise TreeConfigError(f"max_side_px 过小：{max_side_px}")
        self._threshold = float(threshold)
        self._scales = tuple(float(scale) for scale in scales)
        self._grayscale = grayscale
        self._max_side_px = int(max_side_px)
        self.last_score: float = 0.0

    def match(
        self,
        screen: Image,
        template: Image,
        *,
        threshold: float | None = None,
        scales: Sequence[float] | None = None,
    ) -> MatchResult | None:
        """在 screen 中查找 template；返回最佳匹配或 None。"""
        limit = self._threshold if threshold is None else float(threshold)
        scale_list = self._scales if scales is None else tuple(float(item) for item in scales)
        if screen.size == 0 or template.size == 0:
            self.last_score = 0.0
            return None

        screen_work = self._prepare(screen)
        screen_height, screen_width = screen_work.shape[:2]
        factor = 1.0
        longest = max(screen_height, screen_width)
        if longest > self._max_side_px:
            factor = self._max_side_px / float(longest)
            screen_work = cv2.resize(
                screen_work,
                (max(1, int(round(screen_width * factor))), max(1, int(round(screen_height * factor)))),
                interpolation=cv2.INTER_AREA,
            )
            screen_height, screen_width = screen_work.shape[:2]

        template_work = self._prepare(template)
        template_h, template_w = template_work.shape[:2]
        best: tuple[float, tuple[int, int], float, int, int] | None = None
        for scale in scale_list:
            width = int(round(template_w * scale * factor))
            height = int(round(template_h * scale * factor))
            if width < _MIN_TEMPLATE_SIDE or height < _MIN_TEMPLATE_SIDE:
                continue
            if width > screen_width or height > screen_height:
                continue
            interpolation = cv2.INTER_AREA if scale * factor < 1.0 else cv2.INTER_LINEAR
            resized = cv2.resize(template_work, (width, height), interpolation=interpolation)
            response = cv2.matchTemplate(screen_work, resized, cv2.TM_CCOEFF_NORMED)
            _, max_value, _, max_location = cv2.minMaxLoc(response)
            if best is None or max_value > best[0]:
                best = (float(max_value), (int(max_location[0]), int(max_location[1])), scale, width, height)

        self.last_score = 0.0 if best is None else best[0]
        if best is None or best[0] < limit:
            return None
        _, (left, top), scale, _, _ = best
        x = int(round(left / factor))
        y = int(round(top / factor))
        width = max(1, int(round(template_w * scale)))
        height = max(1, int(round(template_h * scale)))
        return MatchResult(rect=Rect(x, y, width, height), score=best[0], scale=scale)

    def match_anchors(
        self,
        screen: Image,
        templates: Sequence[Image],
        *,
        threshold: float | None = None,
        scales: Sequence[float] | None = None,
    ) -> MatchResult | None:
        """按顺序尝试多张锚点图，返回第一张命中结果。"""
        for template in templates:
            result = self.match(screen, template, threshold=threshold, scales=scales)
            if result is not None:
                return result
        return None

    def _prepare(self, image: Image) -> Image:
        if self._grayscale:
            if image.ndim == 3:
                return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            return image
        return image
