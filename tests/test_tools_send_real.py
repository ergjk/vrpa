"""受控真实发送入口测试：所有拒绝路径必须在触碰 UI 前返回。"""

from __future__ import annotations

from pathlib import Path

import pytest

from wechat_agent.tools.send import run_send

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "config.yaml").read_text(encoding="utf-8")


def _config(tmp_path: Path, *, dry_run: bool = True, allow: bool = False) -> Path:
    text = BASE.replace("data_dir: ./data", f"data_dir: {tmp_path.as_posix()}/data", 1)
    if not dry_run:
        text = text.replace("dry_run: true", "dry_run: false", 1)
    if allow:
        text = text.replace("allow_real_send: false", "allow_real_send: true", 1)
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _send(config: Path, *extra: str) -> int:
    return run_send(["--config", str(config), "--chat", "王衢665", "--text", "测试", *extra])


def test_real_send_refuses_without_risk_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _send(_config(tmp_path, dry_run=False, allow=True), "--real") == 2
    assert "i-understand-risk" in capsys.readouterr().err


def test_real_send_refuses_when_dry_run_true(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _send(_config(tmp_path, dry_run=True, allow=True), "--real", "--i-understand-risk") == 2
    assert "dry_run" in capsys.readouterr().err


def test_real_send_refuses_without_allow_switch(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _send(_config(tmp_path, dry_run=False, allow=False), "--real", "--i-understand-risk") == 2
    assert "allow_real_send" in capsys.readouterr().err


def test_real_send_refuses_chat_outside_allowlist(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _config(tmp_path, dry_run=False, allow=True)
    text = path.read_text(encoding="utf-8").replace(
        'real_send_allowlist: ["文件传输助手", "王衢665"]',
        "real_send_allowlist: []",
        1,
    )
    path.write_text(text, encoding="utf-8")
    assert _send(path, "--real", "--i-understand-risk") == 2
    assert "allowlist" in capsys.readouterr().err


def test_default_send_is_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _send(_config(tmp_path)) == 0
    assert "dry_run" in capsys.readouterr().out
