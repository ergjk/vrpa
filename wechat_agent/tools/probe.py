"""`probe` 命令（M2-05）：采集诊断（只读，不落库、不回复）。

用法：
    python -m wechat_agent probe --text samples.txt     # 离线解析诊断（无桌面）
    python -m wechat_agent probe --chat 测试会话        # 真实采集诊断（需微信前台）
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from vrpa.errors import AgentFrameworkError, TreeConfigError
from wechat_agent.perception.parser import WeChatParser

__all__ = ["run_probe"]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m wechat_agent probe",
        description="采集诊断：打印原始剪贴板文本与解析结果（不落库、不回复）",
    )
    parser.add_argument("--config", default=None, help="配置文件路径（真实采集时使用）")
    parser.add_argument("--text", default=None, help="离线模式：从文件读取剪贴板文本")
    parser.add_argument("--chat", default=None, help="真实采集的会话名（默认 <probe>）")
    parser.add_argument("--limit", type=int, default=5, help="预览条数（默认 5）")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    return parser.parse_args(list(argv))


def _payload(raw: str, messages: Sequence[object], source: str, limit: int) -> dict[str, object]:
    preview = []
    for message in messages[: max(0, limit)]:
        preview.append(
            {
                "sender": getattr(message, "sender", None),
                "ts": getattr(message, "ts", None),
                "content": getattr(message, "content", ""),
                "confidence": getattr(message, "confidence", None),
                "strategy": getattr(message, "reason", ""),
            }
        )
    return {
        "ok": True,
        "source": source,
        "chars": len(raw),
        "lines": len(raw.splitlines()),
        "message_count": len(messages),
        "strategy": getattr(messages[0], "reason", "") if messages else "",
        "preview": preview,
    }


def run_probe(argv: Sequence[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    parser = WeChatParser()
    if args.text is not None:
        path = Path(str(args.text))
        if not path.is_file():
            print(f"文本文件不存在：{path}", file=sys.stderr)
            return 2
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"读取文本失败：{exc}", file=sys.stderr)
            return 2
        source = "file"
    else:
        from wechat_agent.core.config import load_config
        from wechat_agent.perception.capture import WeChatPerception

        try:
            config = load_config(args.config)
            perception = WeChatPerception(config)
            perception.activate()
            raw = perception.capture(str(args.chat or "<probe>"))
        except AgentFrameworkError as exc:
            print(f"PROBE ERROR: {exc}", file=sys.stderr)
            return int(exc.exit_code)
        except TreeConfigError as exc:
            print(f"PROBE ERROR: {exc}", file=sys.stderr)
            return 3
        source = "live"

    messages = parser.parse(raw)
    payload = _payload(raw, messages, source, int(args.limit))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"source   : {payload['source']}")
        print(f"chars    : {payload['chars']}  lines: {payload['lines']}")
        print(f"messages : {payload['message_count']}  strategy: {payload['strategy'] or '-'}")
        for index, item in enumerate(payload["preview"], 1):  # type: ignore[union-attr]
            print(f"  [{index}] sender={item['sender']} ts={item['ts']} :: {item['content'][:60]!r}")
        print("RESULT: OK")
    return 0
