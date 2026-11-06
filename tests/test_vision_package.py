"""M1 补充测试：校准包（Profile & Anchors）导出/导入。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from vision_fixtures import paint_patches
from vrpa.errors import TreeConfigError
from vrpa.ports import Rect
from vrpa.vision.calibration import CalibrationSession
from vrpa.vision.locator import AnchorLocator
from vrpa.vision.package import (
    PACKAGE_ANCHORS_DIR,
    PACKAGE_MANIFEST,
    PACKAGE_PROFILE,
    PACKAGE_VERSION,
    export_package,
    import_package,
    list_package_files,
)
from vrpa.vision.profile import load_profile
from vrpa.vision.screen import ImageScreenSource

MAIN = Rect(5, 5, 590, 390)
INPUT = Rect(100, 100, 80, 30)


def _make_profile(tmp_path: Path):
    screen, _ = paint_patches(600, 400, {"main_window": MAIN, "input_box": INPUT})
    rects = {"main_window": MAIN, "input_box": INPUT}
    current = {"id": ""}

    def selector(_image) -> Rect:
        return rects[current["id"]]

    session = CalibrationSession(
        tmp_path / "uia_tree" / "600x400@1.json",
        ImageScreenSource(screen),
        selector,
        profile_name="600x400@1",
        anchors_root=tmp_path / "anchors",
    )
    current["id"] = "main_window"
    session.calibrate("main_window", role="container")
    current["id"] = "input_box"
    session.calibrate("input_box", parent="main_window")
    return session.finalize(), screen


def test_export_package_structure(tmp_path: Path) -> None:
    result, _ = _make_profile(tmp_path)
    share = tmp_path / "share"
    info = export_package(result.profile, share)
    assert (share / PACKAGE_PROFILE).is_file()
    assert (share / PACKAGE_MANIFEST).is_file()
    # main_window 是容器：只存静态 rect，不导出锚点图
    assert not (share / PACKAGE_ANCHORS_DIR / "main_window.png").exists()
    assert (share / PACKAGE_ANCHORS_DIR / "input_box.png").is_file()
    manifest = json.loads((share / PACKAGE_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["package_version"] == PACKAGE_VERSION
    assert manifest["profile"] == "600x400@1"
    assert set(info.files) == set(list_package_files(info.profile))


def test_export_refuses_non_empty_without_force(tmp_path: Path) -> None:
    result, _ = _make_profile(tmp_path)
    share = tmp_path / "share"
    export_package(result.profile, share)
    with pytest.raises(TreeConfigError, match="非空"):
        export_package(result.profile, share)
    assert export_package(result.profile, share, force=True).profile.profile == "600x400@1"


def test_import_roundtrip_and_locate(tmp_path: Path) -> None:
    result, screen = _make_profile(tmp_path)
    share = tmp_path / "share"
    export_package(result.profile, share)

    target_profile = tmp_path / "imported" / "profile.json"
    target_anchors = tmp_path / "imported" / "anchors"
    info = import_package(share, profile_target=target_profile, anchors_target=target_anchors)

    assert target_profile.is_file()
    assert (target_anchors / "input_box.png").is_file()
    loaded = load_profile(target_profile, anchors_root=target_anchors)
    assert loaded.validate() == []
    locator = AnchorLocator(loaded, ImageScreenSource(screen))
    assert locator.locate("input_box").as_tuple() == INPUT.as_tuple()
    assert set(info.files) >= {PACKAGE_PROFILE, PACKAGE_MANIFEST, "anchors/input_box.png"}


def test_import_from_zip(tmp_path: Path) -> None:
    result, _ = _make_profile(tmp_path)
    share = tmp_path / "share"
    export_package(result.profile, share)
    archive = tmp_path / "share.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for path in share.rglob("*"):
            if path.is_file():
                bundle.write(path, path.relative_to(share))
    info = import_package(
        archive,
        profile_target=tmp_path / "x" / "profile.json",
        anchors_target=tmp_path / "x" / "anchors",
    )
    assert info.profile.validate() == []


def test_import_rejects_existing_without_force(tmp_path: Path) -> None:
    result, _ = _make_profile(tmp_path)
    share = tmp_path / "share"
    export_package(result.profile, share)
    target_profile = tmp_path / "target" / "profile.json"
    target_anchors = tmp_path / "target" / "anchors"
    import_package(share, profile_target=target_profile, anchors_target=target_anchors)
    with pytest.raises(TreeConfigError, match="目标已存在"):
        import_package(share, profile_target=target_profile, anchors_target=target_anchors)
    assert (
        import_package(share, profile_target=target_profile, anchors_target=target_anchors, force=True).profile.profile
        == "600x400@1"
    )


def test_import_missing_package_files(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(TreeConfigError, match="缺少 profile.json"):
        import_package(empty, profile_target=tmp_path / "p.json", anchors_target=tmp_path / "a")

    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "profile.json").write_text(
        json.dumps({"schema": 1, "profile": "x", "width": 10, "height": 10, "dpi_scale": 1.0, "elements": {}}),
        encoding="utf-8",
    )
    with pytest.raises(TreeConfigError, match="缺少 anchors"):
        import_package(bad, profile_target=tmp_path / "p2.json", anchors_target=tmp_path / "a2")


def test_import_rejects_bad_manifest_version(tmp_path: Path) -> None:
    result, _ = _make_profile(tmp_path)
    share = tmp_path / "share"
    export_package(result.profile, share)
    manifest = json.loads((share / PACKAGE_MANIFEST).read_text(encoding="utf-8"))
    manifest["package_version"] = 99
    (share / PACKAGE_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(TreeConfigError, match="版本不受支持"):
        import_package(share, profile_target=tmp_path / "p.json", anchors_target=tmp_path / "a")
