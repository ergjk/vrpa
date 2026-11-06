"""M0-F-01 CLI 冒烟测试：入口/帮助/版本/分发/桩退出码/子包可导入。

目的：把 `wechat_agent/main.py` 与各子包 `__init__` 纳入覆盖率门禁，
同时锁定 CLI 行为契约（退出码 + 帮助文本包含全部子命令）。

运行：python -m pytest tests/test_cli.py -q
"""

from __future__ import annotations

import importlib
import json

import pytest

from wechat_agent import main as main_module


def test_no_args_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main_module.main([]) == 0
    out = capsys.readouterr().out
    assert "VRPA-WeChat-Agent" in out
    assert "退出码" in out


def test_help_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert main_module.main(["--help"]) == 0
    out = capsys.readouterr().out
    assert "子命令" in out


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert main_module.main(["--version"]) == 0
    assert "wechat_agent" in capsys.readouterr().out


def test_unknown_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    assert main_module.main(["nope"]) == 2
    assert "未知子命令" in capsys.readouterr().err


def test_unimplemented_subcommand_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    assert main_module.main(["probe"]) == 2
    err = capsys.readouterr().err
    assert "尚未实现" in err


def test_register_handler_unknown_raises() -> None:
    with pytest.raises(KeyError):
        main_module.register_handler("not-exists", lambda argv: 0)


def test_print_help_contains_all_commands(capsys: pytest.CaptureFixture[str]) -> None:
    main_module.print_help()
    out = capsys.readouterr().out
    for name in main_module.COMMANDS:
        assert name in out
    assert "红线" in out


def test_dispatch_returns_ok_for_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main_module.dispatch([]) == main_module.ExitCode.OK
    capsys.readouterr()


def test_selftest_via_main_json(capsys: pytest.CaptureFixture[str]) -> None:
    code = main_module.main(["selftest", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True


def test_subpackages_importable() -> None:
    for name in ("act", "brain", "control", "core", "memory", "perception", "plugins", "tools"):
        module = importlib.import_module(f"wechat_agent.{name}")
        assert module.__name__ == f"wechat_agent.{name}"
