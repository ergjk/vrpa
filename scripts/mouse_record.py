"""真机调试：记录鼠标轨迹（用于校准采集拖拽比例）。

用法：
    python scripts/mouse_record.py --seconds 8 --warmup 3

3 秒倒计时后开始记录 8 秒；请在微信消息区**手动**从一端拖选到另一端。
脚本只读取光标位置，不注入任何键鼠事件。
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import argparse  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="记录鼠标轨迹（只读）")
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--warmup", type=float, default=3.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    from vrpa.vision.dpi import enable_dpi_awareness

    enable_dpi_awareness()
    import pyautogui  # type: ignore[import-untyped]

    for remaining in range(int(args.warmup), 0, -1):
        print(f"{remaining} 秒后开始记录，请把鼠标放到消息区起点…", flush=True)
        time.sleep(1)
    print(f"开始记录 {args.seconds:.0f} 秒：请手动拖选消息文字", flush=True)
    started = time.perf_counter()
    points: list[tuple[int, int]] = []
    while time.perf_counter() - started < args.seconds:
        point = pyautogui.position()
        points.append((int(point.x), int(point.y)))
        time.sleep(0.05)
    if not points:
        print("未采集到鼠标位置")
        return 1
    xs = [item[0] for item in points]
    ys = [item[1] for item in points]
    payload = {
        "points": len(points),
        "start": points[0],
        "end": points[-1],
        "bbox": [min(xs), min(ys), max(xs), max(ys)],
        "screen": list(pyautogui.size()),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"start = {payload['start']}")
        print(f"end   = {payload['end']}")
        print(f"bbox  = {payload['bbox']}")
        print(f"screen= {payload['screen']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
