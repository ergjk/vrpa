"""M1-03/04/05 测试：离线 CLI 链路（calibrate -> validate-tree -> locate）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vision_fixtures import paint_patches, save_png
from vrpa.ports import Rect
from wechat_agent import main as main_module
from wechat_agent.tools.calibrate import (
    _ELEMENT_HINTS,
    _display_to_image_rect,
    _element_label,
    _fit_scale,
    run_calibrate,
)
from wechat_agent.tools.locate import run_locate
from wechat_agent.tools.validate_tree import run_validate_tree

ROOT = Path(__file__).resolve().parents[1]
BASE_TEXT = (ROOT / "config.yaml").read_text(encoding="utf-8")

MAIN = Rect(5, 5, 590, 390)
INPUT = Rect(100, 100, 80, 30)


@pytest.fixture()
def workspace(tmp_path: Path) -> dict[str, Path]:
    screen, _ = paint_patches(600, 400, {"main_window": MAIN, "input_box": INPUT})
    image = save_png(tmp_path / "screen.png", screen)
    config_text = BASE_TEXT.replace("profile: auto", 'profile: "600x400@1"', 1)
    config_text = config_text.replace("data_dir: ./data", f"data_dir: {tmp_path.as_posix()}/data", 1)
    config = tmp_path / "config.yaml"
    config.write_text(config_text, encoding="utf-8")
    return {"config": config, "image": image, "tmp": tmp_path}


def _calibrate(workspace: dict[str, Path], *extra: str) -> int:
    return run_calibrate(
        [
            "--config",
            str(workspace["config"]),
            "--elements",
            "main_window,input_box",
            "--parent",
            "input_box=main_window",
            "--image",
            str(workspace["image"]),
            "--rects",
            "main_window=5,5,590,390;input_box=100,100,80,30",
            *extra,
        ]
    )


def test_offline_calibrate_validate_locate_chain(workspace: dict[str, Path]) -> None:
    assert _calibrate(workspace) == 0
    profile = workspace["tmp"] / "data" / "uia_tree" / "600x400@1.json"
    assert profile.is_file()
    assert (workspace["tmp"] / "data" / "anchors" / "600x400@1" / "input_box.png").is_file()

    assert run_validate_tree(["--config", str(workspace["config"]), "--image", str(workspace["image"])]) == 0
    assert run_locate(["--config", str(workspace["config"]), "--image", str(workspace["image"]), "input_box"]) == 0


def test_locate_json_output(workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    assert _calibrate(workspace) == 0
    capsys.readouterr()
    assert (
        run_locate(
            [
                "--config",
                str(workspace["config"]),
                "--image",
                str(workspace["image"]),
                "--json",
                "input_box",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["rect"] == [100, 100, 80, 30]
    assert payload["score"] > 0.99
    assert payload["profile"] == "600x400@1"


def test_validate_tree_json(workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    assert _calibrate(workspace) == 0
    capsys.readouterr()
    code = run_validate_tree(["--config", str(workspace["config"]), "--image", str(workspace["image"]), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True
    assert set(payload["checked"]) == {"main_window", "input_box"}


def test_validate_tree_fails_when_anchors_missing(workspace: dict[str, Path]) -> None:
    assert _calibrate(workspace) == 0
    (workspace["tmp"] / "data" / "anchors" / "600x400@1" / "input_box.png").unlink()
    assert run_validate_tree(["--config", str(workspace["config"]), "--image", str(workspace["image"])]) == 3


def test_validate_tree_profile_mismatch(workspace: dict[str, Path]) -> None:
    assert _calibrate(workspace) == 0
    wrong, _ = paint_patches(800, 600, {"x": Rect(0, 0, 10, 10)})
    wrong_path = save_png(workspace["tmp"] / "wrong.png", wrong)
    assert run_validate_tree(["--config", str(workspace["config"]), "--image", str(wrong_path)]) == 7


def test_validate_tree_without_profile(workspace: dict[str, Path]) -> None:
    assert run_validate_tree(["--config", str(workspace["config"]), "--image", str(workspace["image"])]) == 3


def test_locate_unknown_element_returns_3(workspace: dict[str, Path]) -> None:
    assert _calibrate(workspace) == 0
    assert run_locate(["--config", str(workspace["config"]), "--image", str(workspace["image"]), "nope"]) == 3


def test_calibrate_refuses_existing_profile_without_force(workspace: dict[str, Path]) -> None:
    assert _calibrate(workspace) == 0
    assert _calibrate(workspace) == 2
    assert _calibrate(workspace, "--force") == 0


def test_calibrate_bad_rects(workspace: dict[str, Path]) -> None:
    code = run_calibrate(
        [
            "--config",
            str(workspace["config"]),
            "--elements",
            "main_window",
            "--image",
            str(workspace["image"]),
            "--rects",
            "main_window=bad",
        ]
    )
    assert code == 2


def test_calibrate_help_and_missing_args(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_calibrate(["--help"]) == 0
    capsys.readouterr()
    assert run_calibrate([]) == 2


def test_main_dispatch_registered_commands(workspace: dict[str, Path]) -> None:
    assert _calibrate(workspace) == 0
    assert (
        main_module.main(["validate-tree", "--config", str(workspace["config"]), "--image", str(workspace["image"])])
        == 0
    )
    assert (
        main_module.main(
            ["locate", "--config", str(workspace["config"]), "--image", str(workspace["image"]), "input_box"]
        )
        == 0
    )


def _write_config(base_text: str, tmp_path: Path, *, extra: str = "") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    text = base_text.replace("profile: auto", 'profile: "600x400@1"', 1)
    text = text.replace("data_dir: ./data", f"data_dir: {tmp_path.as_posix()}/data", 1)
    if extra:
        text = text.replace(
            "  anchors_dir: ./data/anchors    # 锚点图目录（按 profile 分子目录）",
            "  anchors_dir: ./data/anchors    # 锚点图目录（按 profile 分子目录）\n" + extra,
            1,
        )
    config = tmp_path / "config.yaml"
    config.write_text(text, encoding="utf-8")
    return config


def test_cli_export_import_and_external_paths(workspace: dict[str, Path], tmp_path: Path) -> None:
    assert _calibrate(workspace) == 0
    share = workspace["tmp"] / "share"
    assert run_calibrate(["--config", str(workspace["config"]), "--export", str(share)]) == 0
    assert (share / "profile.json").is_file()
    assert (share / "anchors" / "input_box.png").is_file()

    # 1) 外部路径配置：不复制，直接使用分享目录
    external_root = tmp_path / "external"
    external_root.mkdir()
    external_config = _write_config(
        BASE_TEXT,
        external_root,
        extra=f'  profile_path: "{(share / "profile.json").as_posix()}"\n'
        f'  anchors_root: "{(share / "anchors").as_posix()}"',
    )
    assert run_validate_tree(["--config", str(external_config), "--image", str(workspace["image"])]) == 0
    assert run_locate(["--config", str(external_config), "--image", str(workspace["image"]), "input_box"]) == 0

    # 2) 导入到默认 data 路径（新 config）
    imported_root = tmp_path / "imported"
    imported_root.mkdir()
    imported_config = _write_config(BASE_TEXT, imported_root)
    assert run_calibrate(["--config", str(imported_config), "--import", str(share)]) == 0
    assert run_validate_tree(["--config", str(imported_config), "--image", str(workspace["image"])]) == 0
    assert run_locate(["--config", str(imported_config), "--image", str(workspace["image"]), "input_box"]) == 0

    # 3) 重复导入需 --force
    assert run_calibrate(["--config", str(imported_config), "--import", str(share)]) == 3
    assert run_calibrate(["--config", str(imported_config), "--import", str(share), "--force"]) == 0


def test_cli_import_profile_mismatch(workspace: dict[str, Path], tmp_path: Path) -> None:
    assert _calibrate(workspace) == 0
    share = workspace["tmp"] / "share"
    assert run_calibrate(["--config", str(workspace["config"]), "--export", str(share)]) == 0
    wrong, _ = paint_patches(800, 600, {"x": Rect(0, 0, 10, 10)})
    wrong_path = save_png(tmp_path / "wrong.png", wrong)
    imported_config = _write_config(BASE_TEXT, tmp_path / "mismatch")
    assert (
        run_calibrate(
            [
                "--config",
                str(imported_config),
                "--import",
                str(share),
                "--image",
                str(wrong_path),
            ]
        )
        == 7
    )


def test_element_label_contains_index_and_hint() -> None:
    label = _element_label("input_box", 5, 6)
    assert label == "[5/6] input_box — 底部文本输入框"
    assert _element_label("unknown", 1, 6) == "[1/6] unknown"


def test_all_profile_elements_have_hints() -> None:
    for element_id in ("main_window", "chat_title", "search_box", "message_area", "input_box", "send_button"):
        assert element_id in _ELEMENT_HINTS


def test_fit_scale_for_hi_dpi_screenshot() -> None:
    # 物理截图 2560x1440，逻辑屏幕 1280x720（200% 缩放）-> 显示缩小 50%
    assert _fit_scale(2560, 1440, 1280, 720) == 0.5
    assert _fit_scale(1280, 720, 1280, 720) == 1.0
    assert _fit_scale(800, 600, 1280, 720) == 1.0


def test_display_rect_maps_back_to_original_pixels() -> None:
    rect = _display_to_image_rect(10, 20, 110, 70, scale=0.5, image_w=2560, image_h=1440)
    assert rect.as_tuple() == (20, 40, 200, 100)
    clamped = _display_to_image_rect(90, 90, 120, 120, scale=1.0, image_w=100, image_h=100)
    assert clamped.as_tuple() == (90, 90, 10, 10)
