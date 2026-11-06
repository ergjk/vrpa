"""通用配置段（平台无关）：数据模型 + 解析 + .env 加载 + 显示器探测。

归属原则（ADR-0001 / M0-F-06）：
    通用段（app / uia_tree / capture / llm / humanize / ratelimit / safety /
    control / plugins / display）由框架解析；
    平台私有段（当前为 ``platform.options``）由平台插件解析（应用层）。
"""

from __future__ import annotations

import ctypes
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vrpa.config.validators import as_bool as _as_bool
from vrpa.config.validators import as_float as _as_float
from vrpa.config.validators import as_int as _as_int
from vrpa.config.validators import as_number_list as _as_number_list
from vrpa.config.validators import as_range as _as_range
from vrpa.config.validators import as_ratio as _as_ratio
from vrpa.config.validators import as_str as _as_str
from vrpa.config.validators import as_str_list as _as_str_list
from vrpa.config.validators import check_keys as _check_keys
from vrpa.config.validators import expect_mapping as _expect_mapping
from vrpa.config.validators import section as _section
from vrpa.errors import ConfigError

_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
_POLICIES = {"ignore", "queue_confirm"}
_TITLE_VERIFY_MODES = {"capture_first_sender", "search_text"}
_FAIL_POLICIES = {"hold", "skip"}
_TRIM_POLICIES = {"history_first", "memory_first", "knowledge_first"}
_VISIBILITIES = {"private", "public", "list"}
_PROFILE_RE = re.compile(r"^\d{3,5}x\d{3,5}@\d+(?:\.\d+)?$")
_QUIET_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d-([01]?\d|2[0-3]):[0-5]\d$")
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_dotenv(path: Path) -> dict[str, str]:
    """极简 .env 解析：KEY=VALUE、# 注释、可选引号；不覆盖已存在的环境变量。"""
    loaded: dict[str, str] = {}
    if not path.is_file():
        return loaded
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"无法读取 .env（{path}）：{exc}") from exc
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        if "=" not in stripped:
            raise ConfigError(f".env 第 {lineno} 行格式错误（缺少 '='）：{line!r}")
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        if not _ENV_KEY_RE.match(key):
            raise ConfigError(f".env 第 {lineno} 行变量名非法：{key!r}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        loaded[key] = value
    for key, value in loaded.items():
        os.environ.setdefault(key, value)
    return loaded


@dataclass(frozen=True)
class AppConfig:
    log_level: str
    data_dir: str
    dry_run: bool
    tick_interval: float
    max_hours: float


@dataclass(frozen=True)
class MatchConfig:
    threshold: float
    scales: tuple[float, ...]
    grayscale: bool
    max_side_px: int


@dataclass(frozen=True)
class UiaTreeConfig:
    profile: str
    dir: str
    anchors_dir: str
    cache_ttl: float
    match: MatchConfig
    locate_retries: int
    retry_wait: tuple[float, float]
    allow_ratio_fallback: bool
    # 可选：外部校准包（绝对路径）；设置后优先于 dir/anchors_dir 的默认推导
    profile_path: str | None = None
    anchors_root: str | None = None


@dataclass(frozen=True)
class DragConfig:
    from_x: float
    from_y: float
    to_x: float
    to_y: float
    steps: int
    duration: float
    jitter_px: int = 6
    hold_before: float = 0.15
    hold_after: float = 0.15


@dataclass(frozen=True)
class CaptureConfig:
    drag: DragConfig
    copy_wait: float
    min_messages: int
    lookback_screens: int
    dedup_recent_window: int
    low_confidence_policy: str
    title_verify: str
    restore_clipboard: bool


@dataclass(frozen=True)
class LlmConfig:
    provider: str
    base_url: str
    model: str
    temperature: float
    max_tokens: int
    timeout: float
    retries: int
    history_turns: int
    max_prompt_tokens: int
    memory_top_k: int
    fail_policy: str
    persona_path: str = ""
    prompt_trim_policy: str = "history_first"


@dataclass(frozen=True)
class HumanizeConfig:
    perception_delay: tuple[float, float]
    think_delay: tuple[float, float]
    typing_ms_per_char: tuple[float, float]
    pre_send_delay: tuple[float, float]
    long_reply_extra: tuple[float, float]
    jitter_enabled: bool


@dataclass(frozen=True)
class RatelimitConfig:
    per_chat_per_minute: int
    per_chat_per_day: int
    global_per_hour: int
    quiet_hours: tuple[str, ...]
    cooldown_after_send: tuple[float, float]


@dataclass(frozen=True)
class SafetyConfig:
    panic_hotkey: str
    pause_hotkey: str
    max_consecutive_failures: int
    screenshot_on_failure: bool
    sensitive_words: tuple[str, ...]
    max_reply_chars: int
    block_links: bool


@dataclass(frozen=True)
class ControlConfig:
    nlu_enabled: bool
    confirm_override_send: bool


@dataclass(frozen=True)
class MomentsConfig:
    enabled: bool
    default_visibility: str


@dataclass(frozen=True)
class PluginsConfig:
    moments: MomentsConfig


@dataclass(frozen=True)
class DisplayInfo:
    width: int
    height: int
    dpi_scale: float
    monitor: int
    detected: bool


def resolve_path(base: Path, value: str, where: str) -> str:
    try:
        path = Path(value).expanduser()
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{where} 不是合法路径：{value!r}") from exc
    return str(path if path.is_absolute() else (base / path).resolve())


def parse_app(raw: Mapping[str, Any], base: Path) -> AppConfig:
    _check_keys(raw, ("log_level", "data_dir", "dry_run", "tick_interval", "max_hours"), "app")
    return AppConfig(
        log_level=_as_str(raw.get("log_level"), "app.log_level", choices=_LOG_LEVELS),
        data_dir=resolve_path(base, _as_str(raw.get("data_dir"), "app.data_dir"), "app.data_dir"),
        dry_run=_as_bool(raw.get("dry_run"), "app.dry_run"),
        tick_interval=_as_float(raw.get("tick_interval"), "app.tick_interval", minimum=0.2),
        max_hours=_as_float(raw.get("max_hours"), "app.max_hours", minimum=0.1),
    )


def _optional_path(raw: Mapping[str, Any], key: str, base: Path) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    return resolve_path(base, _as_str(value, f"uia_tree.{key}"), f"uia_tree.{key}")


def parse_uia_tree(raw: Mapping[str, Any], base: Path) -> UiaTreeConfig:
    _check_keys(
        raw,
        (
            "profile",
            "dir",
            "anchors_dir",
            "profile_path",
            "anchors_root",
            "cache_ttl",
            "match",
            "locate_retries",
            "retry_wait",
            "allow_ratio_fallback",
        ),
        "uia_tree",
    )
    profile = _as_str(raw.get("profile"), "uia_tree.profile")
    if profile != "auto" and not _PROFILE_RE.match(profile):
        raise ConfigError(f"uia_tree.profile 必须是 auto 或 '<宽>x<高>@<DPI>' 形式，实际为 {profile!r}")
    match_raw = _expect_mapping(raw.get("match"), "uia_tree.match")
    _check_keys(match_raw, ("threshold", "scales", "grayscale", "max_side_px"), "uia_tree.match")
    allow_ratio_fallback = _as_bool(raw.get("allow_ratio_fallback"), "uia_tree.allow_ratio_fallback")
    if allow_ratio_fallback:
        raise ConfigError(
            "uia_tree.allow_ratio_fallback 必须为 false：红线 R3 禁止用比例坐标兜底点击，可点击元素必须有锚点图"
        )
    return UiaTreeConfig(
        profile=profile,
        dir=resolve_path(base, _as_str(raw.get("dir"), "uia_tree.dir"), "uia_tree.dir"),
        anchors_dir=resolve_path(base, _as_str(raw.get("anchors_dir"), "uia_tree.anchors_dir"), "uia_tree.anchors_dir"),
        cache_ttl=_as_float(raw.get("cache_ttl"), "uia_tree.cache_ttl", minimum=0.0, maximum=60.0),
        match=MatchConfig(
            threshold=_as_float(
                match_raw.get("threshold"), "uia_tree.match.threshold", minimum_exclusive=True, maximum=1.0
            ),
            scales=tuple(
                _as_float(item, f"uia_tree.match.scales[{index}]", minimum_exclusive=True, maximum=3.0)
                for index, item in enumerate(_as_number_list(match_raw.get("scales"), "uia_tree.match.scales"))
            ),
            grayscale=_as_bool(match_raw.get("grayscale"), "uia_tree.match.grayscale"),
            max_side_px=_as_int(match_raw.get("max_side_px"), "uia_tree.match.max_side_px", minimum=200),
        ),
        locate_retries=_as_int(raw.get("locate_retries"), "uia_tree.locate_retries", minimum=0, maximum=10),
        retry_wait=_as_range(raw.get("retry_wait"), "uia_tree.retry_wait"),
        allow_ratio_fallback=allow_ratio_fallback,
        profile_path=_optional_path(raw, "profile_path", base),
        anchors_root=_optional_path(raw, "anchors_root", base),
    )


def parse_capture(raw: Mapping[str, Any]) -> CaptureConfig:
    _check_keys(
        raw,
        (
            "drag",
            "copy_wait",
            "min_messages",
            "lookback_screens",
            "dedup_recent_window",
            "low_confidence_policy",
            "title_verify",
            "restore_clipboard",
        ),
        "capture",
    )
    drag_raw = _expect_mapping(raw.get("drag"), "capture.drag")
    _check_keys(
        drag_raw,
        ("from", "to", "steps", "duration", "jitter_px", "hold_before", "hold_after"),
        "capture.drag",
    )
    from_raw = _expect_mapping(drag_raw.get("from"), "capture.drag.from")
    to_raw = _expect_mapping(drag_raw.get("to"), "capture.drag.to")
    _check_keys(from_raw, ("x", "y"), "capture.drag.from")
    _check_keys(to_raw, ("x", "y"), "capture.drag.to")
    return CaptureConfig(
        drag=DragConfig(
            from_x=_as_ratio(from_raw.get("x"), "capture.drag.from.x"),
            from_y=_as_ratio(from_raw.get("y"), "capture.drag.from.y"),
            to_x=_as_ratio(to_raw.get("x"), "capture.drag.to.x"),
            to_y=_as_ratio(to_raw.get("y"), "capture.drag.to.y"),
            steps=_as_int(drag_raw.get("steps"), "capture.drag.steps", minimum=4, maximum=200),
            duration=_as_float(drag_raw.get("duration"), "capture.drag.duration", minimum_exclusive=True, maximum=10.0),
            jitter_px=_as_int(drag_raw.get("jitter_px", 6), "capture.drag.jitter_px", minimum=0, maximum=50),
            hold_before=_as_float(
                drag_raw.get("hold_before", 0.15), "capture.drag.hold_before", minimum=0.0, maximum=2.0
            ),
            hold_after=_as_float(drag_raw.get("hold_after", 0.15), "capture.drag.hold_after", minimum=0.0, maximum=2.0),
        ),
        copy_wait=_as_float(raw.get("copy_wait"), "capture.copy_wait", minimum=0.0, maximum=10.0),
        min_messages=_as_int(raw.get("min_messages"), "capture.min_messages", minimum=1),
        lookback_screens=_as_int(raw.get("lookback_screens"), "capture.lookback_screens", minimum=0, maximum=10),
        dedup_recent_window=_as_int(
            raw.get("dedup_recent_window"), "capture.dedup_recent_window", minimum=20, maximum=5000
        ),
        low_confidence_policy=_as_str(
            raw.get("low_confidence_policy"), "capture.low_confidence_policy", choices=_POLICIES
        ),
        title_verify=_as_str(raw.get("title_verify"), "capture.title_verify", choices=_TITLE_VERIFY_MODES),
        restore_clipboard=_as_bool(raw.get("restore_clipboard"), "capture.restore_clipboard"),
    )


def parse_llm(raw: Mapping[str, Any], base: Path | None = None) -> LlmConfig:
    _check_keys(
        raw,
        (
            "provider",
            "base_url",
            "model",
            "temperature",
            "max_tokens",
            "timeout",
            "retries",
            "history_turns",
            "max_prompt_tokens",
            "memory_top_k",
            "fail_policy",
            "persona_path",
            "prompt_trim_policy",
        ),
        "llm",
    )
    base_url = _as_str(raw.get("base_url"), "llm.base_url")
    if not base_url.startswith(("http://", "https://")):
        raise ConfigError(f"llm.base_url 必须是 http(s) 地址，实际为 {base_url!r}")
    persona_raw = raw.get("persona_path")
    persona_path = (
        resolve_path(base or Path("."), _as_str(persona_raw, "llm.persona_path"), "llm.persona_path")
        if persona_raw is not None
        else str(((base or Path(".")) / "personas" / "default.txt").resolve())
    )
    return LlmConfig(
        provider=_as_str(raw.get("provider"), "llm.provider"),
        base_url=base_url,
        model=_as_str(raw.get("model"), "llm.model"),
        temperature=_as_float(raw.get("temperature"), "llm.temperature", minimum=0.0, maximum=2.0),
        max_tokens=_as_int(raw.get("max_tokens"), "llm.max_tokens", minimum=1),
        timeout=_as_float(raw.get("timeout"), "llm.timeout", minimum_exclusive=True, maximum=600.0),
        retries=_as_int(raw.get("retries"), "llm.retries", minimum=0, maximum=10),
        history_turns=_as_int(raw.get("history_turns"), "llm.history_turns", minimum=1, maximum=200),
        max_prompt_tokens=_as_int(raw.get("max_prompt_tokens"), "llm.max_prompt_tokens", minimum=500),
        memory_top_k=_as_int(raw.get("memory_top_k"), "llm.memory_top_k", minimum=0, maximum=50),
        fail_policy=_as_str(raw.get("fail_policy"), "llm.fail_policy", choices=_FAIL_POLICIES),
        persona_path=persona_path,
        prompt_trim_policy=_as_str(
            raw.get("prompt_trim_policy", "history_first"),
            "llm.prompt_trim_policy",
            choices=_TRIM_POLICIES,
        ),
    )


def parse_humanize(raw: Mapping[str, Any]) -> HumanizeConfig:
    _check_keys(
        raw,
        (
            "perception_delay",
            "think_delay",
            "typing_ms_per_char",
            "pre_send_delay",
            "long_reply_extra",
            "jitter_enabled",
        ),
        "humanize",
    )
    return HumanizeConfig(
        perception_delay=_as_range(raw.get("perception_delay"), "humanize.perception_delay"),
        think_delay=_as_range(raw.get("think_delay"), "humanize.think_delay"),
        typing_ms_per_char=_as_range(raw.get("typing_ms_per_char"), "humanize.typing_ms_per_char"),
        pre_send_delay=_as_range(raw.get("pre_send_delay"), "humanize.pre_send_delay"),
        long_reply_extra=_as_range(raw.get("long_reply_extra"), "humanize.long_reply_extra"),
        jitter_enabled=_as_bool(raw.get("jitter_enabled"), "humanize.jitter_enabled"),
    )


def parse_ratelimit(raw: Mapping[str, Any]) -> RatelimitConfig:
    _check_keys(
        raw,
        ("per_chat_per_minute", "per_chat_per_day", "global_per_hour", "quiet_hours", "cooldown_after_send"),
        "ratelimit",
    )
    quiet_hours = _as_str_list(raw.get("quiet_hours"), "ratelimit.quiet_hours")
    for index, window in enumerate(quiet_hours):
        if not _QUIET_RE.match(window):
            raise ConfigError(f"ratelimit.quiet_hours[{index}] 必须是 'HH:MM-HH:MM'，实际为 {window!r}")
    return RatelimitConfig(
        per_chat_per_minute=_as_int(raw.get("per_chat_per_minute"), "ratelimit.per_chat_per_minute", minimum=0),
        per_chat_per_day=_as_int(raw.get("per_chat_per_day"), "ratelimit.per_chat_per_day", minimum=0),
        global_per_hour=_as_int(raw.get("global_per_hour"), "ratelimit.global_per_hour", minimum=0),
        quiet_hours=quiet_hours,
        cooldown_after_send=_as_range(raw.get("cooldown_after_send"), "ratelimit.cooldown_after_send"),
    )


def parse_safety(raw: Mapping[str, Any]) -> SafetyConfig:
    _check_keys(
        raw,
        (
            "panic_hotkey",
            "pause_hotkey",
            "max_consecutive_failures",
            "screenshot_on_failure",
            "sensitive_words",
            "max_reply_chars",
            "block_links",
        ),
        "safety",
    )
    return SafetyConfig(
        panic_hotkey=_as_str(raw.get("panic_hotkey"), "safety.panic_hotkey"),
        pause_hotkey=_as_str(raw.get("pause_hotkey"), "safety.pause_hotkey"),
        max_consecutive_failures=_as_int(
            raw.get("max_consecutive_failures"), "safety.max_consecutive_failures", minimum=1, maximum=100
        ),
        screenshot_on_failure=_as_bool(raw.get("screenshot_on_failure"), "safety.screenshot_on_failure"),
        sensitive_words=_as_str_list(raw.get("sensitive_words"), "safety.sensitive_words"),
        max_reply_chars=_as_int(raw.get("max_reply_chars"), "safety.max_reply_chars", minimum=1, maximum=5000),
        block_links=_as_bool(raw.get("block_links"), "safety.block_links"),
    )


def parse_control(raw: Mapping[str, Any]) -> ControlConfig:
    _check_keys(raw, ("nlu_enabled", "confirm_override_send"), "control")
    return ControlConfig(
        nlu_enabled=_as_bool(raw.get("nlu_enabled"), "control.nlu_enabled"),
        confirm_override_send=_as_bool(raw.get("confirm_override_send"), "control.confirm_override_send"),
    )


def parse_plugins(raw: Mapping[str, Any]) -> PluginsConfig:
    _check_keys(raw, ("moments",), "plugins")
    moments_raw = _expect_mapping(raw.get("moments"), "plugins.moments")
    _check_keys(moments_raw, ("enabled", "default_visibility"), "plugins.moments")
    return PluginsConfig(
        moments=MomentsConfig(
            enabled=_as_bool(moments_raw.get("enabled"), "plugins.moments.enabled"),
            default_visibility=_as_str(
                moments_raw.get("default_visibility"), "plugins.moments.default_visibility", choices=_VISIBILITIES
            ),
        )
    )


def detect_display() -> DisplayInfo:
    """探测主显示器分辨率与系统 DPI 缩放；失败回退 1920x1080@1.0 并标记 detected=False。"""
    try:
        user32 = ctypes.windll.user32
        width = int(user32.GetSystemMetrics(0))
        height = int(user32.GetSystemMetrics(1))
        try:
            dpi = int(user32.GetDpiForSystem())
        except (AttributeError, OSError):
            dpi = 96
        if width <= 0 or height <= 0:
            raise OSError("GetSystemMetrics 返回非法值")
        return DisplayInfo(width=width, height=height, dpi_scale=round(dpi / 96.0, 2), monitor=0, detected=True)
    except (AttributeError, OSError, ValueError):
        return DisplayInfo(width=1920, height=1080, dpi_scale=1.0, monitor=0, detected=False)


@dataclass(frozen=True)
class FrameworkSections:
    """一次解析得到的全部通用段。"""

    app: AppConfig
    uia_tree: UiaTreeConfig
    capture: CaptureConfig
    llm: LlmConfig
    humanize: HumanizeConfig
    ratelimit: RatelimitConfig
    safety: SafetyConfig
    control: ControlConfig
    plugins: PluginsConfig
    display: DisplayInfo


def parse_framework_sections(document: Mapping[str, Any], base: Path) -> FrameworkSections:
    """解析全部通用段（未知键/类型错误统一抛 ConfigError）。"""
    return FrameworkSections(
        app=parse_app(_section(document, "app"), base),
        uia_tree=parse_uia_tree(_section(document, "uia_tree"), base),
        capture=parse_capture(_section(document, "capture")),
        llm=parse_llm(_section(document, "llm"), base),
        humanize=parse_humanize(_section(document, "humanize")),
        ratelimit=parse_ratelimit(_section(document, "ratelimit")),
        safety=parse_safety(_section(document, "safety")),
        control=parse_control(_section(document, "control")),
        plugins=parse_plugins(_section(document, "plugins")),
        display=detect_display(),
    )


__all__ = [
    "AppConfig",
    "CaptureConfig",
    "ControlConfig",
    "DisplayInfo",
    "DragConfig",
    "FrameworkSections",
    "HumanizeConfig",
    "LlmConfig",
    "MatchConfig",
    "MomentsConfig",
    "PluginsConfig",
    "RatelimitConfig",
    "SafetyConfig",
    "UiaTreeConfig",
    "detect_display",
    "load_dotenv",
    "parse_app",
    "parse_capture",
    "parse_control",
    "parse_framework_sections",
    "parse_humanize",
    "parse_llm",
    "parse_plugins",
    "parse_ratelimit",
    "parse_safety",
    "parse_uia_tree",
    "resolve_path",
]
