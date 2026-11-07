"""身份映射测试：手动 TOML / JSON、昵称校验、严格失败。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vrpa.errors import ConfigError
from wechat_agent.identity import load_identity

TOML_TEXT = """
# 手动维护
[chats."王衢665"]
canonical_id = "wxid_test"
nicknames = ["三", "三三"]

[self]
nicknames = ["王"]

[groups."测试群"]
canonical_id = "123@chatroom"
[groups."测试群".members]
"三" = "wxid_member"
"""


def test_load_toml(tmp_path: Path) -> None:
    (tmp_path / "identity.toml").write_text(TOML_TEXT, encoding="utf-8")
    identity = load_identity(tmp_path)
    assert identity.nicknames_for("王衢665") == ("三", "三三")
    assert identity.canonical_for("王衢665") == "wxid_test"
    assert identity.canonical_for("测试群") == "123@chatroom"
    assert identity.groups["测试群"].members["三"] == "wxid_member"
    assert identity.self_nicknames == ("王",)
    assert identity.is_self("王") is True and identity.is_self("三") is False


def test_missing_returns_empty(tmp_path: Path) -> None:
    assert load_identity(tmp_path).is_empty() is True


def test_json_fallback(tmp_path: Path) -> None:
    (tmp_path / "identity.json").write_text(
        json.dumps({"chats": {"王衢665": {"nicknames": "三"}}}, ensure_ascii=False), encoding="utf-8"
    )
    assert load_identity(tmp_path).nicknames_for("王衢665") == ("三",)


def test_invalid_toml_raises(tmp_path: Path) -> None:
    (tmp_path / "identity.toml").write_text("[bad", encoding="utf-8")
    with pytest.raises(ConfigError, match="解析失败"):
        load_identity(tmp_path)
