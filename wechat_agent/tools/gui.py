"""Tkinter 控制台：运行 / 记忆 / 危险区 / 开发者模式（无额外 GUI 依赖）。"""

from __future__ import annotations

import argparse
import contextlib
import os
import queue
import subprocess
import sys
import tempfile
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from wechat_agent.core.next_action import explain_failure

__all__ = ["run_gui"]

ROOT = Path(__file__).resolve().parents[2]
RED = "#b00020"


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m wechat_agent gui", description="微信 Agent GUI 控制台")
    parser.add_argument("--config", default=None, help="配置文件路径（默认 config.yaml）")
    parser.add_argument("--chat", default="王衢665", help="目标会话")
    return parser.parse_args(list(argv))


def _python() -> str:
    return sys.executable


def _with_config(cmd: list[str], config: str | None) -> list[str]:
    return cmd + (["--config", config] if config else [])


def _build_dry_run_cmd(chat: str, config: str | None, *, mode: str = "single") -> list[str]:
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
        "--json",
    ]
    if mode == "multi":
        cmd.append("--multi")
    elif mode == "history":
        cmd.append("--history")
    return _with_config(cmd, config)


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
    return _with_config(cmd, config)


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
    return _with_config(cmd, config)


def _is_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def _abs_path(value: object, base: Path) -> object:
    if not isinstance(value, str) or not value.strip():
        return value
    candidate = Path(value)
    if candidate.is_absolute() or value.startswith("\\\\"):
        return value
    return str((base / candidate).resolve())


def _make_temp_config(base_config: str | None, chat: str) -> Path:
    """生成一次性真实发送配置；主配置只读，不修改。"""
    source = Path(base_config) if base_config else ROOT / "config.yaml"
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("配置根节点不是 mapping")
    app = raw.setdefault("app", {})
    safety = raw.setdefault("safety", {})
    if not isinstance(app, dict) or not isinstance(safety, dict):
        raise ValueError("app/safety 节点不是 mapping")
    base = source.parent
    if "data_dir" in app:
        app["data_dir"] = _abs_path(app["data_dir"], base)
    uia = raw.get("uia_tree")
    if isinstance(uia, dict):
        for key in ("dir", "anchors_dir", "profile_path", "anchors_root"):
            if key in uia:
                uia[key] = _abs_path(uia[key], base)
    llm = raw.get("llm")
    if isinstance(llm, dict) and "persona_path" in llm:
        llm["persona_path"] = _abs_path(llm["persona_path"], base)
    app["dry_run"] = False
    safety["allow_real_send"] = True
    safety["real_send_allowlist"] = [chat]
    fd, tmp = tempfile.mkstemp(prefix="vrpa_gui_live_", suffix=".yaml")
    os.close(fd)
    path = Path(tmp)
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _cleanup_temp(path: Path | None) -> None:
    if path is not None:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


class _MemoryWorker:  # pragma: no cover - 线程/子进程
    """按间隔运行 memory-extract；只提炼，不发送。"""

    def __init__(self, app: _GuiApp, interval: float, limit: int, config: str | None) -> None:
        self._app = app
        self._interval = max(5.0, float(interval))
        self._limit = max(1, int(limit))
        self._config = config
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen[str] | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            with contextlib.suppress(Exception):
                proc.terminate()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._app._proc is not None:  # noqa: SLF001 - 主任务运行时让路
                self._stop.wait(self._interval)
                continue
            cmd = _with_config(
                [
                    _python(),
                    "-m",
                    "wechat_agent",
                    "memory-extract",
                    "--limit",
                    str(self._limit),
                    "--json",
                ],
                self._config,
            )
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
                    env=self._app._child_env(),  # noqa: SLF001
                )
            except Exception as exc:  # noqa: BLE001
                self._app._events.put(("worker_line", f"记忆 worker 启动失败：{exc}"))  # noqa: SLF001
                return
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                if self._stop.is_set():
                    break
                self._app._events.put(("worker_line", line.rstrip()))  # noqa: SLF001
            code = self._proc.wait()
            self._proc = None
            self._app._events.put(("worker_done", code))  # noqa: SLF001
            if code == 5:
                self._app._events.put(("worker_line", "记忆 worker 已停止：缺少 API Key"))  # noqa: SLF001
                return
            self._stop.wait(self._interval)


