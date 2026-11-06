"""M1-01 测试：profile schema、加载/保存、结构校验。"""

from __future__ import annotations

from pathlib import Path

import pytest

from vision_fixtures import paint_patches, save_png, write_profile_json
from vrpa.errors import TreeConfigError
from vrpa.ports import Rect
from vrpa.vision.profile import (
    PROFILE_SCHEMA_VERSION,
    AnchorSpec,
    ElementSpec,
    Profile,
    load_profile,
    profile_to_document,
    save_profile,
)


def _profile(tmp_path: Path, *, with_anchor: bool = True) -> Profile:
    anchors_root = tmp_path / "anchors"
    anchors_root.mkdir(parents=True, exist_ok=True)
    if with_anchor:
        save_png(anchors_root / "main_window.png", paint_patches(600, 400, {"w": Rect(0, 0, 600, 400)})[0])
    elements = {
        "main_window": ElementSpec(
            element_id="main_window",
            role="container",
            purpose="click",
            parent=None,
            anchors=(AnchorSpec(path="main_window.png"),) if with_anchor else (),
            rect=None if with_anchor else (0, 0, 600, 400),
        )
    }
    return Profile(
        schema=PROFILE_SCHEMA_VERSION,
        profile="600x400@1",
        width=600,
        height=400,
        dpi_scale=1.0,
        elements=elements,
        anchors_root=anchors_root,
    )


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    path = save_profile(profile, tmp_path / "uia_tree" / "600x400@1.json")
    loaded = load_profile(path, anchors_root=tmp_path / "anchors")
    assert loaded.profile == "600x400@1"
    assert loaded.element_ids() == ("main_window",)
    assert loaded.validate() == []
    assert loaded.get("main_window").anchors[0].path == "main_window.png"


def test_profile_document_roundtrip(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    document = profile_to_document(profile)
    assert document["schema"] == 1
    path = tmp_path / "p.json"
    import json

    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    loaded = load_profile(path, anchors_root=tmp_path / "anchors")
    assert loaded.validate(required_ids=["main_window"]) == []


def test_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(TreeConfigError, match="profile 不存在"):
        load_profile(tmp_path / "nope.json")


@pytest.mark.parametrize(
    ("document", "match"),
    [
        ({"schema": 1, "profile": "x", "width": 10, "height": 10, "dpi_scale": 1.0, "elements": {}}, "elements"),
        (
            {"schema": 99, "profile": "x", "width": 10, "height": 10, "dpi_scale": 1.0, "elements": {"a": {}}},
            "elements",
        ),
    ],
)
def test_load_invalid_documents(tmp_path: Path, document: dict[str, object], match: str) -> None:
    path = tmp_path / "bad.json"
    import json

    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(TreeConfigError):
        load_profile(path)


def test_validate_reports_structural_problems(tmp_path: Path) -> None:
    save_png(tmp_path / "anchors" / "a.png", paint_patches(600, 400, {"w": Rect(0, 0, 600, 400)})[0])
    profile = Profile(
        schema=PROFILE_SCHEMA_VERSION,
        profile="",
        width=0,
        height=-1,
        dpi_scale=0.0,
        elements={
            "a": ElementSpec(element_id="b", role="bogus", purpose="nope", parent="missing"),
            "b": ElementSpec(element_id="b", role="anchor", purpose="click", parent="a"),
        },
        anchors_root=tmp_path / "anchors",
    )
    problems = profile.validate(required_ids=["not_there"])
    text = "\n".join(problems)
    assert "profile 名不能为空" in text
    assert "分辨率非法" in text
    assert "role" in text and "purpose" in text
    assert "parent='missing'" in text
    assert "不存在" in text
    assert "缺少必需元素" in text


def test_validate_missing_anchor_file(tmp_path: Path) -> None:
    profile = _profile(tmp_path, with_anchor=True)
    (tmp_path / "anchors" / "main_window.png").unlink()
    problems = profile.validate()
    assert any("文件不存在" in problem for problem in problems)


def test_validate_parent_cycle(tmp_path: Path) -> None:
    profile = Profile(
        schema=PROFILE_SCHEMA_VERSION,
        profile="p",
        width=100,
        height=100,
        dpi_scale=1.0,
        elements={
            "a": ElementSpec(element_id="a", parent="b", rect=(0, 0, 10, 10)),
            "b": ElementSpec(element_id="b", parent="a", rect=(0, 0, 10, 10)),
        },
        anchors_root=tmp_path,
    )
    assert any("环" in problem for problem in profile.validate())


def test_write_profile_json_helper_roundtrip(tmp_path: Path) -> None:
    anchors = tmp_path / "anchors"
    save_png(anchors / "w.png", paint_patches(600, 400, {"w": Rect(0, 0, 600, 400)})[0])
    path = write_profile_json(
        tmp_path / "p.json",
        width=600,
        height=400,
        elements={"w": {"role": "container", "purpose": "click", "parent": None, "anchors": ["w.png"]}},
    )
    loaded = load_profile(path, anchors_root=anchors)
    assert loaded.validate() == []
