"""M0-F-05 微信适配器测试：PlatformAdapter 身份、Ports 装配、AdapterRegistry、契约套件全绿。"""

from __future__ import annotations

from pathlib import Path

import pytest

from vrpa.platform import is_platform_adapter
from vrpa.ports import Brain, ElementTree, Executor, MemoryStore, Perception, Ports
from vrpa.testing.contracts import run_all
from wechat_agent.adapter import ADAPTER, WeChatAdapter, coerce_config
from wechat_agent.adapters import ADAPTER_REGISTRY
from wechat_agent.core.config import Config, build_selftest_report, load_config

ROOT = Path(__file__).resolve().parents[1]
BASE_TEXT = (ROOT / "config.yaml").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clean_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


def _config(tmp_path: Path) -> Config:
    text = BASE_TEXT.replace("data_dir: ./data", f"data_dir: {tmp_path.as_posix()}/data", 1)
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return load_config(path)


def _close(ports: Ports) -> None:
    close = getattr(ports.memory, "close", None)
    if callable(close):
        close()


def test_adapter_identity_and_capabilities() -> None:
    adapter = WeChatAdapter()
    assert is_platform_adapter(adapter)
    assert adapter.kind == "wechat"
    assert adapter.adapter_version == "1.0"
    assert "微信" in adapter.display_name
    capabilities = adapter.capabilities()
    assert {"text_only", "group_chat"} <= set(capabilities)
    assert adapter.describe()


def test_adapter_config_plugin_matches_kind() -> None:
    adapter = WeChatAdapter()
    plugin = adapter.config_plugin()
    assert plugin.kind == adapter.kind
    assert plugin.meta().kind == adapter.kind
    options = plugin.validate_options(
        {
            **plugin.default_options(),
            "window_title_regex": "^(微信|WeChat)$",
            "process_names": ["WeChat.exe"],
        }
    )
    assert options.process_names == ("WeChat.exe",)


def test_adapter_specs() -> None:
    adapter = WeChatAdapter()
    spec = adapter.element_tree_profile_spec()
    assert spec["schema"] == 1
    assert spec["root"] == "main_window"
    assert "input_box" in spec["elements"]
    pack = adapter.parser_pack()
    assert pack["strategies"]
    assert pack["min_samples"] == 15


def test_create_ports_returns_wechat_ports(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    ports = WeChatAdapter().create_ports(cfg)
    try:
        assert isinstance(ports, Ports)
        assert isinstance(ports.element_tree, ElementTree)
        assert isinstance(ports.perception, Perception)
        assert isinstance(ports.executor, Executor)
        assert isinstance(ports.brain, Brain)
        assert isinstance(ports.memory, MemoryStore)
        assert ports.executor.is_dry_run() is True
    finally:
        _close(ports)


def test_contract_suite_is_green_for_wechat_adapter(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    report = run_all(WeChatAdapter(), cfg)
    assert report.ok, report.render()
    assert len(report.checks) == 10


def test_adapter_registry_contains_wechat() -> None:
    assert "wechat" in ADAPTER_REGISTRY.kinds()
    adapter = ADAPTER_REGISTRY.get("wechat")
    assert adapter is ADAPTER
    assert is_platform_adapter(adapter)


def test_adapter_registry_create_ports(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    ports = ADAPTER_REGISTRY.create("wechat", cfg)
    try:
        assert isinstance(ports, Ports)
    finally:
        _close(ports)


def test_selftest_reports_adapter(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    report = build_selftest_report(cfg)
    adapter_report = report["adapter"]
    assert adapter_report["ok"] is True
    assert adapter_report["kind"] == "wechat"
    assert adapter_report["version"] == "1.0"
    assert "group_chat" in adapter_report["capabilities"]
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["adapter"]["ok"] is True


def test_coerce_config_accepts_config(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    assert coerce_config(cfg) is cfg