class _GuiApp:  # pragma: no cover - Tkinter 界面
    def __init__(self, root: Any, config_path: str | None, chat: str) -> None:
        import tkinter as tk
        from tkinter import messagebox, scrolledtext, ttk

        self._tk = tk
        self._messagebox = messagebox
        self._root = root
        self._config_path = config_path
        self._chat = chat
        self._proc: subprocess.Popen[str] | None = None
        self._temp_config: Path | None = None
        self._active_kind = ""
        self._recent_output: list[str] = []
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._worker: _MemoryWorker | None = None

        self._status_var = tk.StringVar(value="状态：未运行")
        self._chat_var = tk.StringVar(value=chat)
        self._switch_var = tk.BooleanVar(value=False)
        self._phrase_var = tk.StringVar()
        self._text_var = tk.StringVar()
        self._real_hint = tk.StringVar(value="真实发送：主配置双锁保持关闭")
        self._worker_var = tk.BooleanVar(value=False)
        self._worker_status = tk.StringVar(value="记忆 worker：关闭")
        self._interval_var = tk.StringVar(value="60")
        self._limit_var = tk.StringVar(value="20")
        self._param_var = tk.StringVar(value="")

        root.title("WeChat Agent 控制台（安全模式 / 开发者模式）")
        root.geometry("980x720")
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        outer = ttk.Frame(root, padding=8)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, textvariable=self._status_var, font=("Segoe UI", 10, "bold")).pack(anchor="w")

        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True, pady=6)
        self._build_run_tab(notebook, ttk, tk)
        self._build_memory_tab(notebook, ttk, tk)
        self._build_danger_tab(notebook, ttk, tk)
        self._build_developer_tab(notebook, ttk, tk)

        self._log: Any = scrolledtext.ScrolledText(outer, height=14, width=120, state="disabled")
        self._log.pack(fill="both", expand=True, pady=4)
        self._append_log("GUI 已启动：真实发送默认锁定；记忆提炼默认关闭。")
        self._append_log("危险操作集中在“危险区”；开发者模式包含诊断入口。")
        self._refresh()
        self._start_hotkey_listener()
        self._root.after(200, self._poll)

    # ------------------------------------------------------------ UI
    def _build_run_tab(self, notebook: Any, ttk: Any, tk: Any) -> None:
        tab = ttk.Frame(notebook, padding=8)
        notebook.add(tab, text="运行")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="会话：").pack(side="left")
        ttk.Entry(row, textvariable=self._chat_var, width=24).pack(side="left")
        ttk.Button(row, text="刷新状态", command=self._refresh).pack(side="left", padx=4)
        ttk.Button(row, text="开始单轮 dry-run", command=lambda: self._start_dry_run("single")).pack(
            side="left", padx=4
        )
        ttk.Button(row, text="多条 dry-run", command=lambda: self._start_dry_run("multi")).pack(side="left", padx=4)
        ttk.Button(row, text="历史 dry-run", command=lambda: self._start_dry_run("history")).pack(side="left", padx=4)
        ttk.Button(row, text="停止/紧急停止", command=self._stop).pack(side="left", padx=4)
        ttk.Button(row, text="打开日志", command=self._open_logs).pack(side="left", padx=4)
        ttk.Label(tab, text="运行期间不要操作 GUI；紧急停止：Ctrl+Alt+Q。").pack(anchor="w", pady=4)

    def _build_memory_tab(self, notebook: Any, ttk: Any, tk: Any) -> None:
        tab = ttk.Frame(notebook, padding=8)
        notebook.add(tab, text="记忆")
        ttk.Label(tab, text="选择性记忆：流水全量保留，核心档案只写筛选结果。").pack(anchor="w", pady=2)
        ttk.Label(tab, textvariable=self._worker_status, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=4)
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="自动提炼：").pack(side="left")
        ttk.Checkbutton(row, text="启用 worker", variable=self._worker_var, command=self._toggle_worker).pack(
            side="left"
        )
        ttk.Label(row, text="间隔(s)：").pack(side="left", padx=(12, 0))
        ttk.Spinbox(row, from_=5, to=3600, textvariable=self._interval_var, width=6).pack(side="left")
        ttk.Label(row, text="每次上限：").pack(side="left", padx=(12, 0))
        ttk.Spinbox(row, from_=1, to=100, textvariable=self._limit_var, width=6).pack(side="left")
        ttk.Button(row, text="立即提炼一次", command=self._run_memory_once).pack(side="left", padx=6)
        ttk.Button(row, text="停止 worker", command=self._stop_worker).pack(side="left", padx=4)
        ttk.Label(tab, text="worker 只调用 LLM 提炼，不发送微信消息；主任务运行时自动让路。").pack(anchor="w", pady=6)

    def _build_danger_tab(self, notebook: Any, ttk: Any, tk: Any) -> None:
        tab = ttk.Frame(notebook, padding=8)
        notebook.add(tab, text="危险区（红）")
        tk.Label(
            tab,
            text="危险区：以下操作会改变安全边界或产生真实副作用，请逐项确认。",
            fg=RED,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=2)
        ttk.Label(tab, textvariable=self._real_hint, foreground=RED, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=2
        )
        ttk.Checkbutton(tab, text="我确认临时解锁并发送 1 条（主配置双锁保持不变）", variable=self._switch_var).pack(
            anchor="w", pady=2
        )
        phrase = ttk.Frame(tab)
        phrase.pack(fill="x", pady=2)
        ttk.Label(phrase, text="确认短语（输入“我确认发送”）：").pack(side="left")
        ttk.Entry(phrase, textvariable=self._phrase_var, width=20).pack(side="left")
        ttk.Button(phrase, text="临时解锁并发送 1 条", command=self._send_one).pack(side="left", padx=4)
        ttk.Button(phrase, text="临时解锁并 live 1 条", command=self._live_one).pack(side="left", padx=4)
        text_row = ttk.Frame(tab)
        text_row.pack(fill="x", pady=2)
        ttk.Label(text_row, text="发送内容：").pack(side="left")
        ttk.Entry(text_row, textvariable=self._text_var, width=60).pack(side="left", fill="x", expand=True)
        ttk.Label(
            tab,
            text="临时配置在系统临时目录生成，进程结束立即删除；失败统一显示 NEXT。",
            foreground=RED,
        ).pack(anchor="w", pady=6)

    def _build_developer_tab(self, notebook: Any, ttk: Any, tk: Any) -> None:
        tab = ttk.Frame(notebook, padding=8)
        notebook.add(tab, text="开发者模式")
        tk.Label(
            tab,
            text="开发者模式：诊断/运维入口；不会绕过 dry_run、allowlist 或管理员检查。",
            fg=RED,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=2)
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=4)
        for label, command in (
            ("first-run", lambda: self._start_named("first-run", ["first-run"])),
            ("doctor", lambda: self._start_named("doctor", ["doctor"])),
            ("validate-tree", lambda: self._start_named("validate-tree", ["validate-tree", "--strict", "--activate"])),
            ("report", lambda: self._start_named("report", ["report"])),
            ("memory-extract 一次", self._run_memory_once),
        ):
            ttk.Button(row, text=label, command=command).pack(side="left", padx=2)
        row2 = ttk.Frame(tab)
        row2.pack(fill="x", pady=4)
        ttk.Button(
            row2, text="打开 config.yaml", command=lambda: self._open_file(self._config_path or "config.yaml")
        ).pack(side="left", padx=2)
        ttk.Button(row2, text="打开 identity.toml", command=lambda: self._open_file("data/identity.toml")).pack(
            side="left", padx=2
        )
        ttk.Button(row2, text="打开日志目录", command=self._open_logs).pack(side="left", padx=2)
        ttk.Label(tab, textvariable=self._param_var).pack(anchor="w", pady=6)
        ttk.Label(
            tab,
            text="只读参数来自 config.yaml；修改安全开关请直接编辑配置，GUI 不代改。",
            foreground=RED,
        ).pack(anchor="w", pady=2)

    # ------------------------------------------------------------ 日志/状态
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
        self._status_var.set(
            f"状态：{'运行中' if self._proc is not None else '未运行'}"
            f" | dry_run={cfg.app.dry_run} allow_real_send={cfg.safety.allow_real_send}"
            f" | admin={_is_admin()} | 消息数={count}"
        )
        self._real_hint.set(
            "真实发送：主配置已解锁（不建议）；GUI 仍可临时解锁"
            if (not cfg.app.dry_run and cfg.safety.allow_real_send)
            else "真实发送：主配置双锁关闭；危险区可临时解锁 1 条"
        )
        self._param_var.set(
            f"history_turns={cfg.llm.history_turns} | memory_top_k={cfg.llm.memory_top_k}"
            f" | allowlist={list(cfg.safety.real_send_allowlist)}"
        )
        self._worker_status.set(
            "记忆 worker：运行中" if self._worker is not None and self._worker.running else "记忆 worker：关闭"
        )

    def _child_env(self) -> dict[str, str]:
        env = os.environ.copy()
        try:
            from wechat_agent.core.config import load_config

            key = load_config(self._config_path).api_key()
            if key:
                env["DEEPSEEK_API_KEY"] = key
        except Exception:  # noqa: BLE001
            pass
        return env

    # ------------------------------------------------------------ 任务
    def _start(self, cmd: list[str], label: str, kind: str = "") -> None:
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
                env=self._child_env(),
            )
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"启动失败：{exc}")
            _cleanup_temp(self._temp_config)
            self._temp_config = None
            self._active_kind = ""
            return
        self._active_kind = kind
        self._recent_output = []
        self._append_log(f"启动 {label}：{' '.join(cmd)}")
        self._status_var.set(f"状态：{label} 运行中")
        threading.Thread(target=reader, daemon=True).start()

    def _start_dry_run(self, mode: str) -> None:
        chat = self._chat_var.get().strip()
        if not chat:
            self._messagebox.showerror("参数错误", "会话不能为空")
            return
        self._start(_build_dry_run_cmd(chat, self._config_path, mode=mode), f"dry-run:{mode}")

    def _start_named(self, label: str, args: list[str]) -> None:
        _ = label
        self._start(_with_config([_python(), "-m", "wechat_agent", *args], self._config_path), args[0])

    def _require_real_confirmation(self) -> bool:
        if not self._switch_var.get():
            self._append_log("拒绝：请先在危险区勾选确认。")
            return False
        if self._phrase_var.get().strip() != "我确认发送":
            self._append_log("拒绝：确认短语不正确。")
            return False
        if not _is_admin():
            self._messagebox.showerror("权限不足", "真实发送需要管理员 PowerShell；请以管理员身份重启 GUI。")
            return False
        return True

    def _send_one(self) -> None:
        if not self._require_real_confirmation():
            return
        if self._proc is not None:
            self._messagebox.showwarning("忙碌", "已有任务在运行，请先停止。")
            return
        text = self._text_var.get().strip()
        if not text:
            self._messagebox.showerror("参数错误", "发送内容不能为空")
            return
        chat = self._chat_var.get().strip()
        try:
            self._temp_config = _make_temp_config(self._config_path, chat)
        except Exception as exc:  # noqa: BLE001
            self._messagebox.showerror("临时解锁失败", str(exc))
            return
        self._start(_build_send_cmd(chat, text, str(self._temp_config)), "send-real", "send-real")

    def _live_one(self) -> None:
        if not self._require_real_confirmation():
            return
        if self._proc is not None:
            self._messagebox.showwarning("忙碌", "已有任务在运行，请先停止。")
            return
        chat = self._chat_var.get().strip()
        try:
            self._temp_config = _make_temp_config(self._config_path, chat)
        except Exception as exc:  # noqa: BLE001
            self._messagebox.showerror("临时解锁失败", str(exc))
            return
        self._start(_build_live_cmd(chat, str(self._temp_config)), "live-1", "live-1")

    # ------------------------------------------------------------ worker
    def _toggle_worker(self) -> None:
        if self._worker_var.get():
            self._start_worker()
        else:
            self._stop_worker()

    def _start_worker(self) -> None:
        if self._worker is not None and self._worker.running:
            return
        try:
            interval = float(self._interval_var.get())
            limit = int(self._limit_var.get())
        except ValueError:
            self._messagebox.showerror("参数错误", "worker 间隔/上限必须是数字")
            self._worker_var.set(False)
            return
        self._worker = _MemoryWorker(self, interval, limit, self._config_path)
        self._worker.start()
        self._append_log(f"记忆 worker 已启动：interval={interval}s limit={limit}")
        self._worker_status.set("记忆 worker：运行中")

    def _stop_worker(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker = None
        self._worker_var.set(False)
        self._worker_status.set("记忆 worker：关闭")
        self._append_log("记忆 worker 已停止")

    def _run_memory_once(self) -> None:
        self._start(
            _with_config(
                [_python(), "-m", "wechat_agent", "memory-extract", "--limit", self._limit_var.get(), "--json"],
                self._config_path,
            ),
            "memory-extract",
            "memory-once",
        )

    # ------------------------------------------------------------ 其他
    def _stop(self) -> None:
        if self._proc is None:
            self._append_log("当前没有运行中的任务。")
            return
        self._append_log("正在终止任务……")
        with contextlib.suppress(Exception):
            self._proc.terminate()

    def _open_logs(self) -> None:
        path = ROOT / "data" / "reports"
        path.mkdir(parents=True, exist_ok=True)
        self._open_file(str(path))

    def _open_file(self, path: str) -> None:
        target = ROOT / path if not Path(path).is_absolute() else Path(path)
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"打开失败：{exc}")

    def _start_hotkey_listener(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        MOD_ALT = 0x0001
        MOD_CONTROL = 0x0002
        VK_Q = 0x51
        WM_HOTKEY = 0x0312

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
                line = str(value)
                self._append_log(line)
                self._recent_output = [*self._recent_output[-19:], line]
            elif kind == "worker_line":
                self._append_log(f"[worker] {value}")
            elif kind == "worker_done":
                code = int(value)  # type: ignore[arg-type]
                self._append_log(f"[worker] 本轮结束，退出码={code}")
            elif kind == "hotkey":
                self._append_log("收到全局紧急停止热键 Ctrl+Alt+Q")
                self._stop()
            elif kind == "done":
                code = int(value)  # type: ignore[arg-type]
                done_kind = self._active_kind
                self._proc = None
                self._active_kind = ""
                self._append_log(f"任务结束，退出码={code}")
                if done_kind in {"send-real", "live-1"}:
                    _cleanup_temp(self._temp_config)
                    self._temp_config = None
                    self._append_log("临时配置已清理；主配置保持 dry_run=true / allow_real_send=false。")
                    if code == 0:
                        received = self._messagebox.askyesno("确认收到", "临时解锁已恢复。测试账号是否已收到这条消息？")
                        self._append_log("已确认收到；本次灰度闭环。" if received else "未确认收到；请检查微信/日志。")
                    else:
                        hint = explain_failure(code, "".join(self._recent_output))
                        self._append_log(f"NEXT: {hint.title} —— {hint.next_action}")
                elif code != 0:
                    hint = explain_failure(code, "".join(self._recent_output))
                    self._append_log(f"NEXT: {hint.title} —— {hint.next_action}")
                self._refresh()
        self._root.after(200, self._poll)

    def _on_close(self) -> None:
        self._stop_worker()
        self._stop()
        _cleanup_temp(self._temp_config)
        self._temp_config = None
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
