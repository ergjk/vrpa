"""M0-F-04 平台适配器契约与注册表测试（vrpa.platform）。"""

from __future__ import annotations

import pytest

from vrpa.errors import ConfigError
from vrpa.platform import (
    CAPABILITY_GROUP_CHAT,
    CAPABILITY_TEXT_ONLY,
    AdapterInfo,
    AdapterRegistry,
    is_platform_adapter,
)
from vrpa.ports import Ports
from vrpa.testing.fakes import FakeConfigPlugin, FakePlatformAdapter


def test_capability_constants() -> None:
    assert CAPABILITY_TEXT_ONLY == "text_only"
    assert CAPABILITY_GROUP_CHAT == "group_chat"


def test_is_platform_adapter_structural() -> None:
    assert is_platform_adapter(FakePlatformAdapter()) is True

    class NotAnAdapter:
        kind = "broken"

    assert is_platform_adapter(NotAnAdapter()) is False
    assert is_platform_adapter(object()) is False


def test_registry_register_get_and_create() -> None:
    registry = AdapterRegistry()
    adapter = FakePlatformAdapter()
    registry.register(adapter)
    assert registry.kinds() == ("fake",)
    assert registry.get("fake") is adapter
    ports = registry.create("fake", {"enabled": True})
    assert isinstance(ports, Ports)
    assert registry.describe_all() == {"fake": adapter.describe()}


def test_registry_rejects_duplicate_and_unknown() -> None:
    registry = AdapterRegistry()
    registry.register(FakePlatformAdapter())
    with pytest.raises(ConfigError, match="重复注册"):
        registry.register(FakePlatformAdapter())
    with pytest.raises(ConfigError, match="未知平台适配器"):
        registry.get("qq")
    with pytest.raises(ConfigError, match="未知平台适配器"):
        registry.create("nope")


def test_registry_rejects_empty_kind_and_non_adapter() -> None:
    class EmptyKindAdapter(FakePlatformAdapter):
        kind = ""

    class NotAnAdapter:
        kind = "x"

    registry = AdapterRegistry()
    with pytest.raises(ConfigError, match="缺少非空 kind"):
        registry.register(EmptyKindAdapter())
    with pytest.raises(ConfigError, match="未实现 PlatformAdapter"):
        registry.register(NotAnAdapter())  # type: ignore[arg-type]


def test_registry_config_plugins() -> None:
    registry = AdapterRegistry()
    adapter = FakePlatformAdapter()
    registry.register(adapter)
    plugins = registry.config_plugins()
    assert len(plugins) == 1
    kind, plugin = plugins[0]
    assert kind == "fake"
    assert isinstance(plugin, FakeConfigPlugin)
    assert plugin.kind == adapter.kind


def test_adapter_info_from_adapter() -> None:
    info = AdapterInfo.from_adapter(FakePlatformAdapter())
    assert info.kind == "fake"
    assert info.display_name == "Fake RPA Platform"
    assert info.adapter_version == "1.0"
    assert info.capabilities == ("text_only",)
