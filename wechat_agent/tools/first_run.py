"""`first-run`：新用户首跑向导（只读，不点击、不发送）。"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from wechat_agent.tools.doctor import DoctorChecker, build_report

__all__ = ["FirstRunChecker", "build_first_run", "next_steps", "run_first_run"]


class FirstRunChecker(DoctorChecker):
    def is_venv(self) -> bool:
        return Path(sys.prefix).resolve() != Path(sys.base_prefix).resolve()

    def is_admin(self) -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:  # noqa: BLE001
            return False

    def api_key_present(self) -> bool:
        key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        return bool(key)

    def profile_path(self, config: Any, display: Any) -> Path:
        tree = config.uia_tree
        if getattr(tree, "profile_path", None):
            return Path(str(tree.profile_path))
        profile = str(getattr(tree, "profile", "auto"))
        if profile == "auto":
            width = int(getattr(display, "width", 0))
            height = int(getattr(display, "height", 0))
            scale = float(getattr(display, "dpi_scale", 1.0))
            profile = f"{width}x{height}@{scale:g}"
        return Path(str(getattr(tree, "dir", "data/uia_tree"))) / f"{profile}.json"


def build_first_run(config: Any, *, checker: FirstRunChecker | None = None) -> dict[str, Any]:
    checker = checker or FirstRunChecker()
    base = build_report(config, checker=checker)
    items: list[dict[str, Any]] = [dict(item) for item in base["items"]]
    statuses = {str(item["id"]): str(item["status"]) for item in items}

    venv_ok = checker.is_venv()
    items.append(
        {
            "id": "python.venv",
            "title": "虚拟环境",
            "status": "PASS" if venv_ok else "WARN",
            "detail": sys.prefix,
            "fatal": False,
        }
    )
    admin_ok = checker.is_admin()
    items.append(
        {
            "id": "windows.admin",
            "title": "管理员权限",
            "status": "PASS" if admin_ok else "WARN",
            "detail": "可真实发送" if admin_ok else "dry-run 可继续；真实发送需管理员 PowerShell",
            "fatal": False,
        }
    )
    dry_run = bool(config.app.dry_run)
    items.append(
        {
            "id": "safety.dry_run",
            "title": "dry_run",
            "status": "PASS" if dry_run else "WARN",
            "detail": "首跑应为 true" if dry_run else "已关闭，真实发送前请确认",
            "fatal": False,
        }
    )
    allow_real = bool(config.safety.allow_real_send)
    items.append(
        {
            "id": "safety.allow_real_send",
            "title": "真实发送总开关",
            "status": "WARN" if allow_real else "PASS",
            "detail": "已解锁，首跑建议关闭" if allow_real else "已锁定（推荐）",
            "fatal": False,
        }
    )
    display = None
    with contextlib.suppress(Exception):
        display = checker.display()
    profile = checker.profile_path(config, display) if display is not None else None
    profile_ok = bool(profile and profile.is_file())
    items.append(
        {
            "id": "uia.profile",
            "title": "校准 profile",
            "status": "PASS" if profile_ok else "WARN",
            "detail": str(profile) if profile else "无法确定 profile 路径",
            "fatal": False,
        }
    )
    key_ok = checker.api_key_present()
    items.append(
        {
            "id": "llm.key",
            "title": "LLM API Key",
            "status": "PASS" if key_ok else "WARN",
            "detail": "已检测到 DEEPSEEK_API_KEY" if key_ok else "未检测到；填 .env 后重跑",
            "fatal": False,
        }
    )

    flags = {
        "venv": venv_ok,
        "admin": admin_ok,
        "deps": statuses.get("deps.required") == "PASS",
        "wechat": statuses.get("wechat.window") == "PASS",
        "profile": profile_ok,
        "key": key_ok,
        "dry_run": dry_run,
    }
    blockers = _blockers(flags)
    steps = blockers if blockers else _ready_steps()
    fatal = bool(base.get("fatal"))
    return {
        "ok": not fatal,
        "fatal": fatal,
        "exit_code": 2 if fatal else 0,
        "summary": {
            "pass": sum(1 for item in items if item["status"] == "PASS"),
            "warn": sum(1 for item in items if item["status"] == "WARN"),
            "fail": sum(1 for item in items if item["status"] == "FAIL"),
        },
        "items": items,
        "next": steps,
        "ready": not blockers,
    }


def _blockers(flags: dict[str, bool]) -> list[str]:
    steps: list[str] = []
    if not flags.get("venv"):
        steps.append("创建/激活虚拟环境：python -m venv venv && .\\venv\\Scripts\\Activate.ps1")
    if not flags.get("deps"):
        steps.append("安装依赖：.\\venv\\Scripts\\python.exe -m pip install -r requirements.txt")
    if not flags.get("key"):
        steps.append("配置 .env：copy .env.example .env，填入 DEEPSEEK_API_KEY")
    if not flags.get("wechat"):
        steps.append("启动微信 PC 4.x，并保持窗口打开")
    if not flags.get("profile"):
        steps.append("校准界面：.\\venv\\Scripts\\python.exe -m wechat_agent calibrate --warmup 10")
    if not flags.get("admin"):
        steps.append("真实发送前：用管理员 PowerShell 打开项目目录（dry-run 无需管理员）")
    if not flags.get("dry_run"):
        steps.append("首跑前把 config.yaml 的 app.dry_run 改回 true")
    return steps


def _ready_steps() -> list[str]:
    return [
        "先跑模拟：.\\venv\\Scripts\\python.exe -m wechat_agent run --simulate --scenario tests/fixtures/simulation/01_basic_flow.json",
        "再跑真机 dry-run：.\\venv\\Scripts\\python.exe -m wechat_agent run --real --chat 目标会话 --warmup 8 --settle 3 --ticks 1 --json",
        "需要界面时：.\\venv\\Scripts\\python.exe -m wechat_agent gui",
    ]


def next_steps(flags: dict[str, bool]) -> list[str]:
    blockers = _blockers(flags)
    return blockers if blockers else _ready_steps()


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m wechat_agent first-run",
        description="新用户首跑向导：虚拟环境/依赖/微信/校准/API Key/安全锁（只读）",
    )
    parser.add_argument("--config", default=None)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(list(argv))


def run_first_run(argv: Sequence[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    from wechat_agent.core.config import load_config

    config = load_config(args.config)
    payload = build_first_run(config)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for item in payload["items"]:
            print(f"[{item['status']:<4}] {item['id']:<24} {item['title']}  {item['detail']}")
        print("")
        if payload["next"]:
            print("NEXT:")
            for index, step in enumerate(payload["next"], 1):
                print(f"  {index}. {step}")
        else:
            print("NEXT: 已就绪，可开始 dry-run。")
        print("RESULT: READY" if payload["ready"] else "RESULT: NEEDS ACTION")
    return int(payload["exit_code"])
