"""插件 CLI（M6-04）：``plugin list`` / ``plugin plan moments``（dry_run）。"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import datetime

from vrpa.plugins import PluginContext, PluginManager
from wechat_agent.plugins.moments import MomentsPlugin

__all__ = ["default_registry", "run_plugin"]


def default_registry() -> PluginManager:
    manager = PluginManager()
    manager.register(MomentsPlugin(clock=lambda: datetime(2026, 1, 1, 9, 0)))
    return manager


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m wechat_agent plugin", description="插件管理（M6-04）")
    sub = parser.add_subparsers(dest="command", required=True)
    list_parser = sub.add_parser("list", help="列出插件")
    list_parser.add_argument("--json", action="store_true")
    plan = sub.add_parser("plan", help="演示插件计划（dry_run，不真实发送）")
    plan.add_argument("name", nargs="?", default="moments")
    plan.add_argument("--json", action="store_true")
    return parser.parse_args(list(argv))


def run_plugin(argv: Sequence[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    manager = default_registry()
    if args.command == "list":
        payload = [
            {"name": meta.name, "version": meta.version, "description": meta.description} for meta in manager.plugins()
        ]
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            for item in payload:
                print(f"{item['name']}@{item['version']}  {item['description']}")
        return 0
    plugin = manager.get(args.name)
    if plugin is None:
        print(f"插件不存在：{args.name}")
        return 2
    context = PluginContext(dry_run=True)
    manager.dispatch("on_start", context)
    manager.dispatch("on_tick", context, 1)
    drafts = plugin.drain()
    payload = [
        {"content": draft.content, "visibility": draft.visibility, "scheduled_for": draft.scheduled_for}
        for draft in drafts
    ]
    if args.json:
        print(json.dumps({"dry_run": True, "drafts": payload}, ensure_ascii=False, indent=2))
    else:
        print("dry_run : True")
        print(f"drafts  : {payload}")
        print("RESULT: OK")
    return 0 if drafts else 1
