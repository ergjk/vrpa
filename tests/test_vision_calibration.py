"""M1-04 测试：校准向导核心（框选 -> 锚点图 -> profile -> 回验）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from vision_fixtures import paint_patches
from vrpa.errors import TreeConfigError
from vrpa.ports import Rect
from vrpa.vision.calibration import CalibrationSession
from vrpa.vision.locator import AnchorLocator
from vrpa.vision.profile import load_profile
from vrpa.vision.screen import ImageScreenSource

MAIN = Rect(5, 5, 590, 390)
INPUT = Rect(100, 100, 80, 30)


class Selector:
    def __init__(self, rects: dict[str, Rect]) -> None:
        self.rects = rects

    def __call__(self, image: object) -> Rect:
        return self.rects[self._current]

    _current = ""


def _session(tmp_path: Path, rects: dict[str, Rect]) -> tuple[CalibrationSession, Selector]:
    screen, _ = paint_patches(600, 400, {"main_window": MAIN, "input_box": INPUT})
    selector = Selector(rects)
    session = CalibrationSession(
        tmp_path / "uia_tree" / "600x400@1.json",
        ImageScreenSource(screen),
        selector,
        profile_name="600x400@1",
        anchors_root=tmp_path / "anchors",
    )
    return session, selector


def test_calibrate_then_finalize_and_locate(tmp_path: Path) -> None:
    session, selector = _session(tmp_path, {"main_window": MAIN, "input_box": INPUT})
    selector._current = "main_window"
    assert session.calibrate("main_window", role="container") == MAIN
    selector._current = "input_box"
    assert session.calibrate("input_box", parent="main_window") == INPUT
    result = session.finalize()

    assert result.profile_path.is_file()
    assert result.element_ids == ("main_window", "input_box")
    assert (tmp_path / "anchors" / "main_window.png").is_file()
    assert (tmp_path / "anchors" / "input_box.png").is_file()

    profile = load_profile(result.profile_path, anchors_root=tmp_path / "anchors")
    assert profile.validate() == []
    screen, _ = paint_patches(600, 400, {"main_window": MAIN, "input_box": INPUT})
    locator = AnchorLocator(profile, ImageScreenSource(screen))
    assert locator.locate("input_box").as_tuple() == INPUT.as_tuple()
    assert locator.validate(required_ids=profile.element_ids()).ok


def test_out_of_bounds_selection_rejected(tmp_path: Path) -> None:
    session, selector = _session(tmp_path, {"main_window": Rect(590, 390, 100, 100)})
    selector._current = "main_window"
    with pytest.raises(TreeConfigError, match="越界"):
        session.calibrate("main_window")


def test_parent_must_be_calibrated_first(tmp_path: Path) -> None:
    session, _ = _session(tmp_path, {"input_box": INPUT})
    with pytest.raises(TreeConfigError, match="父元素"):
        session.calibrate("input_box", parent="main_window")


def test_finalize_without_elements_rejected(tmp_path: Path) -> None:
    session, _ = _session(tmp_path, {})
    with pytest.raises(TreeConfigError, match="尚未校准"):
        session.finalize()


def test_invalid_threshold_rejected(tmp_path: Path) -> None:
    session, selector = _session(tmp_path, {"main_window": MAIN})
    selector._current = "main_window"
    with pytest.raises(TreeConfigError, match="threshold"):
        session.calibrate("main_window", threshold=0.0)


def test_remove_element(tmp_path: Path) -> None:
    session, selector = _session(tmp_path, {"main_window": MAIN})
    selector._current = "main_window"
    session.calibrate("main_window", role="container")
    assert session.remove("main_window") is True
    assert session.remove("main_window") is False
    assert session.element_ids == ()
