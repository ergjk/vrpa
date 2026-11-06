"""M3-07 测试：去重离线回放（golden 场景）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wechat_agent import main as main_module
from wechat_agent.tools.replay import load_scenario, replay_scenario, run_replay

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "tests" / "fixtures" / "dedup_scenarios"


def _matches(payload: dict, expected: dict) -> bool:
    for key, value in expected.items():
        if key == "alignment" and isinstance(value, dict):
            actual = payload.get("alignment") or {}
            for sub_key, sub_value in value.items():
                if actual.get(sub_key) != sub_value:
                    return False
        elif payload.get(key) != value:
            return False
    return True


@pytest.mark.parametrize("path", sorted(SCENARIOS.glob("*.json")), ids=lambda p: p.stem)
def test_golden_scenarios(path: Path) -> None:
    scenario = load_scenario(path)
    payload = replay_scenario(scenario)
    assert _matches(payload, scenario["expected"]), json.dumps(payload, ensure_ascii=False)


def test_run_replay_cli(capsys: pytest.CaptureFixture[str]) -> None:
    scenario = SCENARIOS / "01_basic_overlap.json"
    assert run_replay(["--scenario", str(scenario)]) == 0
    out = capsys.readouterr().out
    assert "golden    : PASS" in out
    assert "RESULT: OK" in out


def test_run_replay_json(capsys: pytest.CaptureFixture[str]) -> None:
    scenario = SCENARIOS / "05_multi_device_self.json"
    assert run_replay(["--scenario", str(scenario), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["queued"] == ["你好"]
    assert payload["self_messages"] == ["我手机发的"]


def test_run_replay_missing_scenario(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_replay(["--scenario", str(tmp_path / "nope.json")]) == 2
    assert "场景文件不存在" in capsys.readouterr().err


def test_run_replay_bad_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert run_replay(["--scenario", str(bad)]) == 2
    assert "无法解析" in capsys.readouterr().err


def test_main_dispatch_replay() -> None:
    scenario = SCENARIOS / "02_full_duplicate.json"
    assert main_module.main(["replay", "--scenario", str(scenario)]) == 0
