"""M1 视觉测试共享工具：合成屏幕、锚点图、临时配置文件。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from vrpa.ports import Rect
from vrpa.vision.matcher import Image


def paint_patches(
    width: int,
    height: int,
    patches: dict[str, Rect],
    *,
    seed: int = 0,
    background: int = 240,
) -> tuple[Image, dict[str, Image]]:
    """生成白底屏幕 + 随机纹理补丁，返回 (screen, {name: crop})。"""
    rng = np.random.default_rng(seed)
    screen: Image = np.full((height, width, 3), background, np.uint8)
    templates: dict[str, Image] = {}
    for name, rect in patches.items():
        patch = rng.integers(0, 255, size=(rect.height, rect.width, 3), dtype=np.uint8)
        screen[rect.y : rect.bottom, rect.x : rect.right] = patch
        templates[name] = patch
    return screen, templates


def save_png(path: Path, image: Image) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        raise RuntimeError(f"无法写入测试图片：{path}")
    return path


def write_profile_json(
    path: Path,
    *,
    width: int,
    height: int,
    profile_name: str = "test@1",
    elements: dict[str, dict[str, object]],
    dpi_scale: float = 1.0,
) -> Path:
    """写一份 profile JSON（元素定义直接透传）。"""
    import json

    document = {
        "schema": 1,
        "profile": profile_name,
        "width": width,
        "height": height,
        "dpi_scale": dpi_scale,
        "created_at": "2026-11-06T00:00:00",
        "elements": elements,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
