"""M2-05 测试：probe 采集诊断命令（离线 --text，不落库/不回复）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wechat_agent import main as main_module
from wechat_agent.tools.probe import run_probe

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "parser_samples" / "02_timestamp_short.txt"


def test_probe_text_mode(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_probe(["--text", str(SAMPLE)]) == 0
    out = capsys.readouterr().out
    assert "source   : file" in out
    assert "messages : 2" in out
    assert "strategy: timestamp_prefix" in out
    assert "RESULT: OK" in out


def test_probe_json_mode(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_probe(["--text", str(SAMPLE), "--json", "--limit", "1"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["source"] == "file"
    assert payload["message_count"] == 2
    assert payload["strategy"] == "timestamp_prefix"
    assert len(payload["preview"]) == 1
    assert payload["preview"][0]["sender"] == "张三"


def test_probe_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_probe(["--text", str(tmp_path / "nope.txt")]) == 2
    assert "文本文件不存在" in capsys.readouterr().err


def test_probe_main_dispatch() -> None:
    assert main_module.main(["probe", "--text", str(SAMPLE)]) == 0


def test_probe_empty_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    assert run_probe(["--text", str(empty)]) == 0
    out = capsys.readouterr().out
    assert "messages : 0" in out
