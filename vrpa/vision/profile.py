"""假 UIA 树 profile：schema 定义、加载/保存、结构校验（M1-01，平台无关）。

profile 只描述「操作界面」：元素 id、角色、用途、父元素、锚点图；
**绝不**描述或读取消息内容（红线 R3）。

JSON schema（v1）：
    {
      "schema": 1,
      "profile": "1280x720@1",
      "width": 1280, "height": 720, "dpi_scale": 1.0,
      "created_at": "2026-11-06T12:00:00",
      "elements": {
        "main_window": {"role": "container", "purpose": "click", "parent": null,
                        "anchors": ["main_window.png"]},
        "input_box":   {"role": "anchor", "purpose": "input", "parent": "main_window",
                        "anchors": [{"path": "input_box.png", "threshold": 0.9}]}
      }
    }
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from vrpa.errors import TreeConfigError

PROFILE_SCHEMA_VERSION = 1
ROLES: frozenset[str] = frozenset({"container", "region", "anchor"})
PURPOSES: frozenset[str] = frozenset({"click", "input", "drag", "guard", "plugin"})

_ELEMENT_KEYS = {"role", "purpose", "parent", "anchors", "rect", "meta"}


@dataclass(frozen=True)
class AnchorSpec:
    """单张锚点图（路径相对 anchors_root）。"""

    path: str
    threshold: float | None = None
    scales: tuple[float, ...] = ()


@dataclass(frozen=True)
class ElementSpec:
    """一个界面元素。"""

    element_id: str
    role: str = "anchor"
    purpose: str = "click"
    parent: str | None = None
    anchors: tuple[AnchorSpec, ...] = ()
    rect: tuple[int, int, int, int] | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Profile:
    """一份假 UIA 树 profile。"""

    schema: int
    profile: str
    width: int
    height: int
    dpi_scale: float
    elements: Mapping[str, ElementSpec]
    anchors_root: Path | None = None
    created_at: str = ""

    # ------------------------------------------------------------ 查询
    def element_ids(self) -> tuple[str, ...]:
        return tuple(self.elements)

    def get(self, element_id: str) -> ElementSpec:
        try:
            return self.elements[element_id]
        except KeyError as exc:
            raise TreeConfigError(f"profile 中不存在元素 {element_id!r}（已定义：{sorted(self.elements)}）") from exc

    def anchor_path(self, element_id: str, anchor: AnchorSpec) -> Path:
        base = self.anchors_root or Path(".")
        return base / anchor.path

    # ------------------------------------------------------------ 校验
    def validate(
        self,
        *,
        required_ids: Sequence[str] = (),
        check_anchor_files: bool = True,
    ) -> list[str]:
        """返回问题列表（空列表 = 通过）。"""
        problems: list[str] = []
        if self.schema != PROFILE_SCHEMA_VERSION:
            problems.append(f"schema={self.schema} 不受支持（期望 {PROFILE_SCHEMA_VERSION}）")
        if not self.profile.strip():
            problems.append("profile 名不能为空")
        if self.width <= 0 or self.height <= 0:
            problems.append(f"分辨率非法：{self.width}x{self.height}")
        if self.dpi_scale <= 0:
            problems.append(f"DPI 缩放非法：{self.dpi_scale}")
        if not self.elements:
            problems.append("elements 不能为空")

        for element_id, spec in self.elements.items():
            where = f"elements.{element_id}"
            if spec.element_id != element_id:
                problems.append(f"{where}.element_id 与键不一致：{spec.element_id!r}")
            if spec.role not in ROLES:
                problems.append(f"{where}.role={spec.role!r} 不在 {sorted(ROLES)}")
            if spec.purpose not in PURPOSES:
                problems.append(f"{where}.purpose={spec.purpose!r} 不在 {sorted(PURPOSES)}")
            if spec.parent is not None:
                if spec.parent not in self.elements:
                    problems.append(f"{where}.parent={spec.parent!r} 不存在")
                elif spec.parent == element_id:
                    problems.append(f"{where}.parent 指向自身")
            if spec.role != "container" and not spec.anchors and spec.rect is None:
                problems.append(f"{where} 既无 anchors 也无 rect（不可定位）")
            for anchor in spec.anchors:
                if not anchor.path.strip():
                    problems.append(f"{where}.anchors 存在空路径")
                    continue
                if anchor.threshold is not None and not (0.0 < anchor.threshold <= 1.0):
                    problems.append(f"{where}.anchors[{anchor.path}].threshold 越界：{anchor.threshold}")
                if check_anchor_files and self.anchors_root is not None:
                    path = self.anchors_root / anchor.path
                    if not path.is_file():
                        problems.append(f"{where}.anchors 文件不存在：{path}")

        problems.extend(_parent_cycle_problems(self.elements))

        missing = [element_id for element_id in required_ids if element_id not in self.elements]
        if missing:
            problems.append(f"缺少必需元素：{missing}")
        return problems


def _parent_cycle_problems(elements: Mapping[str, ElementSpec]) -> list[str]:
    problems: list[str] = []
    for start in elements:
        seen: list[str] = []
        current: str | None = start
        while current is not None:
            if current in seen:
                problems.append(f"elements.{start} 的 parent 链存在环：{' -> '.join([*seen, current])}")
                break
            seen.append(current)
            spec = elements.get(current)
            current = spec.parent if spec is not None else None
    return problems


# ============================================================================
# 加载 / 保存
# ============================================================================
def _parse_anchor(raw: Any, where: str) -> AnchorSpec:
    if isinstance(raw, str):
        if not raw.strip():
            raise TreeConfigError(f"{where} 锚点路径为空")
        return AnchorSpec(path=raw.strip())
    if isinstance(raw, dict):
        path = raw.get("path")
        if not isinstance(path, str) or not path.strip():
            raise TreeConfigError(f"{where} 锚点缺少非空 path")
        threshold_raw = raw.get("threshold")
        threshold = float(threshold_raw) if isinstance(threshold_raw, (int, float)) else None
        scales_raw = raw.get("scales", ())
        scales: tuple[float, ...] = ()
        if isinstance(scales_raw, (list, tuple)) and scales_raw:
            scales = tuple(float(item) for item in scales_raw)
        return AnchorSpec(path=path.strip(), threshold=threshold, scales=scales)
    raise TreeConfigError(f"{where} 锚点必须是字符串或对象，实际为 {type(raw).__name__}")


def _parse_element(element_id: str, raw: Any) -> ElementSpec:
    where = f"elements.{element_id}"
    if not isinstance(raw, dict):
        raise TreeConfigError(f"{where} 必须是映射")
    unknown = sorted(set(raw) - _ELEMENT_KEYS)
    if unknown:
        raise TreeConfigError(f"{where} 存在未知键：{unknown}")
    anchors_raw = raw.get("anchors", ())
    anchors = tuple(_parse_anchor(item, f"{where}.anchors[{index}]") for index, item in enumerate(anchors_raw))
    rect_raw = raw.get("rect")
    rect: tuple[int, int, int, int] | None = None
    if isinstance(rect_raw, (list, tuple)) and len(rect_raw) == 4:
        rect = tuple(int(value) for value in rect_raw)  # type: ignore[assignment]
    meta = raw.get("meta", {})
    return ElementSpec(
        element_id=element_id,
        role=str(raw.get("role", "anchor")),
        purpose=str(raw.get("purpose", "click")),
        parent=None if raw.get("parent") is None else str(raw["parent"]),
        anchors=anchors,
        rect=rect,
        meta=dict(meta) if isinstance(meta, dict) else {},
    )


def load_profile(path: Path | str, *, anchors_root: Path | None = None, strict: bool = True) -> Profile:
    """读取 profile JSON；结构错误统一抛 ``TreeConfigError``。"""
    profile_path = Path(path)
    if not profile_path.is_file():
        raise TreeConfigError(f"profile 不存在：{profile_path}（先执行 calibrate）")
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TreeConfigError(f"无法解析 profile（{profile_path}）：{exc}") from exc
    if not isinstance(data, dict):
        raise TreeConfigError(f"profile 顶层必须是映射：{profile_path}")

    elements_raw = data.get("elements")
    if not isinstance(elements_raw, dict):
        raise TreeConfigError(f"profile 缺少 elements 映射：{profile_path}")
    elements = {str(key): _parse_element(str(key), value) for key, value in elements_raw.items()}

    profile = Profile(
        schema=int(data.get("schema", 0)),
        profile=str(data.get("profile", "")),
        width=int(data.get("width", 0)),
        height=int(data.get("height", 0)),
        dpi_scale=float(data.get("dpi_scale", 0.0)),
        elements=elements,
        anchors_root=anchors_root,
        created_at=str(data.get("created_at", "")),
    )
    if strict:
        problems = profile.validate()
        if problems:
            raise TreeConfigError(f"profile 校验失败（{profile_path}）：" + "；".join(problems[:6]))
    return profile


def profile_to_document(profile: Profile) -> dict[str, Any]:
    """序列化为 JSON 文档。"""
    elements: dict[str, Any] = {}
    for element_id, spec in profile.elements.items():
        item: dict[str, Any] = {
            "role": spec.role,
            "purpose": spec.purpose,
            "parent": spec.parent,
        }
        if spec.anchors:
            item["anchors"] = [
                {"path": anchor.path, "threshold": anchor.threshold, "scales": list(anchor.scales)}
                if (anchor.threshold is not None or anchor.scales)
                else anchor.path
                for anchor in spec.anchors
            ]
        if spec.rect is not None:
            item["rect"] = list(spec.rect)
        if spec.meta:
            item["meta"] = dict(spec.meta)
        elements[element_id] = item
    return {
        "schema": profile.schema,
        "profile": profile.profile,
        "width": profile.width,
        "height": profile.height,
        "dpi_scale": profile.dpi_scale,
        "created_at": profile.created_at or datetime.now().isoformat(timespec="seconds"),
        "elements": elements,
    }


def save_profile(profile: Profile, path: Path | str) -> Path:
    """原子写入 profile JSON，返回目标路径。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    document = profile_to_document(profile)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, target)
    return target
