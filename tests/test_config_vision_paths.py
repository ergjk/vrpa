"""M1 补充测试：配置外部校准包路径（config.yaml 口子）。"""

from __future__ import annotations

from pathlib import Path

from wechat_agent.core.config import load_config

ROOT = Path(__file__).resolve().parents[1]
BASE_TEXT = (ROOT / "config.yaml").read_text(encoding="utf-8")


def _config(tmp_path: Path, extra_lines: str) -> Path:
    text = BASE_TEXT.replace(
        '  profile: auto                  # auto = "<分辨率>@<DPI>"，如 "2560x1440@1.25"', "  profile: auto"
    )
    text = text.replace(
        "  anchors_dir: ./data/anchors    # 锚点图目录（按 profile 分子目录）",
        "  anchors_dir: ./data/anchors    # 锚点图目录（按 profile 分子目录）\n" + extra_lines,
        1,
    )
    text = text.replace("data_dir: ./data", f"data_dir: {tmp_path.as_posix()}/data", 1)
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_external_profile_and_anchors_paths(tmp_path: Path) -> None:
    external = tmp_path / "shared" / "1280x720@1"
    external.mkdir(parents=True)
    profile = external / "profile.json"
    profile.write_text("{}", encoding="utf-8")
    anchors = external / "anchors"
    anchors.mkdir()
    config = _config(
        tmp_path,
        f'  profile_path: "{profile.as_posix()}"\n  anchors_root: "{anchors.as_posix()}"',
    )
    cfg = load_config(config)
    assert cfg.uia_tree.profile_path == str(profile)
    assert cfg.uia_tree.anchors_root == str(anchors)
    assert cfg.profile_path() == profile
    assert cfg.profile_anchors_dir() == anchors


def test_profile_path_only_defaults_to_sibling_anchors(tmp_path: Path) -> None:
    external = tmp_path / "shared" / "pkg"
    external.mkdir(parents=True)
    profile = external / "profile.json"
    profile.write_text("{}", encoding="utf-8")
    config = _config(tmp_path, f'  profile_path: "{profile.as_posix()}"')
    cfg = load_config(config)
    assert cfg.profile_path() == profile
    assert cfg.profile_anchors_dir() == external / "anchors"


def test_default_profile_paths_unchanged(tmp_path: Path) -> None:
    config = _config(tmp_path, "")
    cfg = load_config(config)
    assert cfg.uia_tree.profile_path is None
    assert cfg.uia_tree.anchors_root is None
    assert cfg.profile_path() == cfg.uia_tree_dir / f"{cfg.profile_name()}.json"
    assert cfg.profile_anchors_dir() == cfg.anchors_dir / cfg.profile_name()
