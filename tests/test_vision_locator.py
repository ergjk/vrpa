"""M1-03 / M1-06 测试：定位、缓存、失败语义、校验报告与性能。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from vision_fixtures import paint_patches, save_png, write_profile_json
from vrpa.errors import ElementNotVisible, TreeConfigError
from vrpa.ports import Rect
from vrpa.vision.locator import AnchorLocator
from vrpa.vision.matcher import AnchorMatcher, Image
from vrpa.vision.profile import AnchorSpec, ElementSpec, Profile, load_profile
from vrpa.vision.screen import ImageScreenSource

MAIN = Rect(5, 5, 590, 390)
INPUT = Rect(100, 100, 80, 30)


class CountingScreen:
    def __init__(self, image: Image) -> None:
        self._source = ImageScreenSource(image)
        self.captures = 0

    def capture(self) -> Image:
        self.captures += 1
        return self._source.capture()


def _build_profile(tmp_path: Path) -> tuple[Profile, Image, CountingScreen]:
    screen, _ = paint_patches(600, 400, {"main_window": MAIN, "input_box": INPUT})
    anchors = tmp_path / "anchors"
    save_png(anchors / "main_window.png", screen[MAIN.y : MAIN.bottom, MAIN.x : MAIN.right])
    save_png(anchors / "input_box.png", screen[INPUT.y : INPUT.bottom, INPUT.x : INPUT.right])
    path = write_profile_json(
        tmp_path / "uia_tree" / "600x400@1.json",
        width=600,
        height=400,
        profile_name="600x400@1",
        elements={
            "main_window": {
                "role": "container",
                "purpose": "click",
                "parent": None,
                "anchors": ["main_window.png"],
            },
            "input_box": {
                "role": "anchor",
                "purpose": "input",
                "parent": "main_window",
                "anchors": [{"path": "input_box.png", "threshold": 0.9}],
            },
        },
    )
    profile = load_profile(path, anchors_root=anchors)
    return profile, screen, CountingScreen(screen)


def test_locate_returns_absolute_rect_with_score(tmp_path: Path) -> None:
    profile, _, screen = _build_profile(tmp_path)
    locator = AnchorLocator(profile, screen, matcher=AnchorMatcher(threshold=0.9))
    rect = locator.locate("input_box")
    assert rect.as_tuple() == INPUT.as_tuple()
    match = locator.last_match("input_box")
    assert match is not None and match.score > 0.99
    assert locator.element_ids() == ("main_window", "input_box")
    assert locator.profile_name() == "600x400@1"


def test_cache_hits_avoid_capture_and_invalidate(tmp_path: Path) -> None:
    profile, _, screen = _build_profile(tmp_path)
    locator = AnchorLocator(profile, screen)
    locator.locate("input_box")
    first = screen.captures
    locator.locate("input_box")
    assert screen.captures == first  # 缓存命中
    locator.invalidate()
    locator.locate("input_box")
    assert screen.captures > first


def test_cache_ttl_expiry(tmp_path: Path) -> None:
    profile, _, screen = _build_profile(tmp_path)
    now = {"value": 100.0}
    locator = AnchorLocator(profile, screen, cache_ttl=1.0, clock=lambda: now["value"])
    locator.locate("input_box")
    base = screen.captures
    now["value"] += 0.5
    locator.locate("input_box")
    assert screen.captures == base
    now["value"] += 1.0
    locator.locate("input_box")
    assert screen.captures > base


def test_locate_failure_raises_element_not_visible(tmp_path: Path) -> None:
    profile, _, _ = _build_profile(tmp_path)
    blank, _ = paint_patches(600, 400, {"other": Rect(0, 0, 10, 10)})
    locator = AnchorLocator(profile, CountingScreen(blank))
    with pytest.raises(ElementNotVisible, match="未匹配到锚点"):
        locator.locate("input_box")


def test_unknown_element_raises_tree_error(tmp_path: Path) -> None:
    profile, _, screen = _build_profile(tmp_path)
    locator = AnchorLocator(profile, screen)
    with pytest.raises(TreeConfigError, match="不存在元素"):
        locator.locate("nope")


def test_explicit_rect_element_no_capture(tmp_path: Path) -> None:
    screen = ImageScreenSource(paint_patches(600, 400, {"a": Rect(0, 0, 10, 10)})[0])
    profile = Profile(
        schema=1,
        profile="600x400@1",
        width=600,
        height=400,
        dpi_scale=1.0,
        elements={"a": ElementSpec(element_id="a", rect=(10, 20, 30, 40))},
    )
    counting = CountingScreen(paint_patches(600, 400, {"a": Rect(0, 0, 10, 10)})[0])
    locator = AnchorLocator(profile, counting)
    assert locator.locate("a").as_tuple() == (10, 20, 30, 40)
    assert counting.captures == 0
    assert screen.capture().shape == (400, 600, 3)


def test_parent_cycle_raises(tmp_path: Path) -> None:
    profile = Profile(
        schema=1,
        profile="p",
        width=10,
        height=10,
        dpi_scale=1.0,
        elements={
            "a": ElementSpec(element_id="a", parent="b", anchors=(AnchorSpec(path="a.png"),)),
            "b": ElementSpec(element_id="b", parent="a", anchors=(AnchorSpec(path="b.png"),)),
        },
    )
    locator = AnchorLocator(profile, ImageScreenSource(paint_patches(600, 400, {"x": Rect(0, 0, 10, 10)})[0]))
    with pytest.raises(TreeConfigError, match="环"):
        locator.locate("a")


def test_validate_report_ok_and_problems(tmp_path: Path) -> None:
    profile, _, screen = _build_profile(tmp_path)
    locator = AnchorLocator(profile, screen, matcher=AnchorMatcher(threshold=0.9))
    report = locator.validate(required_ids=profile.element_ids())
    assert report.ok, report.problems
    assert set(report.checked) == {"main_window", "input_box"}

    (tmp_path / "anchors" / "input_box.png").unlink()
    report = locator.validate(required_ids=profile.element_ids())
    assert not report.ok
    assert any("文件不存在" in problem for problem in report.problems)


def test_performance_cached_locate_is_fast(tmp_path: Path) -> None:
    profile, _, screen = _build_profile(tmp_path)
    locator = AnchorLocator(profile, screen)
    locator.locate("input_box")
    start = time.perf_counter()
    for _ in range(50):
        locator.locate("input_box")
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"缓存后 50 次定位耗时 {elapsed:.3f}s"
