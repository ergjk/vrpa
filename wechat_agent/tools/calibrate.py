"""`calibrate` 命令（M1-04）：假 UIA 树校准向导。

四种模式：
    1. 交互模式（默认）：真实截屏 + Tkinter 框选；
    2. 离线模式（``--image`` + ``--rects``）：用静态截图与给定矩形完成校准，
       便于 CI/DoD 复现（不需要桌面交互）；
    3. 导出分享包（``--export <dir>``）：把当前 profile + 锚点图导出为可分享目录；
    4. 导入分享包（``--import <dir|zip>``）：加载别人分享的校准包到本机配置路径。

产物：每个元素一张锚点图 + profile JSON；结束前自动回验结构。
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from vrpa.errors import ProfileMismatch, TreeConfigError
from vrpa.ports import Rect
from vrpa.vision.calibration import CalibrationSession
from vrpa.vision.matcher import Image
from vrpa.vision.package import export_package, import_package
from vrpa.vision.profile import load_profile
from vrpa.vision.screen import AutoScreenSource, ImageScreenSource

__all__ = ["run_calibrate"]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m wechat_agent calibrate",
        description="假 UIA 树校准向导（M1-04）：框选元素 -> 锚点图 -> profile",
    )
    parser.add_argument("--config", default=None, help="配置文件路径（默认 config.yaml）")
    parser.add_argument("--elements", default=None, help="待校准元素，逗号分隔，如 main_window,input_box")
    parser.add_argument("--import", dest="import_path", default=None, help="导入校准包（目录或 .zip）")
    parser.add_argument("--export", dest="export_path", default=None, help="导出校准包到目录")
    parser.add_argument("--parent", action="append", default=[], help="父子关系：child=parent（可多次）")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的 profile")
    parser.add_argument("--image", default=None, help="离线模式截图（PNG/JPG）")
    parser.add_argument("--rects", default=None, help="离线模式矩形：id=x,y,w,h;id2=...")
    return parser.parse_args(list(argv))


def _parse_rects(raw: str) -> dict[str, Rect]:
    result: dict[str, Rect] = {}
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise TreeConfigError(f"--rects 片段缺少 '='：{chunk!r}")
        element_id, numbers = chunk.split("=", 1)
        parts = [part.strip() for part in numbers.split(",")]
        if len(parts) != 4:
            raise TreeConfigError(f"--rects 需要 x,y,w,h：{chunk!r}")
        try:
            x, y, width, height = (int(part) for part in parts)
        except ValueError as exc:
            raise TreeConfigError(f"--rects 数值非法：{chunk!r}") from exc
        result[element_id.strip()] = Rect(x, y, width, height)
    return result


def _parse_parents(items: Sequence[str]) -> dict[str, str]:
    parents: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise TreeConfigError(f"--parent 需要 child=parent：{item!r}")
        child, parent = item.split("=", 1)
        parents[child.strip()] = parent.strip()
    return parents


def _tk_selector(image: Image) -> Rect:
    """Tkinter 框选：鼠标拖拽返回 Rect。"""
    import tkinter as tk

    from PIL import Image as PILImage  # type: ignore[import-untyped]

    rgb = image[:, :, ::-1] if image.ndim == 3 else image
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        temp_path = Path(handle.name)
    PILImage.fromarray(np.asarray(rgb, dtype=np.uint8)).save(temp_path)

    root = tk.Tk()
    root.title("VRPA calibrate：拖拽框选元素（Esc 取消）")
    photo = tk.PhotoImage(file=str(temp_path))
    canvas = tk.Canvas(root, width=photo.width(), height=photo.height())
    canvas.pack()
    canvas.create_image(0, 0, anchor="nw", image=photo)
    state: dict[str, object] = {"start": None, "rect": None, "rect_id": None}

    def on_press(event: tk.Event) -> None:  # type: ignore[type-arg]
        state["start"] = (event.x, event.y)
        if state["rect_id"] is not None:
            canvas.delete(state["rect_id"])  # type: ignore[arg-type]
        state["rect_id"] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="red", width=2)

    def on_drag(event: tk.Event) -> None:  # type: ignore[type-arg]
        start = state["start"]
        if start is None:
            return
        canvas.coords(state["rect_id"], start[0], start[1], event.x, event.y)  # type: ignore[index]

    def on_release(event: tk.Event) -> None:  # type: ignore[type-arg]
        start = state["start"]
        if start is None:
            return
        left, top = min(start[0], event.x), min(start[1], event.y)
        right, bottom = max(start[0], event.x), max(start[1], event.y)
        state["rect"] = Rect(left, top, right - left, bottom - top)
        root.destroy()

    def on_escape(_event: object = None) -> None:
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", on_escape)
    root.mainloop()
    temp_path.unlink(missing_ok=True)
    rect = state["rect"]
    if not isinstance(rect, Rect):
        raise TreeConfigError("校准已取消（未框选任何区域）")
    return rect


def _load_config_or_none(args: argparse.Namespace) -> object:
    from wechat_agent.core.config import load_config

    return load_config(args.config)


def _import_bundle(args: argparse.Namespace) -> int:
    """导入他人分享的校准包到 config 指定的 profile/anchors 路径。"""
    try:
        config = _load_config_or_none(args)
        source = Path(str(args.import_path))
        info = import_package(
            source,
            profile_target=config.profile_path(),  # type: ignore[attr-defined]
            anchors_target=config.profile_anchors_dir(),  # type: ignore[attr-defined]
            force=bool(args.force),
        )
        if args.image is not None:
            if not Path(str(args.image)).is_file():
                print(f"截图不存在：{args.image}", file=sys.stderr)
                return 2
            frame = ImageScreenSource.from_file(str(args.image)).capture()
            height, width = frame.shape[:2]
            if (width, height) != (info.profile.width, info.profile.height):
                raise ProfileMismatch(
                    f"校准包尺寸 {info.profile.width}x{info.profile.height} 与当前截图 {width}x{height} 不一致",
                    hint="请导入与当前分辨率/DPI 匹配的分享包，或自行重新校准",
                )
    except ProfileMismatch as exc:
        print(f"PROFILE MISMATCH: {exc}", file=sys.stderr)
        return 7
    except TreeConfigError as exc:
        print(f"IMPORT ERROR: {exc}", file=sys.stderr)
        return 3

    print(f"profile : {config.profile_path()}")  # type: ignore[attr-defined]
    print(f"anchors : {config.profile_anchors_dir()}")  # type: ignore[attr-defined]
    print(f"elements: {', '.join(info.profile.element_ids())}")
    print("next    : python -m wechat_agent validate-tree --strict")
    print("          python -m wechat_agent locate input_box --json")
    print("RESULT: OK")
    return 0


def _export_bundle(args: argparse.Namespace) -> int:
    """把当前 profile + 锚点图导出为可分享目录。"""
    try:
        config = _load_config_or_none(args)
        profile = load_profile(
            config.profile_path(),  # type: ignore[attr-defined]
            anchors_root=config.profile_anchors_dir(),  # type: ignore[attr-defined]
        )
        info = export_package(profile, Path(str(args.export_path)), force=bool(args.force))
    except TreeConfigError as exc:
        print(f"EXPORT ERROR: {exc}", file=sys.stderr)
        return 3
    print(f"package : {info.root}")
    print(f"files   : {len(info.files)} 个（profile.json / package.json / anchors/*）")
    print("share   : 可直接压缩该目录分享；对方按 docs/calibration-package.md 导入")
    print("RESULT: OK")
    return 0


def run_calibrate(argv: Sequence[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    if args.import_path:
        return _import_bundle(args)
    if args.export_path:
        return _export_bundle(args)

    if not args.elements:
        print("校准模式需要 --elements（或使用 --import / --export）", file=sys.stderr)
        return 2
    elements = [item.strip() for item in str(args.elements).split(",") if item.strip()]
    if not elements:
        print("--elements 不能为空", file=sys.stderr)
        return 2
    try:
        parents = _parse_parents(list(args.parent))
        rects = _parse_rects(str(args.rects)) if args.rects else {}
    except TreeConfigError as exc:
        print(f"CALIBRATE ERROR: {exc}", file=sys.stderr)
        return 2

    offline = args.image is not None or bool(rects)
    if offline:
        if args.image is None or not Path(args.image).is_file():
            print("离线模式需要存在 --image 文件", file=sys.stderr)
            return 2
        missing = [element_id for element_id in elements if element_id not in rects]
        if missing:
            print(f"--rects 缺少元素：{missing}", file=sys.stderr)
            return 2

    from wechat_agent.core.config import load_config

    try:
        config = load_config(args.config)
        profile_path = config.profile_path()
        if profile_path.is_file() and not args.force:
            print(f"profile 已存在：{profile_path}（如需覆盖请加 --force）", file=sys.stderr)
            return 2

        screen = ImageScreenSource.from_file(args.image) if args.image is not None else AutoScreenSource()
        if offline:
            current = {"element": ""}

            def selector(_image: Image) -> Rect:
                return rects[current["element"]]

        else:
            selector = _tk_selector

        session = CalibrationSession(
            profile_path,
            screen,
            selector,
            profile_name=config.profile_name(),
            anchors_root=config.profile_anchors_dir(),
            dpi_scale=config.display.dpi_scale,
        )
        pending = list(elements)
        while pending:
            progressed = False
            for element_id in list(pending):
                parent = parents.get(element_id)
                if parent is not None and parent not in session.element_ids:
                    continue
                if offline:
                    current["element"] = element_id
                rect = session.calibrate(element_id, parent=parent)
                print(f"[OK] {element_id} :: rect={rect.as_tuple()}")
                pending.remove(element_id)
                progressed = True
            if not progressed:
                print(f"父元素未校准/循环依赖：{pending}", file=sys.stderr)
                return 2
        result = session.finalize()
    except TreeConfigError as exc:
        print(f"CALIBRATE ERROR: {exc}", file=sys.stderr)
        return 3

    print(f"profile : {result.profile_path}")
    print(f"elements: {', '.join(result.element_ids)}")
    print("RESULT: OK")
    return 0
