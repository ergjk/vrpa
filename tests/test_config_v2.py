"""M0-F-03 应用层配置 v2 集成测试。

覆盖：schema 2 直读、v1 自动升级（含迁移提示）、未知平台 kind、平台 options 校验失败、
顶层 wechat 段被拒绝、平台默认值合并、schema 版本拒绝、selftest 平台信息。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from wechat_agent.core.config import ConfigError, build_selftest_report, load_config

ROOT = Path(__file__).resolve().parents[1]
BASE_TEXT = (ROOT / "config.yaml").read_text(encoding="utf-8")


def _base_document() -> dict[str, Any]:
    data = yaml.safe_load(BASE_TEXT)
    assert isinstance(data, dict)
    return data


def _write(tmp_path: Path, document: dict[str, Any], name: str = "config.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _v1_document() -> dict[str, Any]:
    document = _base_document()
    document["schema"] = 1
    platform = document.pop("platform")
    document["wechat"] = platform["options"]
    return document


def test_v2_platform_loaded() -> None:
    cfg = load_config(ROOT / "config.yaml")
    assert cfg.schema == 2
    assert cfg.platform_kind == "wechat"
    assert "wechat" in cfg.platform_plugin
    assert cfg.wechat.process_names == ("WeChat.exe", "WeChatAppEx.exe")
    assert cfg.migrations == ()


def test_v1_auto_upgrade_with_migration_notice(tmp_path: Path) -> None:
    path = _write(tmp_path, _v1_document())
    with pytest.warns(UserWarning, match="自动升级"):
        cfg = load_config(path)
    assert cfg.schema == 2
    assert cfg.platform_kind == "wechat"
    assert cfg.migrations and "自动升级" in cfg.migrations[0]
    assert "WeChat.exe" in cfg.wechat.process_names


def test_v1_upgrade_equivalent_to_v2(tmp_path: Path) -> None:
    path = _write(tmp_path, _v1_document())
    with pytest.warns(UserWarning):
        upgraded = load_config(path)
    direct = load_config(ROOT / "config.yaml")
    assert upgraded.wechat == direct.wechat
    assert upgraded.platform_kind == direct.platform_kind


def test_unknown_platform_kind_rejected(tmp_path: Path) -> None:
    document = _base_document()
    document["platform"]["kind"] = "qq"
    with pytest.raises(ConfigError, match="未知平台"):
        load_config(_write(tmp_path, document))


def test_invalid_platform_options_rejected(tmp_path: Path) -> None:
    document = _base_document()
    document["platform"]["options"]["switch_chat"] = "bogus"
    with pytest.raises(ConfigError, match="platform.options"):
        load_config(_write(tmp_path, document))


def test_root_wechat_section_rejected(tmp_path: Path) -> None:
    document = _base_document()
    document["wechat"] = document["platform"]["options"]
    with pytest.raises(ConfigError, match="顶层 wechat 段"):
        load_config(_write(tmp_path, document))


def test_platform_defaults_are_merged(tmp_path: Path) -> None:
    document = _base_document()
    del document["platform"]["options"]["activate_before_action"]
    del document["platform"]["options"]["chat_type_default"]
    cfg = load_config(_write(tmp_path, document))
    assert cfg.wechat.activate_before_action is True
    assert cfg.wechat.chat_type_default == "private"


def test_schema_3_rejected(tmp_path: Path) -> None:
    document = _base_document()
    document["schema"] = 3
    with pytest.raises(ConfigError, match="不支持"):
        load_config(_write(tmp_path, document))


def test_selftest_report_contains_platform() -> None:
    cfg = load_config(ROOT / "config.yaml")
    report = build_selftest_report(cfg)
    assert report["platform"]["kind"] == "wechat"
    assert any(check["name"] == "platform" for check in report["checks"])
    assert report["migrations"] == []
