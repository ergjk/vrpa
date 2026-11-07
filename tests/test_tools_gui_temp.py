"""GUI 临时解锁辅助函数测试（不打开窗口、不发送）。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from wechat_agent.tools.gui import _cleanup_temp, _make_temp_config


def _base_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        "app:\n  dry_run: true\n  data_dir: ./data\n"
        'safety:\n  allow_real_send: false\n  real_send_allowlist: ["A", "B"]\n',
        encoding="utf-8",
    )
    return path


def test_make_temp_config_unlocks_only_temp(tmp_path: Path) -> None:
    base = _base_config(tmp_path)
    before = base.read_text(encoding="utf-8")
    temp = _make_temp_config(str(base), "王衢665")
    try:
        data = yaml.safe_load(temp.read_text(encoding="utf-8"))
        assert data["app"]["dry_run"] is False
        assert data["safety"]["allow_real_send"] is True
        assert data["safety"]["real_send_allowlist"] == ["王衢665"]
    finally:
        _cleanup_temp(temp)
    assert not temp.exists()
    assert base.read_text(encoding="utf-8") == before  # 主配置未被修改


def test_cleanup_temp_ignores_missing() -> None:
    _cleanup_temp(None)
    _cleanup_temp(Path("definitely-not-exists-vrpa.yaml"))


def test_make_temp_config_rejects_bad_root(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- not-a-mapping\n", encoding="utf-8")
    with pytest.raises(ValueError):
        _make_temp_config(str(bad), "王衢665")
