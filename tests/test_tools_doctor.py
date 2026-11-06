"""M0-07 测试：doctor 环境体检（FakeChecker，只读探测）。"""

from __future__ import annotations

import json
from pathlib import Path

from vrpa.ports import Rect
from vrpa.vision.window import WindowInfo
from wechat_agent import main as main_module
from wechat_agent.core.config import load_config
from wechat_agent.tools.doctor import DoctorChecker, build_report, run_doctor

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "config.yaml").read_text(encoding="utf-8")


def _config(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(BASE.replace("data_dir: ./data", f"data_dir: {tmp_path.as_posix()}/data", 1), encoding="utf-8")
    return load_config(path)


class FakeChecker(DoctorChecker):
    def __init__(
        self,
        *,
        version=(3, 14, 7),
        missing=(),
        display=None,
        window=None,
        write_error: Exception | None = None,
    ) -> None:
        self._version = version
        self._missing = set(missing)
        self._display = display
        self._window = window
        self._write_error = write_error

    def python_version(self):
        return self._version

    def find_spec(self, module: str) -> bool:
        return module not in self._missing

    def display(self):
        if self._display is not None:
            return self._display
        return super().display()

    def find_window(self, config):
        return (self._window, "") if self._window else (None, "未找到微信窗口（测试）")

    def write_probe(self, data_dir: Path) -> str:
        if self._write_error is not None:
            raise self._write_error
        return super().write_probe(data_dir)


class Display:
    def __init__(self, width=1920, height=1080, dpi_scale=1.0, detected=True):
        self.width, self.height, self.dpi_scale, self.detected = width, height, dpi_scale, detected


INFO = WindowInfo(hwnd=1, title="微信", rect=Rect(0, 0, 800, 600), client_rect=Rect(0, 0, 800, 580))


def test_all_good(tmp_path: Path) -> None:
    payload = build_report(_config(tmp_path), checker=FakeChecker(display=Display(), window=INFO))
    assert payload["ok"] is True and payload["exit_code"] == 0
    assert payload["summary"]["pass"] >= 4


def test_missing_deps_warn_not_fatal(tmp_path: Path) -> None:
    payload = build_report(
        _config(tmp_path),
        checker=FakeChecker(missing={"pyautogui", "pywinauto", "cv2"}, display=Display()),
    )
    assert payload["ok"] is True and payload["summary"]["warn"] >= 1
    item = next(item for item in payload["items"] if item["id"] == "deps.required")
    assert item["status"] == "WARN" and "pyautogui" in item["detail"]


def test_old_python_fatal(tmp_path: Path) -> None:
    payload = build_report(_config(tmp_path), checker=FakeChecker(version=(3, 10, 0), display=Display()))
    assert payload["ok"] is False and payload["exit_code"] != 0
    assert payload["fatal"] is True


def test_data_write_failure_fatal(tmp_path: Path) -> None:
    payload = build_report(
        _config(tmp_path),
        checker=FakeChecker(display=Display(), write_error=PermissionError("denied")),
    )
    assert payload["fatal"] is True and payload["exit_code"] == 2
    item = next(item for item in payload["items"] if item["id"] == "data.write")
    assert item["status"] == "FAIL"


def test_small_screen_and_missing_window_warn(tmp_path: Path) -> None:
    payload = build_report(_config(tmp_path), checker=FakeChecker(display=Display(width=800, height=600)))
    statuses = {item["id"]: item["status"] for item in payload["items"]}
    assert statuses["display.resolution"] == "WARN"
    assert statuses["wechat.window"] == "WARN"
    assert payload["fatal"] is False


def test_display_detection_failure_warn(tmp_path: Path) -> None:
    class Broken(FakeChecker):
        def display(self):
            raise OSError("no display")

    payload = build_report(_config(tmp_path), checker=Broken())
    assert any(item["id"] == "display.detect" and item["status"] == "WARN" for item in payload["items"])


def test_run_doctor_cli(tmp_path: Path, capsys) -> None:
    config = _config(tmp_path)
    assert run_doctor(["--config", str(config.path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert any(item["id"] == "data.write" for item in payload["items"])


def test_run_doctor_text(tmp_path: Path, capsys) -> None:
    config = _config(tmp_path)
    assert run_doctor(["--config", str(config.path)]) == 0
    out = capsys.readouterr().out
    assert "RESULT: OK" in out and "summary:" in out


def test_main_dispatch_doctor(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert main_module.main(["doctor", "--config", str(config.path)]) == 0


def test_build_report_never_raises_for_unexpected_checker(tmp_path: Path) -> None:
    class Exploding(FakeChecker):
        def find_window(self, config):
            raise RuntimeError("boom")

    payload = build_report(_config(tmp_path), checker=Exploding(display=Display()))
    assert payload["ok"] is True
    assert any(item["id"] == "wechat.window" and item["status"] == "WARN" for item in payload["items"])
