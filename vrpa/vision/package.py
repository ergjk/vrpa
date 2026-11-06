"""校准包（Profile & Anchors）导入/导出（M1，平台无关）。

分享包目录结构（v1）：
    <package>/
      package.json      # 清单：package_version / profile / dpi_scale / anchor 文件数
      profile.json      # 假 UIA 树 profile（schema=1，锚点路径相对 anchors/）
      anchors/          # 锚点裁剪图（相对 profile.json 同级）
        main_window.png
        input_box.png
        ...

原则：
    - 官方不固化任何第三方截图；包完全由用户自行导出/导入；
    - 锚点图只包含「操作界面元素」裁剪，禁止包含消息内容（红线 R3）；
    - 导入时严格校验 package_version / profile schema / 锚点文件存在性与目标尺寸。
"""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from vrpa.errors import TreeConfigError
from vrpa.vision.profile import Profile, load_profile, save_profile

__all__ = [
    "PACKAGE_ANCHORS_DIR",
    "PACKAGE_MANIFEST",
    "PACKAGE_PROFILE",
    "PACKAGE_VERSION",
    "PackageInfo",
    "export_package",
    "import_package",
    "list_package_files",
]

PACKAGE_VERSION = 1
PACKAGE_MANIFEST = "package.json"
PACKAGE_PROFILE = "profile.json"
PACKAGE_ANCHORS_DIR = "anchors"


@dataclass(frozen=True)
class PackageInfo:
    """导入/导出结果。"""

    root: Path
    profile: Profile
    files: tuple[str, ...]


def list_package_files(profile: Profile) -> list[str]:
    """分享包必须包含的文件（相对包根目录）。"""
    files = [PACKAGE_PROFILE, PACKAGE_MANIFEST]
    for element in profile.elements.values():
        for anchor in element.anchors:
            files.append(f"{PACKAGE_ANCHORS_DIR}/{anchor.path}")
    return files


def export_package(profile: Profile, destination: Path | str, *, force: bool = False) -> PackageInfo:
    """把当前 profile + 锚点图导出为可分享目录。"""
    root = Path(destination)
    if root.exists() and any(root.iterdir()) and not force:
        raise TreeConfigError(f"导出目录非空：{root}（如需覆盖请加 --force）")
    root.mkdir(parents=True, exist_ok=True)

    anchors_root = profile.anchors_root
    if anchors_root is None:
        raise TreeConfigError("导出校准包需要锚点根目录（profile.anchors_root）")
    anchors_target = root / PACKAGE_ANCHORS_DIR
    anchors_target.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for element in profile.elements.values():
        for anchor in element.anchors:
            source = anchors_root / anchor.path
            if not source.is_file():
                raise TreeConfigError(f"锚点图不存在，无法导出：{source}")
            target = anchors_target / anchor.path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(f"{PACKAGE_ANCHORS_DIR}/{anchor.path}")

    # profile.json：锚点路径保持相对 anchors/
    save_profile(profile, root / PACKAGE_PROFILE)
    manifest = {
        "package_version": PACKAGE_VERSION,
        "profile": profile.profile,
        "width": profile.width,
        "height": profile.height,
        "dpi_scale": profile.dpi_scale,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "anchor_files": copied,
        "note": "anchors 仅含操作界面元素裁剪；请勿包含消息内容（红线 R3）",
    }
    (root / PACKAGE_MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    loaded = load_profile(root / PACKAGE_PROFILE, anchors_root=anchors_target)
    return PackageInfo(root=root, profile=loaded, files=tuple(list_package_files(loaded)))


@contextmanager
def _resolve_source(source: Path | str) -> Iterator[Path]:
    """目录直接用；.zip 解压到临时目录。"""
    path = Path(source)
    if path.is_dir():
        yield path
        return
    if path.is_file() and path.suffix.lower() == ".zip":
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(path) as archive:
                archive.extractall(tmp)
            root = Path(tmp)
            # 兼容「zip 内多一层目录」的打包习惯
            if not (root / PACKAGE_PROFILE).is_file() and len(list(root.iterdir())) == 1:
                candidate = next(root.iterdir())
                if candidate.is_dir():
                    root = candidate
            yield root
        return
    raise TreeConfigError(f"校准包不存在或格式不支持：{path}（支持目录或 .zip）")


def _validate_manifest(root: Path) -> dict[str, object]:
    manifest_path = root / PACKAGE_MANIFEST
    if not manifest_path.is_file():
        return {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TreeConfigError(f"package.json 无法解析：{exc}") from exc
    if not isinstance(manifest, dict):
        raise TreeConfigError("package.json 顶层必须是映射")
    version = manifest.get("package_version")
    if version is not None and version != PACKAGE_VERSION:
        raise TreeConfigError(f"校准包版本不受支持：{version}（期望 {PACKAGE_VERSION}）")
    return manifest


def import_package(
    source: Path | str,
    *,
    profile_target: Path | str,
    anchors_target: Path | str,
    force: bool = False,
) -> PackageInfo:
    """导入他人分享的校准包到本机目标路径（严格校验后复制）。"""
    profile_destination = Path(profile_target)
    anchors_destination = Path(anchors_target)
    if not force and (profile_destination.exists() or anchors_destination.exists()):
        raise TreeConfigError(
            f"目标已存在：profile={profile_destination} anchors={anchors_destination}（如需覆盖请加 --force）"
        )

    with _resolve_source(source) as root:
        profile_path = root / PACKAGE_PROFILE
        anchors_source = root / PACKAGE_ANCHORS_DIR
        if not profile_path.is_file():
            raise TreeConfigError(f"校准包缺少 {PACKAGE_PROFILE}：{root}")
        if not anchors_source.is_dir():
            raise TreeConfigError(f"校准包缺少 {PACKAGE_ANCHORS_DIR}/：{root}")
        _validate_manifest(root)
        profile = load_profile(profile_path, anchors_root=anchors_source)
        problems = profile.validate(
            required_ids=profile.element_ids(),
            check_anchor_files=True,
        )
        if problems:
            raise TreeConfigError("校准包校验失败：" + "；".join(problems[:6]))

        profile_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(profile_path, profile_destination)
        anchors_destination.mkdir(parents=True, exist_ok=True)
        shutil.copytree(anchors_source, anchors_destination, dirs_exist_ok=True)

    imported = load_profile(profile_destination, anchors_root=anchors_destination)
    return PackageInfo(root=root, profile=imported, files=tuple(list_package_files(imported)))
