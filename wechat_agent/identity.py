"""身份映射（V1.0，应用层）：手动维护的 TOML，仅用于显示/校验，不写入记忆库。

位置：``data/identity.toml``（被 .gitignore 忽略，可手动编辑、支持注释）
示例：仓库根目录 ``identity.example.toml``

原则：
    - 会话主键 = 会话名；有备注时用备注，无备注时等于昵称（昵称变更会改变主键，建议设备注）；
    - 昵称 = 显示名，可变化，仅用于切会话后的校验与展示；
    - canonical_id 可选，用于未来身份迁移；
    - 绝不记录消息内容（R3）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import tomllib

from vrpa.errors import ConfigError

__all__ = ["ChatIdentity", "GroupIdentity", "IdentityMap", "load_identity"]


@dataclass(frozen=True)
class ChatIdentity:
    canonical_id: str | None = None
    nicknames: tuple[str, ...] = ()


@dataclass(frozen=True)
class GroupIdentity:
    canonical_id: str | None = None
    members: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class IdentityMap:
    chats: dict[str, ChatIdentity] = field(default_factory=dict)
    groups: dict[str, GroupIdentity] = field(default_factory=dict)
    self_nicknames: tuple[str, ...] = ()

    def nicknames_for(self, chat: str) -> tuple[str, ...]:
        entry = self.chats.get(chat)
        return entry.nicknames if entry is not None else ()

    def is_self(self, sender: str | None) -> bool:
        name = (sender or "").strip()
        return bool(name) and name in self.self_nicknames

    def canonical_for(self, chat: str) -> str | None:
        entry = self.chats.get(chat) or self.groups.get(chat)
        return entry.canonical_id if entry is not None else None

    def is_empty(self) -> bool:
        return not self.chats and not self.groups and not self.self_nicknames


def _chat_identity(raw: object, where: str) -> ChatIdentity:
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} 必须是表（table）")
    canonical = raw.get("canonical_id")
    if canonical is not None and not isinstance(canonical, str):
        raise ConfigError(f"{where}.canonical_id 必须是字符串")
    nicknames_raw = raw.get("nicknames", [])
    if isinstance(nicknames_raw, str):
        nicknames = (nicknames_raw.strip(),) if nicknames_raw.strip() else ()
    elif isinstance(nicknames_raw, list):
        nicknames = tuple(str(item).strip() for item in nicknames_raw if str(item).strip())
    else:
        raise ConfigError(f"{where}.nicknames 必须是字符串数组")
    return ChatIdentity(canonical_id=canonical, nicknames=nicknames)


def _group_identity(raw: object, where: str) -> GroupIdentity:
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} 必须是表（table）")
    canonical = raw.get("canonical_id")
    if canonical is not None and not isinstance(canonical, str):
        raise ConfigError(f"{where}.canonical_id 必须是字符串")
    members_raw = raw.get("members", {})
    if not isinstance(members_raw, dict):
        raise ConfigError(f"{where}.members 必须是表（table）")
    members: dict[str, str] = {}
    for nickname, member_id in members_raw.items():
        if not isinstance(member_id, str):
            raise ConfigError(f"{where}.members.{nickname} 必须是字符串")
        members[str(nickname)] = member_id
    return GroupIdentity(canonical_id=canonical, members=members)


def _parse_document(document: object, source: str) -> IdentityMap:
    if not isinstance(document, dict):
        raise ConfigError(f"身份映射 {source} 顶层必须是表（table）")
    chats: dict[str, ChatIdentity] = {}
    groups: dict[str, GroupIdentity] = {}
    self_raw = document.get("self")
    self_nicknames: tuple[str, ...] = ()
    if self_raw is not None:
        self_identity = _chat_identity(self_raw, "self")
        self_nicknames = self_identity.nicknames
    for chat, raw in dict(document.get("chats", {})).items():
        chats[str(chat)] = _chat_identity(raw, f"chats.{chat}")
    for group, raw in dict(document.get("groups", {})).items():
        groups[str(group)] = _group_identity(raw, f"groups.{group}")
    return IdentityMap(chats=chats, groups=groups, self_nicknames=self_nicknames)


def load_identity(data_dir: Path | str) -> IdentityMap:
    """读取 ``data/identity.toml``（不存在则返回空映射）。"""
    root = Path(data_dir)
    toml_path = root / "identity.toml"
    if toml_path.is_file():
        try:
            document = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"身份映射解析失败：{toml_path}（{exc}）") from exc
        return _parse_document(document, str(toml_path))
    json_path = root / "identity.json"
    if json_path.is_file():
        try:
            document = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"身份映射解析失败：{json_path}（{exc}）") from exc
        return _parse_document(document, str(json_path))
    return IdentityMap()
