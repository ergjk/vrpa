"""M6-05/06 测试：报告、浸泡、验收清单、send/plugin 命令接线。"""

from __future__ import annotations

import json
from pathlib import Path

from vrpa.memory.db import init_databases
from vrpa.memory.history import HistoryStore
from vrpa.memory.jobs import TaskQueue
from wechat_agent import main as main_module
from wechat_agent.core.config import load_config
from wechat_agent.tools.acceptance import build_acceptance, run_acceptance
from wechat_agent.tools.report import build_report, run_report
from wechat_agent.tools.send import run_send
from wechat_agent.tools.soak import run_soak

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "config.yaml").read_text(encoding="utf-8")


def _config(tmp_path: Path):
    text = BASE.replace("data_dir: ./data", f"data_dir: {tmp_path.as_posix()}/data", 1)
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return load_config(path)


def _seed(config) -> None:
    databases = init_databases(config.data_dir)
    try:
        history = HistoryStore(databases)
        history.append("张三", "你好")
        queue = TaskQueue(databases)
        queue.enqueue("demo", {})
    finally:
        databases.close()


def test_report_generation(tmp_path: Path, capsys) -> None:
    config = _config(tmp_path)
    _seed(config)
    payload = build_report(config)
    assert payload["databases"]["messages"] == 1
    assert payload["databases"]["tasks"] == 1
    assert run_report(["--config", str(config.path), "--json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["output"].endswith(".md")
    assert Path(printed["output"]).is_file()
    assert "运行报告" in Path(printed["output"]).read_text(encoding="utf-8")


def test_soak_runs_simulated_chain(tmp_path: Path, capsys) -> None:
    config = _config(tmp_path)
    assert run_soak(["--config", str(config.path), "--iterations", "3", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["iterations"] == 3
    assert payload["failures"] == 0 and payload["dry_run"] is True
    assert payload["replies"] == 3


def test_acceptance_checklist(tmp_path: Path, capsys) -> None:
    config = _config(tmp_path)
    payload = build_acceptance(config)
    assert payload["dry_run"] is True
    assert any(item["id"] == "safe.dry_run_lock" for item in payload["items"])
    assert payload["summary"]["manual"] > 0
    assert run_acceptance(["--config", str(config.path), "--json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert Path(printed["output"]).is_file()
    assert "真机验收清单" in Path(printed["output"]).read_text(encoding="utf-8")


def test_send_cli_dry_run(tmp_path: Path, capsys) -> None:
    config = _config(tmp_path)
    assert run_send(["--config", str(config.path), "--chat", "张三", "--text", "你好", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == "dry_run" and payload["dry_run"] is True


def test_main_dispatch_m6_commands(tmp_path: Path, capsys) -> None:
    config = _config(tmp_path)
    assert main_module.main(["send", "--config", str(config.path), "--chat", "张三", "--text", "你好"]) == 0
    assert main_module.main(["plugin", "list", "--json"]) == 0
    assert main_module.main(["report", "--config", str(config.path)]) == 0
    assert main_module.main(["soak", "--config", str(config.path), "--iterations", "1"]) == 0
    assert main_module.main(["acceptance", "--config", str(config.path)]) == 0
    capsys.readouterr()
