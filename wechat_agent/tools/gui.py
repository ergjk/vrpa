"""Tkinter 控制台（M6-07，无额外依赖）：启动/停止单轮 dry-run、查看状态、锁定真实发送。"""

from __future__ import annotations

import argparse
import os
import queue
import subprocess
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

__all__ = ["run_gui"]

ROOT = Path(__file__).resolve().parents[2]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m wechat_agent gui", description="微信 Agent GUI 控制台")
    parser.add_argument("--config", default=None, help="配置文件路径（默认 config.yaml）")
    parser.add_argument("--chat", default="王衢665", help="目标会话")
    return parser.parse_args(list(argv))


def _python() -> str:
    return sys.executable


def _build_dry_run_cmd(chat: str, config: str | None) -> list[str]:
    cmd = [
        _python(),
        "-m",
        "wechat_agent",
        "run",
        "--real",
        "--chat",
        chat,
        "--ticks",
        "1",
        "--warmup",
        "3",
        "--settle",
        "3",
        "--multi",
        "--json",
    ]
    if config:
        cmd += ["--config", config]
    return cmd


def _build_send_cmd(chat: str, text: str, config: str | None) -> list[str]:
    cmd = [
        _python(),
        "-m",
        "wechat_agent",
        "send",
        "--real",
        "--chat",
        chat,
        "--text",
        text,
        "--i-understand-risk",
        "--json",
    ]
    if config:
        cmd += ["--config", config]
    return cmd


def _build_live_cmd(chat: str, config: str | None) -> list[str]:
    cmd = [
        _python(),
        "-m",
        "wechat_agent",
        "run",
        "--live",
        "--chat",
        chat,
        "--max-sends",
        "1",
        "--interval",
        "30",
        "--i-understand-risk",
        "--json",
    ]
    if config:
        cmd += ["--config", config]
    return cmd


