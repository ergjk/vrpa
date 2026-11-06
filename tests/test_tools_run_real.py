"""真实 dry-run 链路测试：Fake 感知 + 真实双库/解析/去重/执行器 dry_run。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from vrpa.errors import ConfigError
from wechat_agent.core.config import load_config
from wechat_agent.tools.run import ScriptedBrain, ScriptedPerception
from wechat_agent.tools.run_real import EchoBrain, execute_dry_run, run_real

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "config.yaml").read_text(encoding="utf-8")

CAPTURE = "三\n2026年11月07日  2:16\n你好\n\n三\n2026年11月07日  2:17\n在吗"


def _config(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(BASE.replace("data_dir: ./data", f"data_dir: {tmp_path.as_posix()}/data", 1), encoding="utf-8")
    return load_config(path)


def test_execute_dry_run_with_injected_brain(tmp_path: Path) -> None:
    config = _config(tmp_path)
    payload = execute_dry_run(
        config,
        perception=ScriptedPerception({"张三": [CAPTURE]}),
        chat="张三",
        ticks=1,
        brain=ScriptedBrain({"张三": ["你好呀"]}),
    )
    assert payload["ok"] is True
    assert payload["mode"] == "injected"
    assert payload["captured"] == 2
    assert payload["ingested"] == 2
    assert payload["replies"] == ["你好呀"]
    assert payload["writes"] == 3  # 2 条入 + 1 条 dry_run 回写
    assert payload["dry_run"] is True


def test_execute_dry_run_echo_mode_without_key(tmp_path: Path) -> None:
    config = _config(tmp_path)
    payload = execute_dry_run(
        config,
        perception=ScriptedPerception({"张三": [CAPTURE]}),
        chat="张三",
        ticks=1,
    )
    assert payload["mode"] == "echo"
    assert payload["replies"] and payload["replies"][0].startswith("[dry-run echo]")
    assert payload["dry_run"] is True


def test_execute_refuses_dry_run_false(tmp_path: Path) -> None:
    _config(tmp_path)
    text = (tmp_path / "config.yaml").read_text(encoding="utf-8").replace("dry_run: true", "dry_run: false", 1)
    bad = tmp_path / "bad.yaml"
    bad.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="dry_run=true"):
        execute_dry_run(
            load_config(bad),
            perception=ScriptedPerception({"张三": [CAPTURE]}),
            chat="张三",
        )


def test_run_real_requires_chat_and_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = _config(tmp_path)
    args = SimpleNamespace(chat=None, config=str(config.path), ticks=1, llm=False, json=True)
    assert run_real(args) == 2

    text = (tmp_path / "config.yaml").read_text(encoding="utf-8").replace("dry_run: true", "dry_run: false", 1)
    bad = tmp_path / "bad.yaml"
    bad.write_text(text, encoding="utf-8")
    args_bad = SimpleNamespace(chat="张三", config=str(bad), ticks=1, llm=False, json=True)
    assert run_real(args_bad) == 2
    assert "dry_run=true" in capsys.readouterr().err


def test_echo_brain_is_offline() -> None:
    result = EchoBrain().generate([{"role": "user", "content": "hi"}])
    assert result.text.startswith("[dry-run echo]") and result.model == "echo"
