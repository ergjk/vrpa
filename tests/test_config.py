"""M0-02 配置系统单元测试。

覆盖：默认配置加载、显式/auto profile 命名、未知键、类型错误、区间颠倒、
比例越界、红线（allow_ratio_fallback）、静默时段格式、缺段、.env 加载与密钥掩码、
目录创建、selftest 报告结构。

运行：python -m pytest tests/test_config.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from wechat_agent.core.config import (
    ConfigError,
    build_selftest_report,
    load_config,
)

ROOT = Path(__file__).resolve().parents[1]
BASE_TEXT = (ROOT / "config.yaml").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clean_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


def _write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _mutate(old: str, new: str) -> str:
    assert old in BASE_TEXT, f"config.yaml 中未找到基准片段：{old!r}"
    return BASE_TEXT.replace(old, new, 1)


def test_load_root_config() -> None:
    cfg = load_config(ROOT / "config.yaml")
    assert cfg.schema == 1
    assert cfg.app.dry_run is True
    assert cfg.data_dir == (ROOT / "data").resolve()
    assert cfg.uia_tree.allow_ratio_fallback is False
    assert cfg.llm.provider == "deepseek"
    assert cfg.profile_name()


def test_explicit_profile_and_dirs(tmp_path: Path) -> None:
    text = _mutate("profile: auto", 'profile: "1920x1080@1.25"')
    cfg = load_config(_write_config(tmp_path, text))
    assert cfg.profile_name() == "1920x1080@1.25"
    assert cfg.profile_path() == tmp_path / "data" / "uia_tree" / "1920x1080@1.25.json"
    dirs = cfg.ensure_dirs()
    assert all(path.is_dir() for path in dirs)
    assert cfg.profile_anchors_dir().is_dir()


def test_auto_profile_name() -> None:
    cfg = load_config(ROOT / "config.yaml")
    assert re.fullmatch(r"\d{3,5}x\d{3,5}@\d+(?:\.\d+)?", cfg.profile_name())


def test_unknown_key_rejected(tmp_path: Path) -> None:
    text = _mutate("  tick_interval: 2.0", "  tick_interval: 2.0\n  typo_key: 1")
    with pytest.raises(ConfigError, match="未知键"):
        load_config(_write_config(tmp_path, text))


def test_bad_type_rejected(tmp_path: Path) -> None:
    text = _mutate("dry_run: true", "dry_run: 'yes'")
    with pytest.raises(ConfigError, match="布尔值"):
        load_config(_write_config(tmp_path, text))


def test_reversed_range_rejected(tmp_path: Path) -> None:
    text = _mutate("think_delay: [1.5, 5.0]", "think_delay: [5.0, 1.5]")
    with pytest.raises(ConfigError, match="区间下限不能大于上限"):
        load_config(_write_config(tmp_path, text))


def test_ratio_out_of_range_rejected(tmp_path: Path) -> None:
    text = _mutate("from: {x: 0.94, y: 0.14}", "from: {x: 1.94, y: 0.14}")
    with pytest.raises(ConfigError, match="必须 <= 1.0"):
        load_config(_write_config(tmp_path, text))


def test_redline_ratio_fallback_rejected(tmp_path: Path) -> None:
    text = _mutate("allow_ratio_fallback: false", "allow_ratio_fallback: true")
    with pytest.raises(ConfigError, match="红线 R3"):
        load_config(_write_config(tmp_path, text))


def test_bad_quiet_hours_rejected(tmp_path: Path) -> None:
    text = _mutate('quiet_hours: ["01:00-07:30"]', 'quiet_hours: ["25:00-07:30"]')
    with pytest.raises(ConfigError, match="HH:MM-HH:MM"):
        load_config(_write_config(tmp_path, text))


def test_missing_section_rejected(tmp_path: Path) -> None:
    text = re.sub(r"^control:\n(?:  .*\n)+", "", BASE_TEXT, count=1, flags=re.MULTILINE)
    assert "control:" not in text
    with pytest.raises(ConfigError, match="缺少段落"):
        load_config(_write_config(tmp_path, text))


def test_env_loaded_and_masked(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=sk-test-1234567890\n", encoding="utf-8")
    cfg = load_config(_write_config(tmp_path, BASE_TEXT))
    assert cfg.api_key() == "sk-test-1234567890"
    assert cfg.api_key_masked() == "sk-***7890"
    assert "DEEPSEEK_API_KEY" in cfg.env_loaded


def test_masked_when_missing() -> None:
    cfg = load_config(ROOT / "config.yaml")
    assert cfg.api_key() is None
    assert cfg.api_key_masked() == "<未设置>"
    assert cfg.masked_dump()["secrets"]["DEEPSEEK_API_KEY"] == "<未设置>"


def test_selftest_report_structure(tmp_path: Path) -> None:
    cfg = load_config(_write_config(tmp_path, BASE_TEXT))
    report = build_selftest_report(cfg)
    assert report["ok"] is True
    names = [item["name"] for item in report["checks"]]
    assert "config" in names
    assert any(name.startswith("dir:") for name in names)
    assert report["display"]["profile"] == cfg.profile_name()


def test_selftest_pending_flag_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    """--redlines 属 M0-09 交付；在此之前必须明确报错（退出码 2），不能静默忽略。"""
    from wechat_agent.core.config import run_selftest

    assert run_selftest(["--redlines"]) == 2
    err = capsys.readouterr().err
    assert "尚未交付" in err and "M0-09" in err


def test_selftest_unknown_flag_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    from wechat_agent.core.config import run_selftest

    assert run_selftest(["--nonsense"]) == 2
    assert "未知选项" in capsys.readouterr().err


def test_selftest_render_result_pass(tmp_path: Path) -> None:
    """回归：render 内部循环变量不得遮蔽 RESULT 状态（曾出现 "RESULT: ok"）。"""
    from wechat_agent.core.config import render_selftest

    cfg = load_config(_write_config(tmp_path, BASE_TEXT))
    text = render_selftest(build_selftest_report(cfg))
    assert text.splitlines()[-1] == "RESULT: PASS"
