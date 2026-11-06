"""M0-F-03 框架配置内核测试（vrpa.config）。

覆盖：环境变量解析与旧名告警、schema 检查、v1 -> v2 自动升级、默认值深度合并、
平台插件注册表、通用校验原语的错误语义。

说明：本文件属于应用侧测试，允许出现平台名作为测试数据。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from vrpa.config.env import get_env, warn_legacy_env
from vrpa.config.loader import (
    SCHEMA_VERSION,
    check_schema,
    load_document,
    merge_defaults,
    upgrade_document,
)
from vrpa.config.plugin import PlatformMeta, PlatformRegistry
from vrpa.config.validators import as_str, check_keys, expect_mapping
from vrpa.errors import ConfigError

LEGACY_SECTIONS = {"wechat": "wechat"}


def _write_yaml(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------- env
def test_get_env_primary_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VRPA_CONFIG", "new.yaml")
    monkeypatch.setenv("WECHAT_AGENT_CONFIG", "legacy.yaml")
    assert get_env("VRPA_CONFIG", ("WECHAT_AGENT_CONFIG",)) == "new.yaml"


def test_get_env_legacy_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VRPA_CONFIG", raising=False)
    monkeypatch.setenv("WECHAT_AGENT_CONFIG", "legacy.yaml")
    with pytest.warns(DeprecationWarning, match="WECHAT_AGENT_CONFIG"):
        assert get_env("VRPA_CONFIG", ("WECHAT_AGENT_CONFIG",)) == "legacy.yaml"


def test_get_env_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VRPA_CONFIG", raising=False)
    monkeypatch.delenv("WECHAT_AGENT_CONFIG", raising=False)
    assert get_env("VRPA_CONFIG", ("WECHAT_AGENT_CONFIG",)) is None
    assert get_env("VRPA_CONFIG", ("WECHAT_AGENT_CONFIG",), default="x.yaml") == "x.yaml"


def test_warn_legacy_env_message() -> None:
    with pytest.warns(DeprecationWarning, match="已弃用"):
        warn_legacy_env("OLD_NAME", "NEW_NAME")


# ---------------------------------------------------------------- schema / upgrade
def test_check_schema() -> None:
    assert check_schema({"schema": 2}) == 2
    assert SCHEMA_VERSION == 2
    with pytest.raises(ConfigError, match="schema 必须是整数"):
        check_schema({"schema": "2"})
    with pytest.raises(ConfigError, match="不支持"):
        check_schema({"schema": 3})


def test_upgrade_v1_document() -> None:
    raw = {
        "schema": 1,
        "wechat": {
            "window_title_regex": "^(微信|WeChat)$",
            "process_names": ["WeChat.exe"],
            "activate_before_action": True,
            "chat_type_default": "private",
            "switch_chat": "search_box",
        },
        "app": {"log_level": "INFO"},
    }
    document, report = upgrade_document(raw, legacy_sections=LEGACY_SECTIONS)
    assert document["schema"] == 2
    assert document["platform"]["kind"] == "wechat"
    assert document["platform"]["options"]["process_names"] == ["WeChat.exe"]
    assert "wechat" not in document
    assert report is not None
    assert report.from_schema == 1 and report.to_schema == 2
    assert "自动升级" in report.message()
    assert "platform.kind=wechat" in report.message()


def test_upgrade_current_schema_no_report() -> None:
    raw = {"schema": 2, "platform": {"kind": "wechat", "options": {}}}
    document, report = upgrade_document(raw, legacy_sections=LEGACY_SECTIONS)
    assert report is None
    assert document["platform"]["kind"] == "wechat"


def test_upgrade_rejects_v1_with_platform_section() -> None:
    raw = {"schema": 1, "platform": {"kind": "wechat", "options": {}}}
    with pytest.raises(ConfigError, match="不应包含 platform 段"):
        upgrade_document(raw, legacy_sections=LEGACY_SECTIONS)


def test_upgrade_requires_single_legacy_section() -> None:
    with pytest.raises(ConfigError, match="只能包含一个平台段"):
        upgrade_document({"schema": 1, "app": {}}, legacy_sections=LEGACY_SECTIONS)
    with pytest.raises(ConfigError, match="只能包含一个平台段"):
        upgrade_document(
            {"schema": 1, "wechat": {}, "other": {}},
            legacy_sections={"wechat": "wechat", "other": "other"},
        )


def test_upgrade_rejects_non_mapping_section() -> None:
    with pytest.raises(ConfigError, match="必须是映射"):
        upgrade_document({"schema": 1, "wechat": None}, legacy_sections=LEGACY_SECTIONS)


# ---------------------------------------------------------------- merge / load
def test_merge_defaults_deep() -> None:
    defaults = {"a": {"b": 1, "c": 2}, "items": [1, 2], "flag": True}
    document = {"a": {"b": 9}, "items": [3]}
    merged = merge_defaults(defaults, document)
    assert merged == {"a": {"b": 9, "c": 2}, "items": [3], "flag": True}


def test_merge_defaults_does_not_mutate_inputs() -> None:
    defaults = {"a": {"b": 1}}
    document: dict[str, Any] = {}
    merge_defaults(defaults, document)["a"]["b"] = 99
    assert defaults["a"]["b"] == 1


def test_load_document_v1(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        {
            "schema": 1,
            "wechat": {"process_names": ["WeChat.exe"]},
            "app": {"log_level": "INFO"},
        },
    )
    document, report = load_document(path, legacy_sections=LEGACY_SECTIONS)
    assert document["schema"] == 2
    assert document["platform"]["options"]["process_names"] == ["WeChat.exe"]
    assert report is not None


def test_load_document_merge_defaults(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path, {"schema": 2, "platform": {"kind": "wechat", "options": {}}})
    document, _ = load_document(
        path,
        legacy_sections={},
        defaults={"app": {"log_level": "WARNING", "dry_run": True}},
    )
    assert document["app"]["log_level"] == "WARNING"
    assert document["app"]["dry_run"] is True


# ---------------------------------------------------------------- registry / validators
class _FakePlugin:
    kind = "fake"
    legacy_sections = ("fake_legacy",)

    def meta(self) -> PlatformMeta:
        return PlatformMeta(kind=self.kind, display_name="Fake", plugin_version="0.1")

    def default_options(self) -> dict[str, Any]:
        return {"enabled": True}

    def validate_options(self, options: object) -> dict[str, Any]:
        return dict(expect_mapping(options, "platform.options"))

    def describe(self) -> str:
        return "fake platform"


def test_registry_register_get_and_legacy_map() -> None:
    registry = PlatformRegistry()
    plugin = _FakePlugin()
    registry.register(plugin)
    assert registry.kinds() == ("fake",)
    assert registry.get("fake") is plugin
    assert registry.legacy_section_map() == {"fake_legacy": "fake"}
    with pytest.raises(ConfigError, match="重复注册"):
        registry.register(plugin)
    with pytest.raises(ConfigError, match="未知平台"):
        registry.get("nope")


def test_validators_reject_unknown_keys() -> None:
    with pytest.raises(ConfigError, match="未知键"):
        check_keys({"a": 1, "typo": 2}, ("a",), "x")
    with pytest.raises(ConfigError, match="必须是映射"):
        expect_mapping([], "x")
    with pytest.raises(ConfigError, match="之一"):
        as_str("bogus", "x.choice", choices={"a", "b"})