class _GuiApp:  # pragma: no cover - Tkinter 界面，逻辑测试覆盖辅助函数
    def __init__(self, root: Any, config_path: str | None, chat: str) -> None:
        import tkinter as tk
        from tkinter import messagebox, scrolledtext, ttk

        self._tk = tk
        self._messagebox = messagebox
        self._root = root
        self._config_path = config_path
        self._chat = chat
        self._proc: subprocess.Popen[str] | None = None
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._log: Any = scrolledtext.ScrolledText(root, height=18, width=110, state="disabled")
        self._status_var = tk.StringVar(value="状态：未运行")
        self._chat_var = tk.StringVar(value=chat)
        self._switch_var = tk.BooleanVar(value=False)
        self._phrase_var = tk.StringVar()
        self._text_var = tk.StringVar()
        self._real_hint = tk.StringVar(value="真实发送默认锁定")

        root.title("WeChat Agent 控制台（安全模式）")
        root.geometry("900x620")
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        frame = ttk.Frame(root, padding=8)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, textvariable=self._status_var, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="会话：").pack(side="left")
        ttk.Entry(row, textvariable=self._chat_var, width=24).pack(side="left")
        ttk.Button(row, text="刷新状态", command=self._refresh).pack(side="left", padx=4)
        ttk.Button(row, text="开始单轮 dry-run", command=self._start_dry_run).pack(side="left", padx=4)
        ttk.Button(row, text="停止/紧急停止 (Ctrl+Alt+Q)", command=self._stop).pack(side="left", padx=4)
        ttk.Button(row, text="打开日志目录", command=self._open_logs).pack(side="left", padx=4)

        real = ttk.LabelFrame(frame, text="真实发送（默认锁定，需人工确认）", padding=6)
        real.pack(fill="x", pady=6)
        ttk.Label(real, textvariable=self._real_hint, foreground="#a33").pack(anchor="w")
        ttk.Checkbutton(real, text="我确认 dry_run=false 且 allow_real_send=true", variable=self._switch_var).pack(
            anchor="w"
        )
        phrase_row = ttk.Frame(real)
        phrase_row.pack(fill="x", pady=2)
        ttk.Label(phrase_row, text="确认短语（输入“我确认发送”）：").pack(side="left")
        ttk.Entry(phrase_row, textvariable=self._phrase_var, width=20).pack(side="left")
        ttk.Button(phrase_row, text="发送 1 条", command=self._send_one).pack(side="left", padx=4)
        ttk.Button(phrase_row, text="live 1 条", command=self._live_one).pack(side="left", padx=4)
        text_row = ttk.Frame(real)
        text_row.pack(fill="x", pady=2)
        ttk.Label(text_row, text="发送内容：").pack(side="left")
        ttk.Entry(text_row, textvariable=self._text_var, width=60).pack(side="left", fill="x", expand=True)

        self._log.pack(fill="both", expand=True, pady=4)
        self._append_log("GUI 已启动：真实发送默认锁定；dry-run 仅采集/入库/推理，不发送。")
        self._append_log("运行期间不要操作 GUI（会抢微信焦点）；紧急停止：Ctrl+Alt+Q。")
        self._refresh()
        self._start_hotkey_listener()
        self._root.after(200, self._poll)

    # ------------------------------------------------------------ 操作
    def _append_log(self, text: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", text.rstrip() + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _refresh(self) -> None:
        from wechat_agent.core.config import load_config

        try:
            cfg = load_config(self._config_path)
        except Exception as exc:  # noqa: BLE001
            self._status_var.set(f"配置读取失败：{exc}")
            self._real_hint.set("真实发送：配置不可用，已锁定")
            return
        try:
            import sqlite3

            db = Path(cfg.data_dir) / "chat_history.db"
            count = 0
            if db.is_file():
                conn = sqlite3.connect(db)
                try:
                    count = int(conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0])
                finally:
                    conn.close()
        except Exception:  # noqa: BLE001
            count = -1
        unlocked = (not cfg.app.dry_run) and cfg.safety.allow_real_send
        self._status_var.set(
            f"状态：{'运行中' if self._proc is not None else '未运行'}"
            f" | dry_run={cfg.app.dry_run} allow_real_send={cfg.safety.allow_real_send}"
            f" | 消息数={count} | allowlist={list(cfg.safety.real_send_allowlist)}"
        )
        self._real_hint.set("真实发送：已解锁（仍会逐项确认）" if unlocked else "真实发送：锁定（主配置双锁关闭）")

    def _start(self, cmd: list[str], label: str) -> None:
        if self._proc is not None:
            self._messagebox.showwarning("忙碌", "已有任务在运行，请先停止。")
            return

        def reader() -> None:
            assert self._proc is not None and self._proc.stdout is not None
            for line in self._proc.stdout:
                self._events.put(("line", line))
            code = self._proc.wait()
            self._events.put(("done", code))

        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"启动失败：{exc}")
            return
        self._append_log(f"启动 {label}：{' '.join(cmd)}")
        self._status_var.set(f"状态：{label} 运行中")
        threading.Thread(target=reader, daemon=True).start()

    def _start_dry_run(self) -> None:
        chat = self._chat_var.get().strip()
        if not chat:
            self._messagebox.showerror("参数错误", "会话不能为空")
            return
        self._start(_build_dry_run_cmd(chat, self._config_path), "dry-run")

    def _require_real_confirmation(self) -> bool:
        if not self._switch_var.get():
            self._append_log("拒绝：请先勾选真实发送确认。")
            return False
        if self._phrase_var.get().strip() != "我确认发送":
            self._append_log("拒绝：确认短语不正确。")
            return False
        return True

    def _send_one(self) -> None:
        if not self._require_real_confirmation():
            return
        text = self._text_var.get().strip()
        if not text:
            self._messagebox.showerror("参数错误", "发送内容不能为空")
            return
        self._start(_build_send_cmd(self._chat_var.get().strip(), text, self._config_path), "send-real")

    def _live_one(self) -> None:
        if not self._require_real_confirmation():
            return
        self._start(_build_live_cmd(self._chat_var.get().strip(), self._config_path), "live-1")

    def _stop(self) -> None:
        if self._proc is None:
            self._append_log("当前没有运行中的任务。")
            return
        self._append_log("正在终止任务……")
        try:
            self._proc.terminate()
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"终止失败：{exc}")

    def _open_logs(self) -> None:
        path = ROOT / "data" / "reports"
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"打开目录失败：{exc}")

    def _start_hotkey_listener(self) -> None:
        """全局注册 Ctrl+Alt+Q，即使 GUI 失去焦点也能紧急停止。"""
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        MOD_ALT = 0x0001
        MOD_CONTROL = 0x0002
        VK_Q = 0x51
        WM_HOTKEY = 0x0312
        self._hotkey_thread_id: int | None = None

        def worker() -> None:
            try:
                ok = user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT, VK_Q)
                if not ok:
                    self._events.put(("line", "全局停止热键 Ctrl+Alt+Q 注册失败（可能被占用）"))
                    return
                msg = wintypes.MSG()
                while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                    if msg.message == WM_HOTKEY:
                        self._events.put(("hotkey", None))
            except Exception as exc:  # noqa: BLE001
                self._events.put(("line", f"全局停止热键异常：{exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self) -> None:
        while True:
            try:
                kind, value = self._events.get_nowait()
            except queue.Empty:
                break
            if kind == "line":
                self._append_log(str(value))
            elif kind == "hotkey":
                self._append_log("收到全局紧急停止热键 Ctrl+Alt+Q")
                self._stop()
            elif kind == "done":
                self._append_log(f"任务结束，退出码={value}")
                self._proc = None
                self._refresh()
        self._root.after(200, self._poll)

    def _on_close(self) -> None:
        self._stop()
        self._root.destroy()


def run_gui(argv: Sequence[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    try:
        import tkinter as tk
    except Exception as exc:  # noqa: BLE001
        print(f"GUI 不可用：{exc}", file=sys.stderr)
        return 5
    try:
        root = tk.Tk()
    except Exception as exc:  # noqa: BLE001
        print(f"GUI 启动失败：{exc}", file=sys.stderr)
        return 5
    _GuiApp(root, args.config, args.chat)
    root.mainloop()
    return 0
