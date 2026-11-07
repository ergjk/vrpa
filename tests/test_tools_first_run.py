"""first-run 首跑向导测试（不打开微信、不发送）。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from wechat_agent.tools.first_run import FirstRunChecker, build_first_run, next_steps, run_first_run


class _FakeChecker(FirstRunChecker):
    def __init__(self, root: Path) -> None:
        self.root = root

    def python_version(self) -> tuple[int, ...]:
        return (3, 14, 7)

    def find_spec(self, module: str) -> bool:
        return True

    def display(self) -> SimpleNamespace:
        return SimpleNamespace(width=1920, height=1080, dpi_scale=1.5, detected=True)

    def find_window(self, config: object) -> tuple[SimpleNamespace, str]:
        return SimpleNamespace(title="微信", process_name="Weixin.exe"), ""

    def write_probe(self, data_dir: Path) -> str:
        return str(data_dir)

    def is_venv(self) -> bool:
        return True

    def is_admin(self) -> bool:
        return True

    def api_key_present(self) -> bool:
        return True


def _config(root: Path, *, dry_run: bool = True, allow_real: bool = False) -> SimpleNamespace:
    (root / "uia_tree").mkdir(parents=True, exist_ok=True)
    (root / "uia_tree" / "1920x1080@1.5.json").write_text("{}", encoding="utf-8")
    persona = root / "persona.txt"
    persona.write_text("测试人设", encoding="utf-8")
    return SimpleNamespace(
        data_dir=root,
        llm=SimpleNamespace(persona_path=str(persona)),
        wechat=SimpleNamespace(window_title_regex="^微信$", process_names=("Weixin.exe",)),
        uia_tree=SimpleNamespace(profile="auto", dir=str(root / "uia_tree"), profile_path=None),
        app=SimpleNamespace(dry_run=dry_run),
        safety=SimpleNamespace(allow_real_send=allow_real, real_send_allowlist=("王衢665",)),
    )


def test_first_run_ready(tmp_path: Path) -> None:
    payload = build_first_run(_config(tmp_path), checker=_FakeChecker(tmp_path))
    assert payload["ready"] is True
    assert payload["next"]
    assert payload["summary"]["fail"] == 0
    assert any(item["id"] == "uia.profile" and item["status"] == "PASS" for item in payload["items"])


def test_first_run_warns_on_missing_profile_and_unsafe_switch(tmp_path: Path) -> None:
    config = _config(tmp_path, dry_run=False, allow_real=True)
    (tmp_path / "uia_tree" / "1920x1080@1.5.json").unlink()
    payload = build_first_run(config, checker=_FakeChecker(tmp_path))
    assert payload["ready"] is False
    assert any(item["id"] == "uia.profile" and item["status"] == "WARN" for item in payload["items"])
    assert any(item["id"] == "safety.allow_real_send" and item["status"] == "WARN" for item in payload["items"])


def test_next_steps_includes_venv_and_wechat() -> None:
    steps = next_steps(
        {"venv": False, "deps": False, "key": False, "wechat": False, "profile": True, "admin": False, "dry_run": True}
    )
    assert any("venv" in step for step in steps)
    assert any("微信" in step for step in steps)
    assert any("pip install" in step for step in steps)
    assert any(".env" in step for step in steps)
    assert any("管理员" in step for step in steps)


def test_first_run_help_does_not_load_config() -> None:
    assert run_first_run(["--help"]) == 0


def test_first_run_json_ready(tmp_path: Path, capsys: object) -> None:
    config = _config(tmp_path)
    payload = build_first_run(config, checker=_FakeChecker(tmp_path))
    assert payload["exit_code"] == 0


def test_checker_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import ctypes

    checker = FirstRunChecker()
    assert isinstance(checker.is_venv(), bool)
    assert isinstance(checker.is_admin(), bool)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    assert checker.api_key_present() is True
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert checker.api_key_present() is False
    monkeypatch.setattr(
        ctypes.windll.shell32,
        "IsUserAnAdmin",
        lambda: (_ for _ in ()).throw(OSError("no shell32")),
    )
    assert checker.is_admin() is False


def test_checker_profile_path(tmp_path: Path) -> None:
    checker = FirstRunChecker()
    display = SimpleNamespace(width=1920, height=1080, dpi_scale=1.5)
    config = _config(tmp_path)
    assert checker.profile_path(config, display) == tmp_path / "uia_tree" / "1920x1080@1.5.json"
    config.uia_tree.profile_path = str(tmp_path / "custom.json")  # type: ignore[attr-defined]
    assert checker.profile_path(config, display) == tmp_path / "custom.json"


def test_display_failure_marks_profile_warn(tmp_path: Path) -> None:
    class _NoDisplay(_FakeChecker):
        def display(self) -> SimpleNamespace:
            raise OSError("no display")

    payload = build_first_run(_config(tmp_path), checker=_NoDisplay(tmp_path))
    assert any(item["id"] == "uia.profile" and item["status"] == "WARN" for item in payload["items"])


def test_run_first_run_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import wechat_agent.core.config as config_module
    import wechat_agent.tools.first_run as first_run_module

    config = _config(tmp_path)
    monkeypatch.setattr(config_module, "load_config", lambda path=None: config)
    monkeypatch.setattr(
        first_run_module,
        "build_first_run",
        lambda cfg: {
            "ok": True,
            "fatal": False,
            "exit_code": 0,
            "summary": {"pass": 1, "warn": 0, "fail": 0},
            "items": [],
            "next": [],
            "ready": True,
        },
    )
    assert run_first_run(["--json"]) == 0
    assert '"ready": true' in capsys.readouterr().out


def test_run_first_run_text_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import wechat_agent.core.config as config_module
    import wechat_agent.tools.first_run as first_run_module

    config = _config(tmp_path)
    monkeypatch.setattr(config_module, "load_config", lambda path=None: config)
    monkeypatch.setattr(
        first_run_module,
        "build_first_run",
        lambda cfg: {
            "ok": True,
            "fatal": False,
            "exit_code": 0,
            "summary": {"pass": 0, "warn": 1, "fail": 0},
            "items": [{"id": "x", "title": "项", "status": "WARN", "detail": "细节", "fatal": False}],
            "next": ["下一步 A"],
            "ready": False,
        },
    )
    assert run_first_run([]) == 0
    out = capsys.readouterr().out
    assert "NEXT:" in out and "下一步 A" in out
