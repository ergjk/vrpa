"""M4-05 测试：`run --simulate` 全链路（Fake 后端 + dry_run，零真实键鼠）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wechat_agent import main as main_module
from wechat_agent.tools.run import load_scenario, run_run

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "tests" / "fixtures" / "simulation"


@pytest.mark.parametrize("path", sorted(SCENARIOS.glob("*.json")), ids=lambda p: p.stem)
def test_simulation_golden(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    scenario = load_scenario(path)
    code = run_run(["--simulate", "--scenario", str(path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["passed"] is True, payload
    for key, value in scenario.get("expected", {}).items():
        assert payload[key] == value, f"{path.name}: {key}"


def test_basic_flow_sent_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    path = SCENARIOS / "01_basic_flow.json"
    assert run_run(["--simulate", "--scenario", str(path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["sent"] == [{"chat": "张三", "text": "你好呀", "trigger": "auto"}]
    assert payload["writes"] == {"张三": 2}


def test_pause_takeover_stop(capsys: pytest.CaptureFixture[str]) -> None:
    path = SCENARIOS / "03_pause_takeover.json"
    assert run_run(["--simulate", "--scenario", str(path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    triggers = [item["trigger"] for item in payload["sent"]]
    assert "auto" in triggers and "override" in triggers
    assert payload["state"] == "stopped"


def test_circuit_breaker_scenario(capsys: pytest.CaptureFixture[str]) -> None:
    path = SCENARIOS / "04_circuit_breaker.json"
    assert run_run(["--simulate", "--scenario", str(path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["breaker"] == "open"
    assert payload["state"] == "paused"
    assert payload["failures"] == 3


def test_run_requires_a_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_run([]) == 2


def test_missing_scenario(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_run(["--simulate"]) == 2
    assert "场景文件" in capsys.readouterr().err


def test_missing_scenario_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_run(["--simulate", "--scenario", str(tmp_path / "nope.json")]) == 2
    assert "场景文件不存在" in capsys.readouterr().err


def test_main_dispatch_run_simulate() -> None:
    path = SCENARIOS / "01_basic_flow.json"
    assert main_module.main(["run", "--simulate", "--scenario", str(path)]) == 0


def test_simulate_imports_no_real_driver() -> None:
    source = (ROOT / "wechat_agent/tools/run.py").read_text(encoding="utf-8")
    for forbidden in ("pyautogui", "PyAutoGuiDriver", "WeChatPerception", "pyperclip"):
        assert forbidden not in source, f"simulate 不得依赖真实输入：{forbidden}"
