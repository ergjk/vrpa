"""视觉工具共享装配（M1）：从应用配置构建 AnchorLocator / 屏幕源。"""

from __future__ import annotations

from pathlib import Path

from vrpa.errors import ProfileMismatch
from vrpa.vision.locator import AnchorLocator
from vrpa.vision.matcher import AnchorMatcher
from vrpa.vision.profile import Profile, load_profile
from vrpa.vision.screen import AutoScreenSource, ImageScreenSource, ScreenSource

__all__ = ["build_locator", "build_screen", "load_config_profile"]


def load_config_profile(config: object) -> Profile:
    """从应用 Config 读取 profile（锚点目录按 profile 名解析）。"""
    profile_path = config.profile_path()  # type: ignore[attr-defined]
    anchors_root = config.profile_anchors_dir()  # type: ignore[attr-defined]
    return load_profile(profile_path, anchors_root=anchors_root)


def build_screen(image: Path | None) -> ScreenSource:
    """--image 时使用离线静态图，否则使用真实截屏。"""
    return ImageScreenSource.from_file(image) if image is not None else AutoScreenSource()


def build_locator(config: object, *, image: Path | None = None) -> AnchorLocator:
    """按应用配置构建定位器，并校验屏幕尺寸与 profile 一致。"""
    uia = config.uia_tree  # type: ignore[attr-defined]
    screen = build_screen(image)
    profile = load_config_profile(config)
    first_frame = screen.capture()
    height, width = first_frame.shape[:2]
    if (width, height) != (profile.width, profile.height):
        raise ProfileMismatch(
            f"屏幕尺寸与 profile 不一致：当前 {width}x{height}，profile={profile.profile}"
            f"（{profile.width}x{profile.height}）；请重新校准",
            hint="分辨率/DPI 变化后执行 `python -m wechat_agent calibrate` 重新校准",
        )
    matcher = AnchorMatcher(
        threshold=uia.match.threshold,
        scales=uia.match.scales,
        grayscale=uia.match.grayscale,
        max_side_px=uia.match.max_side_px,
    )
    return AnchorLocator(profile, screen, matcher=matcher, cache_ttl=uia.cache_ttl)
