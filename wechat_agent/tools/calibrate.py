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
import time
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
    parser.add_argument("--append", action="store_true", help="向已有 profile 追加元素（不覆盖其他元素）")
    parser.add_argument("--image", default=None, help="离线模式截图（PNG/JPG）")
    parser.add_argument("--rects", default=None, help="离线模式矩形：id=x,y,w,h;id2=...")
    parser.add_argument(
        "--warmup",
        type=float,
        default=5.0,
        help="交互校准前的准备倒计时秒数（默认 5；截图在倒计时结束后拍摄）",
    )
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


_CONTAINER_ELEMENTS = frozenset({"main_window", "message_area", "drag_start_area"})

_ELEMENT_HINTS: dict[str, str] = {
    "main_window": "整个微信主窗口",
    "chat_title": "当前会话顶部标题（联系人/群名）",
    "search_box": "左上角搜索输入框",
    "message_area": "中间消息列表区域（标题下、输入框上）",
    "input_box": "底部文本输入框",
    "send_button": "底部「发送」按钮",
    "drag_start_area": "鼠标起点区（文本框区去掉气泡-头像区后的空白带，框选顶部起始带）",
}


def _element_label(element_id: str, index: int, total: int) -> str:
    """框选窗口标题文案：[序号/总数] 元素 — 区域提示。"""
    hint = _ELEMENT_HINTS.get(element_id, "")
    suffix = f" — {hint}" if hint else ""
    return f"[{index}/{total}] {element_id}{suffix}"


def _fit_scale(image_w: int, image_h: int, screen_w: int, screen_h: int) -> float:
    """截图完整显示所需的缩放比例（只缩小不放大；DPR 1.0 时为 1.0）。"""
    if image_w <= 0 or image_h <= 0 or screen_w <= 0 or screen_h <= 0:
        return 1.0
    return min(1.0, screen_w / image_w, screen_h / image_h)


def _display_to_image_rect(
    left: int,
    top: int,
    right: int,
    bottom: int,
    *,
    scale: float,
    image_w: int,
    image_h: int,
) -> Rect:
    """把屏幕显示坐标（可能被缩小）换算回原始截图像素坐标并做边界钳制。"""
    factor = scale if scale > 0 else 1.0
    x = max(0, min(image_w - 1, int(round(left / factor))))
    y = max(0, min(image_h - 1, int(round(top / factor))))
    width = max(1, int(round((right - left) / factor)))
    height = max(1, int(round((bottom - top) / factor)))
    width = min(width, image_w - x)
    height = min(height, image_h - y)
    return Rect(x, y, width, height)


