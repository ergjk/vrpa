"""M1-02 测试：锚点图多尺度匹配引擎。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from vision_fixtures import paint_patches, save_png
from vrpa.errors import TreeConfigError
from vrpa.ports import Rect
from vrpa.vision.matcher import AnchorMatcher, load_image


def test_exact_match_returns_absolute_rect() -> None:
    screen, templates = paint_patches(600, 400, {"input_box": Rect(100, 120, 80, 40)})
    matcher = AnchorMatcher(threshold=0.9)
    result = matcher.match(screen, templates["input_box"])
    assert result is not None
    assert result.score > 0.99
    assert result.scale == pytest.approx(1.0)
    assert result.rect.as_tuple() == (100, 120, 80, 40)


def test_multiscale_match_resized_template() -> None:
    rng = np.random.default_rng(11)
    smooth = cv2.resize(rng.integers(0, 255, (10, 20, 3), dtype=np.uint8), (80, 40), interpolation=cv2.INTER_LINEAR)
    screen = np.full((400, 600, 3), 240, np.uint8)
    screen[120:160, 100:180] = smooth
    resized = cv2.resize(smooth, (72, 36))
    matcher = AnchorMatcher(threshold=0.8, scales=(1.0, 1.11))
    result = matcher.match(screen, resized)
    assert result is not None
    assert abs(result.rect.x - 100) <= 3
    assert abs(result.rect.y - 120) <= 3
    assert result.scale in (1.0, 1.11)


def test_threshold_miss_returns_none() -> None:
    screen, _ = paint_patches(600, 400, {"a": Rect(0, 0, 40, 40)})
    rng = np.random.default_rng(42)
    noise = rng.integers(0, 255, size=(40, 40, 3), dtype=np.uint8)
    matcher = AnchorMatcher(threshold=0.95)
    assert matcher.match(screen, noise) is None


def test_downscale_mapping_keeps_coordinates() -> None:
    # 平滑随机纹理在降采样后仍保持结构，适合验证坐标回映射
    rng = np.random.default_rng(5)
    small = rng.integers(0, 255, (15, 30, 3), dtype=np.uint8)
    template = cv2.resize(small, (300, 150), interpolation=cv2.INTER_LINEAR)
    screen = np.full((1600, 3000, 3), 240, np.uint8)
    screen[1200:1350, 2400:2700] = template
    matcher = AnchorMatcher(threshold=0.8, max_side_px=800)
    result = matcher.match(screen, template)
    assert result is not None
    assert abs(result.rect.x - 2400) <= 10
    assert abs(result.rect.y - 1200) <= 10
    assert abs(result.rect.width - 300) <= 10


def test_template_larger_than_screen_returns_none() -> None:
    screen, _ = paint_patches(200, 100, {"a": Rect(0, 0, 20, 20)})
    _, templates = paint_patches(400, 300, {"t": Rect(0, 0, 400, 300)}, seed=3)
    assert AnchorMatcher().match(screen, templates["t"]) is None


def test_multiple_anchors_first_hit_wins() -> None:
    screen, templates = paint_patches(600, 400, {"second": Rect(200, 200, 60, 30)})
    rng = np.random.default_rng(7)
    miss = rng.integers(0, 255, size=(30, 30, 3), dtype=np.uint8)
    matcher = AnchorMatcher(threshold=0.9)
    result = matcher.match_anchors(screen, [miss, templates["second"]])
    assert result is not None
    assert result.rect.as_tuple() == (200, 200, 60, 30)


def test_load_image_and_missing(tmp_path: Path) -> None:
    screen, _ = paint_patches(100, 100, {"a": Rect(0, 0, 10, 10)})
    path = save_png(tmp_path / "a.png", screen)
    assert load_image(path).shape == screen.shape
    with pytest.raises(TreeConfigError, match="无法读取锚点图"):
        load_image(tmp_path / "missing.png")


def test_matcher_validates_params() -> None:
    with pytest.raises(TreeConfigError):
        AnchorMatcher(threshold=0.0)
    with pytest.raises(TreeConfigError):
        AnchorMatcher(max_side_px=10)
