"""真机验收清单生成（M6-06）：只读检查 + 人工步骤，绝不真实发送。"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

__all__ = ["build_acceptance", "render_checklist", "run_acceptance"]


def _item(item_id: str, section: str, title: str, status: str, note: str = "") -> dict[str, Any]:
    return {"id": item_id, "section": section, "title": title, "status": status, "note": note}


def build_acceptance(config: Any) -> dict[str, Any]:
    data_dir = Path(config.data_dir)
    profile = Path(config.profile_path())
    persona = Path(config.llm.persona_path)
    knowledge = data_dir / "knowledge"
    items: list[dict[str, Any]] = [
        _item("env.dry_run", "环境", "dry_run=true（首次真机必须）", "pass" if config.app.dry_run else "fail"),
        _item("env.persona", "环境", "人设文件存在", "pass" if persona.is_file() else "manual", str(persona)),
        _item(
            "env.display", "环境", "显示器已检测", "pass" if config.display.detected else "fail", str(config.display)
        ),
        _item(
            "env.api_key",
            "环境",
            "DEEPSEEK_API_KEY 已配置",
            "pass" if config.api_key() else "manual",
            "未配置时自动回复将转人工",
        ),
        _item("ui.profile", "校准", "假 UIA 树 profile 存在", "pass" if profile.is_file() else "fail", str(profile)),
        _item(
            "ui.anchors", "校准", "锚点目录存在", "pass" if Path(config.profile_anchors_dir()).is_dir() else "manual"
        ),
        _item(
            "kb.global",
            "知识",
            "全局知识目录可读",
            "pass" if (knowledge / "global").is_dir() else "manual",
            str(knowledge / "global"),
        ),
        _item("kb.chat", "知识", "专属知识目录可读", "pass" if (knowledge / "chats").is_dir() else "manual"),
        _item(
            "memory.dbs", "记忆", "双库文件已初始化", "pass" if (data_dir / "chat_history.db").is_file() else "manual"
        ),
        _item("safe.dry_run_lock", "安全", "真实发送前已逐项确认 dry_run=false", "manual", "必须人工勾选"),
        _item("safe.backup", "安全", "data/ 已备份", "manual"),
        _item("real.calibrate", "真机步骤", "validate-tree 通过", "manual"),
        _item("real.probe", "真机步骤", "probe 能采集到消息", "manual"),
        _item("real.reply", "真机步骤", "小号验证一轮自动回复 + 回读校验", "manual"),
        _item("real.memory", "真机步骤", "重启后记忆召回正确", "manual"),
        _item("rollback", "回滚", "回滚方式：dry_run=true + 停止进程 + 恢复 data/ 备份", "manual"),
    ]
    summary = {
        "pass": sum(1 for item in items if item["status"] == "pass"),
        "fail": sum(1 for item in items if item["status"] == "fail"),
        "manual": sum(1 for item in items if item["status"] == "manual"),
    }
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dry_run": bool(config.app.dry_run),
        "summary": summary,
        "items": items,
    }


def render_checklist(payload: dict[str, Any]) -> str:
    lines = [
        "# 真机验收清单",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 当前 dry_run：{payload['dry_run']}",
        f"- 自动检查：pass={payload['summary']['pass']} fail={payload['summary']['fail']} manual={payload['summary']['manual']}",
        "",
        "> 本清单不执行任何真实键鼠操作；真实发送前必须人工逐项确认。",
        "",
    ]
    sections: dict[str, list[dict[str, Any]]] = {}
    for item in payload["items"]:
        sections.setdefault(str(item["section"]), []).append(item)
    for section, items in sections.items():
        lines.append(f"## {section}")
        for item in items:
            mark = {"pass": "x", "fail": "!", "manual": " "}.get(str(item["status"]), " ")
            note = f"  <!-- {item['note']} -->" if item["note"] else ""
            lines.append(f"- [{mark}] {item['title']}{note}")
        lines.append("")
    return "\n".join(lines)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m wechat_agent acceptance", description="真机验收清单")
    parser.add_argument("--config", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(list(argv))


def run_acceptance(argv: Sequence[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    from wechat_agent.core.config import load_config

    config = load_config(args.config)
    payload = build_acceptance(config)
    output = (
        Path(args.output)
        if args.output
        else Path(config.data_dir) / "reports" / f"acceptance_{datetime.now():%Y%m%d_%H%M%S}.md"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_checklist(payload), encoding="utf-8")
    payload["output"] = str(output)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"checklist : {output}")
        print(f"summary   : {payload['summary']}")
        print("RESULT: OK")
    return 0
