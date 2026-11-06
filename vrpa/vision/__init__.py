"""VRPA 视觉子系统（平台无关）：假 UIA 树 profile、锚点多尺度匹配、元素定位、校准。

依赖：``numpy`` + ``opencv-python``（仅本子系统需要；核心 vrpa 仍为标准库）。
红线 R3：视觉定位只服务「操作界面」，不读取/不推断消息内容。
"""

from __future__ import annotations

from vrpa.vision.calibration import CalibrationResult, CalibrationSession
from vrpa.vision.locator import AnchorLocator, ValidationReport
from vrpa.vision.matcher import AnchorMatcher, MatchResult, load_image
from vrpa.vision.package import (
    PackageInfo,
    export_package,
    import_package,
    list_package_files,
)
from vrpa.vision.profile import (
    PROFILE_SCHEMA_VERSION,
    AnchorSpec,
    ElementSpec,
    Profile,
    load_profile,
    save_profile,
)
from vrpa.vision.screen import AutoScreenSource, ImageScreenSource, ScreenSource

__all__ = [
    "PROFILE_SCHEMA_VERSION",
    "AnchorLocator",
    "AnchorMatcher",
    "AnchorSpec",
    "AutoScreenSource",
    "CalibrationResult",
    "CalibrationSession",
    "ElementSpec",
    "ImageScreenSource",
    "MatchResult",
    "PackageInfo",
    "export_package",
    "import_package",
    "list_package_files",
    "Profile",
    "ScreenSource",
    "ValidationReport",
    "load_image",
    "load_profile",
    "save_profile",
]