def _tk_selector(image: Image, *, label: str = "") -> Rect:
    """Tkinter 框选：鼠标拖拽返回 Rect。"""
    import tkinter as tk

    from PIL import Image as PILImage  # type: ignore[import-untyped]

    root = tk.Tk()
    image_h, image_w = int(image.shape[0]), int(image.shape[1])
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    # 预留窗口标题栏/边框高度，避免缩放后窗口仍超出屏幕导致底部被裁。
    usable_w = max(1, screen_w - 24)
    usable_h = max(1, screen_h - 96)
    scale = _fit_scale(image_w, image_h, usable_w, usable_h)

    rgb = image[:, :, ::-1] if image.ndim == 3 else image
    display = PILImage.fromarray(np.asarray(rgb, dtype=np.uint8))
    if scale < 1.0:
        display = display.resize(
            (max(1, int(round(image_w * scale))), max(1, int(round(image_h * scale)))),
            PILImage.LANCZOS,
        )
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        temp_path = Path(handle.name)
    display.save(temp_path)

    scale_hint = f"（显示缩放 {scale:.0%}）" if scale < 1.0 else ""
    title = (
        f"VRPA 校准：请框选 {label}{scale_hint}（Esc 取消）" if label else "VRPA calibrate：拖拽框选元素（Esc 取消）"
    )
    root.title(title)
    photo = tk.PhotoImage(file=str(temp_path))
    canvas = tk.Canvas(root, width=photo.width(), height=photo.height())
    canvas.pack()
    canvas.create_image(0, 0, anchor="nw", image=photo)
    if label:
        banner = canvas.create_text(
            photo.width() // 2,
            20,
            text=f"请框选：{label}",
            fill="white",
            font=("Microsoft YaHei", 14, "bold"),
        )
        bounds = canvas.bbox(banner)
        if bounds is not None:
            background = canvas.create_rectangle(
                bounds[0] - 12,
                bounds[1] - 6,
                bounds[2] + 12,
                bounds[3] + 6,
                fill="#c00000",
                outline="#c00000",
            )
            canvas.tag_lower(background, banner)
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
        state["rect"] = _display_to_image_rect(
            left,
            top,
            right,
            bottom,
            scale=scale,
            image_w=image_w,
            image_h=image_h,
        )
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
        append = bool(getattr(args, "append", False))
        if append and not profile_path.is_file():
            print("--append 需要已存在的 profile；首次请正常校准", file=sys.stderr)
            return 2
        if profile_path.is_file() and not args.force and not append:
            print(f"profile 已存在：{profile_path}（如需覆盖请加 --force，追加请用 --append）", file=sys.stderr)
            return 2

        screen = ImageScreenSource.from_file(args.image) if args.image is not None else AutoScreenSource()
        current = {"element": "", "label": ""}
        if offline:

            def selector(_image: Image) -> Rect:
                return rects[current["element"]]

        else:

            def selector(image: Image) -> Rect:
                return _tk_selector(image, label=current["label"])

        session = CalibrationSession(
            profile_path,
            screen,
            selector,
            profile_name=config.profile_name(),
            anchors_root=config.profile_anchors_dir(),
            dpi_scale=config.display.dpi_scale,
        )
        warmup = max(0.0, float(getattr(args, "warmup", 5.0) or 0.0))
        if not offline and warmup > 0:
            print(f"准备倒计时：{warmup:.0f} 秒后截屏并开始框选（现在请切到微信并保持窗口不动）")
            remaining = warmup
            while remaining > 0:
                time.sleep(min(1.0, remaining))
                remaining -= 1.0
                if remaining > 0:
                    print(f"  剩余 {remaining:.0f} 秒…", flush=True)
            print(
                f"开始截屏，请按终端顺序依次框选 {len(elements)} 个元素（截图已冻结，框选不限时）",
                flush=True,
            )

        pending = list(elements)
        while pending:
            progressed = False
            for element_id in list(pending):
                parent = parents.get(element_id)
                if parent is not None and parent not in session.element_ids:
                    continue
                current["element"] = element_id
                index = len(elements) - len(pending) + 1
                current["label"] = _element_label(element_id, index, len(elements))
                rect = session.calibrate(
                    element_id,
                    parent=parent,
                    role="container" if element_id in _CONTAINER_ELEMENTS else "anchor",
                )
                print(f"[OK] {element_id} :: rect={rect.as_tuple()}")
                pending.remove(element_id)
                progressed = True
            if not progressed:
                print(f"父元素未校准/循环依赖：{pending}", file=sys.stderr)
                return 2
        old_profile = None
        backup = None
        if append:
            import shutil

            from vrpa.vision.profile import load_profile

            backup = profile_path.with_name(profile_path.name + f".bak_{int(time.time())}")
            shutil.copy2(profile_path, backup)
            old_profile = load_profile(profile_path, anchors_root=config.profile_anchors_dir())
        result = session.finalize()
        if append and old_profile is not None:
            import dataclasses

            from vrpa.vision.profile import save_profile

            merged_elements = dict(old_profile.elements)
            merged_elements.update(result.profile.elements)
            merged = dataclasses.replace(result.profile, elements=merged_elements)
            save_profile(merged, profile_path)
            print(f"[APPEND] {len(result.profile.elements)} 个元素已合并，旧 profile 备份：{backup}")
    except TreeConfigError as exc:
        print(f"CALIBRATE ERROR: {exc}", file=sys.stderr)
        return 3

    print(f"profile : {result.profile_path}")
    print(f"elements: {', '.join(result.element_ids)}")
    print("RESULT: OK")
    return 0
