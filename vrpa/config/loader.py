"""通用配置加载内核：YAML 解析、schema 版本检查、v1 -> v2 自动升级、默认值深度合并。

schema 演进：
    v1: 顶层平台段（如 ``<kind>: {...}``）
    v2: ``platform: {kind: <平台>, options: {...}}``

升级由框架内核完成，但**平台段名到 kind 的映射由插件提供**（``PlatformRegistry.legacy_section_map``），
因此内核保持平台无关。
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vrpa.errors import ConfigError

__all__ = [
    "SCHEMA_VERSION",
    "SUPPORTED_SCHEMAS",
    "MigrationReport",
    "check_schema",
    "load_document",
    "load_yaml_document",
    "merge_defaults",
    "upgrade_document",
]

SCHEMA_VERSION = 2
SUPPORTED_SCHEMAS: tuple[int, ...] = (1, SCHEMA_VERSION)


@dataclass(frozen=True)
class MigrationReport:
    """一次配置迁移的结果（用于打印提示 / selftest 记录）。"""

    from_schema: int
    to_schema: int
    notes: tuple[str, ...] = ()

    def message(self) -> str:
        detail = "；".join(self.notes)
        base = f"检测到 schema v{self.from_schema} 配置，已自动升级为 v{self.to_schema}"
        return f"{base}（{detail}）" if detail else base


def load_yaml_document(path: Path) -> dict[str, Any]:
    """读取并解析 YAML 文档（PyYAML 延迟导入，缺失时给可读错误）。"""
    try:
        import yaml  # type: ignore[import-untyped]  # 延迟导入：缺 PyYAML 时给可读错误
    except ModuleNotFoundError as exc:
        raise ConfigError("缺少 PyYAML 依赖：请执行 pip install -r requirements-core.txt") from exc
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件（{path}）：{exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML 解析失败（{path}）：{exc}") from exc
    if data is None:
        raise ConfigError(f"配置文件为空：{path}")
    if not isinstance(data, dict):
        raise ConfigError(f"配置文件顶层必须是映射（dict）：{path}")
    return dict(data)


def check_schema(raw: Mapping[str, Any]) -> int:
    """读取并校验 schema 版本号。"""
    value = raw.get("schema")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"schema 必须是整数版本号，实际为 {value!r}")
    if value not in SUPPORTED_SCHEMAS:
        raise ConfigError(f"不支持的配置 schema={value}（当前支持 {SUPPORTED_SCHEMAS}）")
    return value


def merge_defaults(defaults: Mapping[str, Any], document: Mapping[str, Any]) -> dict[str, Any]:
    """深度合并：``document`` 覆盖 ``defaults``；嵌套 dict 递归合并，其余（含列表）整体替换。"""
    merged: dict[str, Any] = copy.deepcopy(dict(defaults))
    for key, value in document.items():
        base = merged.get(key)
        if isinstance(base, Mapping) and isinstance(value, Mapping):
            merged[key] = merge_defaults(base, value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def upgrade_document(
    raw: Mapping[str, Any],
    *,
    legacy_sections: Mapping[str, str],
) -> tuple[dict[str, Any], MigrationReport | None]:
    """把文档升级到当前 schema；已是当前版本则原样返回（浅拷贝）。"""
    version = check_schema(raw)
    if version == SCHEMA_VERSION:
        return dict(raw), None
    if "platform" in raw:
        raise ConfigError("schema v1 不应包含 platform 段（该段自 schema v2 起启用）")

    present = [name for name in legacy_sections if name in raw]
    if len(present) != 1:
        raise ConfigError(
            f"schema v1 配置需要且只能包含一个平台段（候选：{sorted(legacy_sections)}；实际找到：{present or '无'}）"
        )

    section_name = present[0]
    kind = legacy_sections[section_name]
    section_value = raw[section_name]
    if not isinstance(section_value, dict):
        raise ConfigError(f"schema v1 平台段 {section_name} 必须是映射（dict），实际为 {type(section_value).__name__}")
    upgraded: dict[str, Any] = {}
    for key, value in raw.items():
        if key == "schema" or key in legacy_sections:
            continue
        upgraded[key] = copy.deepcopy(value)
    upgraded["schema"] = SCHEMA_VERSION
    upgraded["platform"] = {
        "kind": kind,
        "options": copy.deepcopy(section_value),
    }
    notes = (f"平台段 {section_name} -> platform.kind={kind} / platform.options",)
    return upgraded, MigrationReport(from_schema=version, to_schema=SCHEMA_VERSION, notes=notes)


def load_document(
    path: Path,
    *,
    legacy_sections: Mapping[str, str] | None = None,
    defaults: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], MigrationReport | None]:
    """加载 -> 升级 -> 合并默认值，返回可校验的 v2 文档。"""
    raw = load_yaml_document(path)
    document, report = upgrade_document(raw, legacy_sections=legacy_sections or {})
    if defaults:
        document = merge_defaults(defaults, document)
    return document, report
