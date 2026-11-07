"""受控真实发送循环测试：所有拒绝路径必须在构建 UI 之前返回。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from wechat_agent.tools.run_live import run_live

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "config.yaml").read_text(encoding="utf-8")


def _config(tmp_path: Path, *, dry_run: bool = True, allow: bool = False, allowlist: str = '["王衢665"]') -> Path:
    text = BASE.replace("data_dir: ./data", f"data_dir: {tmp_path.as_posix()}/data", 1)
    if not dry_run:
        text = text.replace("dry_run: true", "dry_run: false", 1)
    if allow:
        text = text.replace("allow_real_send: false", "allow_real_send: true", 1)
    text = text.replace('real_send_allowlist: ["文件传输助手", "王衢665"]', f"real_send_allowlist: {allowlist}", 1)
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _args(config: Path, **overrides: object) -> SimpleNamespace:
    data = {
        "chat": "王衢665",
        "config": str(config),
        "max_sends": 1,
        "interval": 0,
        "i_understand_risk": True,
        "json": True,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_live_rejects_missing_risk(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_live(_args(_config(tmp_path, dry_run=False, allow=True), i_understand_risk=False)) == 2
    assert "i-understand-risk" in capsys.readouterr().err


def test_live_rejects_missing_max_sends(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_live(_args(_config(tmp_path, dry_run=False, allow=True), max_sends=0)) == 2
    assert "max-sends" in capsys.readouterr().err


def test_live_rejects_non_admin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import wechat_agent.tools.run_live as live_module

    monkeypatch.setattr(live_module, "_is_admin", lambda: False)
    assert run_live(_args(_config(tmp_path, dry_run=False, allow=True))) == 2
    assert "管理员" in capsys.readouterr().err


def test_live_rejects_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import wechat_agent.tools.run_live as live_module

    monkeypatch.setattr(live_module, "_is_admin", lambda: True)
    assert run_live(_args(_config(tmp_path, dry_run=True, allow=True))) == 2
    assert "dry_run" in capsys.readouterr().err


def test_live_rejects_allow_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import wechat_agent.tools.run_live as live_module

    monkeypatch.setattr(live_module, "_is_admin", lambda: True)
    assert run_live(_args(_config(tmp_path, dry_run=False, allow=False))) == 2
    assert "allow_real_send" in capsys.readouterr().err


def test_live_rejects_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import wechat_agent.tools.run_live as live_module

    monkeypatch.setattr(live_module, "_is_admin", lambda: True)
    assert run_live(_args(_config(tmp_path, dry_run=False, allow=True, allowlist="[]"))) == 2
    assert "allowlist" in capsys.readouterr().err


def test_live_success_path_with_fakes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import wechat_agent.tools.run_live as live_module

    class _Perception:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def activate(self) -> None:
            pass

        def switch_session(self, chat: str) -> None:
            pass

        def capture(self, chat: str) -> str:
            return "测试消息"

        def scroll_to_bottom(self) -> None:
            pass

    class _Brain:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

    class _Executor:
        def __init__(self, *args: object, **kwargs: object) -> None:
            capture = kwargs.get("capture")
            if callable(capture):
                capture("测试")

    class _Orchestrator:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.machine = SimpleNamespace(state=SimpleNamespace(value="running"))
            self.queue: list[object] = []

        def start(self) -> None:
            pass

        def tick(self, chats: object) -> SimpleNamespace:
            return SimpleNamespace(replies=("自动回复",), events=(), failures=0)

    monkeypatch.setattr(live_module, "_is_admin", lambda: True)
    monkeypatch.setattr(live_module, "WeChatElementTree", _Perception)
    monkeypatch.setattr(live_module, "WeChatWindow", _Perception)
    monkeypatch.setattr(live_module, "PyAutoGuiDriver", _Perception)
    monkeypatch.setattr(live_module, "WeChatPerception", _Perception)
    monkeypatch.setattr(live_module, "WeChatBrain", _Brain)
    monkeypatch.setattr(live_module, "WeChatExecutor", _Executor)
    monkeypatch.setattr(live_module, "Orchestrator", _Orchestrator)
    config = _config(tmp_path, dry_run=False, allow=True)
    code = run_live(_args(config, max_sends=1, interval=0))
    assert code == 0
    out = capsys.readouterr().out
    assert '"sent_count": 1' in out and '"ok": true' in out


def _patch_live_fakes(monkeypatch: pytest.MonkeyPatch, orchestrator_cls: type) -> None:
    import wechat_agent.tools.run_live as live_module

    class _Perception:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def activate(self) -> None:
            pass

        def switch_session(self, chat: str) -> None:
            pass

        def capture(self, chat: str) -> str:
            return "测试消息"

        def scroll_to_bottom(self) -> None:
            pass

    class _Brain:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

    class _Executor:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

    monkeypatch.setattr(live_module, "_is_admin", lambda: True)
    for name in ("WeChatElementTree", "WeChatWindow", "PyAutoGuiDriver", "WeChatPerception"):
        monkeypatch.setattr(live_module, name, _Perception)
    monkeypatch.setattr(live_module, "WeChatBrain", _Brain)
    monkeypatch.setattr(live_module, "WeChatExecutor", _Executor)
    monkeypatch.setattr(live_module, "Orchestrator", orchestrator_cls)


class _NoReplyOrchestrator:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.machine = SimpleNamespace(state=SimpleNamespace(value="running"))
        self.queue: list[object] = []

    def start(self) -> None:
        pass

    def tick(self, chats: object) -> SimpleNamespace:
        return SimpleNamespace(replies=(), events=(), failures=0)


class _FailingOrchestrator:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.machine = SimpleNamespace(state=SimpleNamespace(value="running"))
        self.queue: list[object] = []

    def start(self) -> None:
        pass

    def tick(self, chats: object) -> SimpleNamespace:
        return SimpleNamespace(replies=(), events=("send_failed",), failures=1)


class _RaisingOrchestrator:
    def __init__(self, *args: object, **kwargs: object) -> None:
        from vrpa.errors import ConfigError

        raise ConfigError("fake failure")


def test_live_no_replies_reports_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_live_fakes(monkeypatch, _NoReplyOrchestrator)
    code = run_live(_args(_config(tmp_path, dry_run=False, allow=True), max_sends=2, interval=0, json=False))
    assert code == 1
    assert "RESULT: FAIL" in capsys.readouterr().out


def test_live_failure_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_live_fakes(monkeypatch, _FailingOrchestrator)
    code = run_live(_args(_config(tmp_path, dry_run=False, allow=True), max_sends=2, interval=0))
    assert code == 1
    assert '"failures": 1' in capsys.readouterr().out


def test_live_orchestrator_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_live_fakes(monkeypatch, _RaisingOrchestrator)
    code = run_live(_args(_config(tmp_path, dry_run=False, allow=True), max_sends=1, interval=0))
    assert code != 0
    assert "LIVE ERROR" in capsys.readouterr().err


def test_live_requires_chat(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_live(_args(Path("config.yaml"), chat=None)) == 2
    assert "--chat" in capsys.readouterr().err


def test_is_admin_returns_bool() -> None:
    from wechat_agent.tools.run_live import _is_admin

    assert isinstance(_is_admin(), bool)
