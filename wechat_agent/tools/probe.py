"""`probe` 命令（M2-05）：采集诊断（只读，不落库、不回复）。

用法：
    python -m wechat_agent probe --text samples.txt     # 离线解析诊断（无桌面）
    python -m wechat_agent probe --chat 测试会话        # 真实采集诊断（需微信前台）
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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
    parser.add_argument(
        "--warmup",
        type=float,
        default=3.0,
        help="真实采集前的准备倒计时秒数（默认 3；倒计时内切到微信）",
    )
    parser.add_argument("--drag-from", default=None, help="临时覆盖拖拽起点比例：x,y（如 0.90,0.80）")
    parser.add_argument("--drag-to", default=None, help="临时覆盖拖拽终点比例：x,y（如 0.10,0.15）")
    parser.add_argument(
        "--drag-duration", type=float, default=None, help="临时覆盖拖拽时长秒数（默认 0.45，真机可试 1.2）"
    )
    parser.add_argument("--debug", action="store_true", help="打印消息区/拖拽起止点/时长")
    parser.add_argument("--dump", default=None, help="把采集到的原始剪贴板文本保存到文件")
    return parser.parse_args(list(argv))


def _parse_pair(raw: str, where: str) -> tuple[float, float]:
    parts = raw.split(",")
    if len(parts) != 2:
        raise TreeConfigError(f"{where} 需要 x,y 两个比例：{raw!r}")
    try:
        return float(parts[0]), float(parts[1])
    except ValueError as exc:
        raise TreeConfigError(f"{where} 比例非数字：{raw!r}") from exc


def _with_drag_override(
    config: object,
    from_raw: str | None,
    to_raw: str | None,
    duration: float | None = None,
) -> object:
    """临时覆盖 capture.drag 比例（用于真机调参，不写回配置文件）。"""
    from dataclasses import replace

    if from_raw is None and to_raw is None and duration is None:
        return config
    capture = config.capture  # type: ignore[attr-defined]
    drag = capture.drag
    if from_raw is not None:
        x, y = _parse_pair(from_raw, "--drag-from")
        drag = replace(drag, from_x=x, from_y=y)
    if to_raw is not None:
        x, y = _parse_pair(to_raw, "--drag-to")
        drag = replace(drag, to_x=x, to_y=y)
    if duration is not None:
        drag = replace(drag, duration=float(duration))
    return replace(config, capture=replace(capture, drag=drag))


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
            config = _with_drag_override(config, args.drag_from, args.drag_to, args.drag_duration)
            warmup = max(0.0, float(getattr(args, "warmup", 3.0) or 0.0))
            if warmup > 0:
                print(f"准备倒计时：{warmup:.0f} 秒后开始采集（请切到微信主窗口）", file=sys.stderr)
                remaining = warmup
                while remaining > 0:
                    time.sleep(min(1.0, remaining))
                    remaining -= 1.0
                    if remaining > 0:
                        print(f"  剩余 {remaining:.0f} 秒…", file=sys.stderr, flush=True)
            if args.debug:
                print("[debug] config loaded", file=sys.stderr, flush=True)
            perception = WeChatPerception(config)
            if args.debug:
                print("[debug] perception ready", file=sys.stderr, flush=True)
            perception.activate()
            if args.debug:
                print("[debug] window activated", file=sys.stderr, flush=True)
            if args.debug:
                area, start, end, duration = perception.drag_plan()
                print(
                    f"[debug] message_area={area.as_tuple()} drag={start}->{end} duration={duration}",
                    file=sys.stderr,
                )
            if not perception.is_foreground():
                fg_process = perception.foreground_process_name()
                print(
                    f"[debug] 前台校验未通过（foreground_process={fg_process}），继续由 capture 再次置前",
                    file=sys.stderr,
                )
            raw = perception.capture(str(args.chat or "<probe>"))
        except AgentFrameworkError as exc:
            print(f"PROBE ERROR: {exc}", file=sys.stderr)
            return int(exc.exit_code)
        except TreeConfigError as exc:
            print(f"PROBE ERROR: {exc}", file=sys.stderr)
            return 3
        source = "live"

    messages = parser.parse(raw)
    if args.dump:
        dump_path = Path(str(args.dump))
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        dump_path.write_text(raw, encoding="utf-8")
        print(f"raw dumped: {dump_path}", file=sys.stderr)
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
