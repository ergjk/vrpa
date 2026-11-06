"""`doctor` 环境体检（M0-07）：依赖 / 屏幕 DPI / 微信窗口 / 数据目录写权限。

分级：
    PASS  正常
    WARN  缺失或异常但不阻塞（依赖缺失、微信未启动、屏幕偏小、人设缺失等）
    FAIL  致命（Python 版本过低、数据目录不可写、配置/写探针失败） -> 非 0 退出

本命令只读探测，不点击、不发送、不写入业务库（仅数据目录临时探针文件并即时删除）。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["DoctorChecker", "build_report", "run_doctor"]

MIN_PYTHON = (3, 11)
REQUIRED_DEPS = ("numpy", "cv2", "pyautogui", "pywinauto", "pyperclip")
MIN_WIDTH = 1280
MIN_HEIGHT = 720


@dataclass(frozen=True)
class DoctorItem:
    id: str
    title: str
    status: str
    detail: str = ""
    fatal: bool = False


class DoctorChecker:
    """可替换的探测实现（测试注入 Fake）。"""

    def python_version(self) -> tuple[int, ...]:
        return tuple(sys.version_info[:3])

    def find_spec(self, module: str) -> bool:
        try:
            return importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            return False

    def display(self) -> Any:
        from vrpa.config.schema import detect_display

        return detect_display()

    def find_window(self, config: Any) -> tuple[Any | None, str]:
        try:
            from vrpa.vision.window import PywinautoWindowBackend

            info = PywinautoWindowBackend().find(
                title_regex=config.wechat.window_title_regex,
                process_names=config.wechat.process_names,
            )
        except Exception as exc:  # noqa: BLE001 - 体检不得崩溃
            return None, f"{type(exc).__name__}: {exc}"
        if info is None:
            return None, "未找到微信窗口（请先启动微信）"
        return info, ""

    def write_probe(self, data_dir: Path) -> str:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / f".doctor_write_probe_{os.getpid()}"
        try:
            probe.write_text("doctor", encoding="utf-8")
            if probe.read_text(encoding="utf-8") != "doctor":
                raise OSError("写入内容回读不一致")
        finally:
            probe.unlink(missing_ok=True)
        return str(data_dir)


def _item(item_id: str, title: str, status: str, detail: str = "", fatal: bool = False) -> DoctorItem:
    return DoctorItem(id=item_id, title=title, status=status, detail=detail, fatal=fatal)


def build_report(config: Any, *, checker: DoctorChecker | None = None) -> dict[str, Any]:
    checker = checker or DoctorChecker()
    items: list[DoctorItem] = []

    # 1. Python 版本（致命）
    version = checker.python_version()
    version_text = ".".join(str(part) for part in version)
    if tuple(version[:2]) >= MIN_PYTHON:
        items.append(_item("python.version", f"Python {version_text}", "PASS"))
    else:
        items.append(
            _item(
                "python.version",
                f"Python {version_text} 过低",
                "FAIL",
                f"需要 >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}",
                fatal=True,
            )
        )

    # 2. 第三方依赖（缺失 WARN，不阻塞）
    missing = [module for module in REQUIRED_DEPS if not checker.find_spec(module)]
    if missing:
        items.append(_item("deps.required", "第三方依赖", "WARN", "缺失：" + ", ".join(missing)))
    else:
        items.append(_item("deps.required", "第三方依赖", "PASS", ", ".join(REQUIRED_DEPS)))

    # 3. 屏幕分辨率 / DPI 缩放（WARN）
    try:
        display = checker.display()
    except Exception as exc:  # noqa: BLE001
        items.append(_item("display.detect", "屏幕检测", "WARN", f"{type(exc).__name__}: {exc}"))
    else:
        if not getattr(display, "detected", False):
            items.append(_item("display.detect", "屏幕检测", "WARN", "未检测到显示器"))
        elif getattr(display, "width", 0) < MIN_WIDTH or getattr(display, "height", 0) < MIN_HEIGHT:
            items.append(
                _item(
                    "display.resolution",
                    "屏幕分辨率",
                    "WARN",
                    f"{display.width}x{display.height}，建议 >= {MIN_WIDTH}x{MIN_HEIGHT}",
                )
            )
        else:
            items.append(
                _item(
                    "display.resolution",
                    "屏幕分辨率",
                    "PASS",
                    f"{display.width}x{display.height} @ dpi_scale={display.dpi_scale}",
                )
            )

    # 4. 微信进程/窗口（WARN）
    try:
        window, error = checker.find_window(config)
    except Exception as exc:  # noqa: BLE001
        window, error = None, f"{type(exc).__name__}: {exc}"
    if window is None:
        items.append(_item("wechat.window", "微信窗口", "WARN", error or "未找到微信窗口"))
    else:
        items.append(
            _item(
                "wechat.window",
                "微信窗口",
                "PASS",
                f"title={getattr(window, 'title', '?')} process={getattr(window, 'process_name', '?')}",
            )
        )

    # 5. 数据目录写权限（致命）
    data_dir = Path(config.data_dir)
    try:
        detail = checker.write_probe(data_dir)
    except Exception as exc:  # noqa: BLE001
        items.append(
            _item("data.write", "数据目录写权限", "FAIL", f"{data_dir}: {type(exc).__name__}: {exc}", fatal=True)
        )
    else:
        items.append(_item("data.write", "数据目录写权限", "PASS", detail))

    # 6. 配置资源（WARN）
    persona = Path(config.llm.persona_path)
    items.append(_item("persona.file", "人设文件", "PASS" if persona.is_file() else "WARN", str(persona)))

    fatal = any(item.status == "FAIL" and item.fatal for item in items)
    summary = {
        "pass": sum(1 for item in items if item.status == "PASS"),
        "warn": sum(1 for item in items if item.status == "WARN"),
        "fail": sum(1 for item in items if item.status == "FAIL"),
    }
    return {
        "ok": not fatal,
        "fatal": fatal,
        "exit_code": 2 if fatal else 0,
        "dry_run": bool(config.app.dry_run),
        "summary": summary,
        "items": [
            {"id": item.id, "title": item.title, "status": item.status, "detail": item.detail, "fatal": item.fatal}
            for item in items
        ],
    }


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m wechat_agent doctor",
        description="环境体检：依赖 / 屏幕 DPI / 微信窗口 / 数据目录写权限（只读探测）",
    )
    parser.add_argument("--config", default=None)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(list(argv))


def run_doctor(argv: Sequence[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    from wechat_agent.core.config import load_config

    config = load_config(args.config)
    payload = build_report(config)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for item in payload["items"]:
            print(f"[{item['status']:<4}] {item['id']:<20} {item['title']}  {item['detail']}")
        summary = payload["summary"]
        print(
            f"summary: pass={summary['pass']} warn={summary['warn']} fail={summary['fail']}  dry_run={payload['dry_run']}"
        )
        print("RESULT: OK" if payload["ok"] else "RESULT: FAIL（存在致命项）")
    return int(payload["exit_code"])
