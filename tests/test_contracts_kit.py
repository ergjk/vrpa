"""M0-F-04 适配器合规测试套件测试（vrpa.testing.contracts）。

覆盖：
    1. Fake 适配器全绿；
    2. 各类破坏性适配器被准确检出（身份 / 能力 / 插件 kind / profile / parser / 端口）；
    3. 报告渲染与 JSON；
    4. CLI 入口（成功 / JSON / 加载失败退出码）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest

from vrpa.config.plugin import PlatformMeta
from vrpa.ports import Ports
from vrpa.testing.contracts import ContractCheck, ContractReport, load_adapter, main, run_all
from vrpa.testing.fakes import FakeConfigPlugin, FakePlatformAdapter

EXPECTED_CHECKS = {
    "adapter.identity",
    "adapter.capabilities",
    "adapter.config_plugin",
    "adapter.element_tree_profile_spec",
    "adapter.parser_pack",
    "adapter.create_ports",
    "ports.smoke",
    "adapter.create_ports.idempotent",
    "adapter.info",
    "adapter.describe",
}


def _failed_names(report: ContractReport) -> set[str]:
    return {check.name for check in report.failed}


def test_fake_adapter_passes_all_contracts() -> None:
    report = run_all(FakePlatformAdapter())
    assert report.ok, report.render()
    assert {check.name for check in report.checks} == EXPECTED_CHECKS
    text = report.render()
    assert "RESULT: PASS" in text
    assert "adapter : fake v1.0" in text


def test_report_to_dict_is_json_serializable() -> None:
    report = run_all(FakePlatformAdapter())
    payload = report.to_dict()
    text = json.dumps(payload, ensure_ascii=False)
    assert payload["ok"] is True
    assert payload["adapter"]["kind"] == "fake"
    assert len(payload["checks"]) == len(EXPECTED_CHECKS)
    assert "RESULT" not in text


def test_broken_identity_detected() -> None:
    class EmptyKindAdapter(FakePlatformAdapter):
        kind = ""

    report = run_all(EmptyKindAdapter())
    assert not report.ok
    assert "adapter.identity" in _failed_names(report)


def test_broken_capabilities_detected() -> None:
    class EmptyCapabilitiesAdapter(FakePlatformAdapter):
        def capabilities(self) -> frozenset[str]:
            return frozenset()

    report = run_all(EmptyCapabilitiesAdapter())
    assert not report.ok
    assert "adapter.capabilities" in _failed_names(report)


def test_broken_config_plugin_kind_detected() -> None:
    class OtherPlugin(FakeConfigPlugin):
        kind = "other"

    class MismatchedPluginAdapter(FakePlatformAdapter):
        def config_plugin(self) -> FakeConfigPlugin:
            return OtherPlugin()

    report = run_all(MismatchedPluginAdapter())
    assert not report.ok
    assert "adapter.config_plugin" in _failed_names(report)


def test_broken_profile_spec_detected() -> None:
    class EmptySpecAdapter(FakePlatformAdapter):
        def element_tree_profile_spec(self) -> Mapping[str, Any]:
            return {}

    report = run_all(EmptySpecAdapter())
    assert not report.ok
    assert "adapter.element_tree_profile_spec" in _failed_names(report)


def test_broken_parser_pack_detected() -> None:
    class EmptyPackAdapter(FakePlatformAdapter):
        def parser_pack(self) -> Mapping[str, Any]:
            return {"strategies": []}

    report = run_all(EmptyPackAdapter())
    assert not report.ok
    assert "adapter.parser_pack" in _failed_names(report)


def test_broken_create_ports_detected() -> None:
    report = run_all(FakePlatformAdapter(fail_ports=True))
    assert not report.ok
    assert {"adapter.create_ports", "ports.smoke"} <= _failed_names(report)


def test_wrong_ports_type_detected() -> None:
    class WrongPortsAdapter(FakePlatformAdapter):
        def create_ports(self, options: Any = None) -> Ports:  # type: ignore[override]
            return object()  # type: ignore[return-value]

    report = run_all(WrongPortsAdapter())
    assert not report.ok
    assert "adapter.create_ports" in _failed_names(report)


def test_plugin_meta_kind_mismatch_detected() -> None:
    class WrongMetaPlugin(FakeConfigPlugin):
        def meta(self) -> PlatformMeta:
            return PlatformMeta(kind="other", display_name="Fake", plugin_version="1.0")

    class WrongMetaAdapter(FakePlatformAdapter):
        def config_plugin(self) -> FakeConfigPlugin:
            return WrongMetaPlugin()

    report = run_all(WrongMetaAdapter())
    assert not report.ok
    assert "adapter.config_plugin" in _failed_names(report)


def test_load_adapter_accepts_class_spec() -> None:
    adapter = load_adapter("vrpa.testing.fakes:FakePlatformAdapter")
    assert adapter.kind == "fake"


def test_load_adapter_rejects_bad_spec() -> None:
    with pytest.raises(ValueError, match="需要"):
        load_adapter("no-colon")
    with pytest.raises(ValueError, match="未实现 PlatformAdapter"):
        load_adapter("builtins:len")


def test_cli_success(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--adapter", "vrpa.testing.fakes:FakePlatformAdapter"])
    out = capsys.readouterr().out
    assert code == 0
    assert "RESULT: PASS" in out


def test_cli_json(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--adapter", "vrpa.testing.fakes:FakePlatformAdapter", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True


def test_cli_load_failure_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--adapter", "not_a_real_module:Adapter"])
    assert code == 2
    assert "无法加载适配器" in capsys.readouterr().err


def test_contract_check_dataclass() -> None:
    check = ContractCheck(name="x", ok=False, detail="bad")
    assert check.ok is False and check.detail == "bad"
    report = ContractReport(adapter_kind="fake", adapter_version="1.0", checks=(check,))
    assert report.ok is False
    assert report.failed == (check,)
