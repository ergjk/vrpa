"""配置系统：加载、校验、路径解析、密钥掩码、selftest。

里程碑：M0-02（施工图见 docs/行动清单-V1.0.md）
输入：config.yaml（同仓库根目录）、可选 .env
输出：Config dataclass 树；load_config() / run_selftest()

纪律：
- 模块顶层只用标准库；PyYAML 在 _load_yaml() 内延迟导入，
  因此 `--help`、`--version` 甚至 selftest 的错误提示都不依赖第三方包；
- 未知配置键一律报错（防止拼写错误被静默忽略）；
- 配置错误统一抛 ConfigError（exit_code = 2，M0-04 迁移到 core/errors.py）。
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import re
import sys
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from vrpa.config.env import get_env
from vrpa.config.loader import SCHEMA_VERSION, load_document, merge_defaults
from vrpa.config.plugin import PlatformRegistry
from vrpa.config.validators import (
    as_bool as _as_bool,
)
from vrpa.config.validators import (
    as_float as _as_float,
)
from vrpa.config.validators import (
    as_int as _as_int,
)
from vrpa.config.validators import (
    as_number_list as _as_number_list,
)
from vrpa.config.validators import (
    as_range as _as_range,
)
from vrpa.config.validators import (
    as_ratio as _as_ratio,
)
from vrpa.config.validators import (
    as_str as _as_str,
)
from vrpa.config.validators import (
    as_str_list as _as_str_list,
)
from vrpa.config.validators import (
    check_keys as _check_keys,
)
from vrpa.config.validators import (
    expect_mapping as _expect_mapping,
)
from vrpa.config.validators import (
    mask_secret as _mask_secret,
)
from vrpa.config.validators import (
    section as _section,
)
from vrpa.errors import ConfigError
from vrpa.platform import AdapterInfo
from wechat_agent.config.wechat_schema import WechatPlatformOptions

DEFAULT_CONFIG_NAME = "config.yaml"
SUPPORTED_SCHEMA = SCHEMA_VERSION
ENV_CONFIG_OVERRIDE = "VRPA_CONFIG"
ENV_CONFIG_OVERRIDE_LEGACY = ("WECHAT_AGENT_CONFIG",)
ENV_API_KEY = "DEEPSEEK_API_KEY"

_TOP_KEYS = (
    "schema",
    "app",
    "platform",
    "uia_tree",
    "capture",
    "llm",
    "humanize",
    "ratelimit",
    "safety",
    "control",
    "plugins",
)
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
_POLICIES = {"ignore", "queue_confirm"}
_TITLE_VERIFY_MODES = {"capture_first_sender", "search_text"}
_FAIL_POLICIES = {"hold", "skip"}
_VISIBILITIES = {"private", "public", "list"}
_PROFILE_RE = re.compile(r"^\d{3,5}x\d{3,5}@\d+(?:\.\d+)?$")
_QUIET_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d-([01]?\d|2[0-3]):[0-5]\d$")
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# 平台插件注册表：由微信适配器的 config_plugin() 装配（懒加载，避免模块导入环）
_platform_registry: PlatformRegistry | None = None


def platform_registry() -> PlatformRegistry:
    global _platform_registry
    if _platform_registry is None:
        from wechat_agent.adapter import WeChatAdapter  # 延迟导入：config <-> adapter 循环防护

        registry = PlatformRegistry()
        registry.register(WeChatAdapter().config_plugin())
        _platform_registry = registry
    return _platform_registry


# ============================================================================
# 数据模型
# ============================================================================
@dataclass(frozen=True)
class AppConfig:
    log_level: str
    data_dir: str
    dry_run: bool
    tick_interval: float
    max_hours: float


# 平台配置对象由 wechat_agent/config/wechat_schema.py 提供；保留旧名便于应用层引用
WechatConfig = WechatPlatformOptions


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


@dataclass(frozen=True)
class DragConfig:
    from_x: float
    from_y: float
    to_x: float
    to_y: float
    steps: int
    duration: float


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


@dataclass(frozen=True)
class Config:
    schema: int
    path: Path
    platform_kind: str
    platform_plugin: str
    app: AppConfig
    wechat: WechatConfig
    uia_tree: UiaTreeConfig
    capture: CaptureConfig
    llm: LlmConfig
    humanize: HumanizeConfig
    ratelimit: RatelimitConfig
    safety: SafetyConfig
    control: ControlConfig
    plugins: PluginsConfig
    display: DisplayInfo
    env_loaded: tuple[str, ...] = field(default_factory=tuple)
    migrations: tuple[str, ...] = ()

    # ---------- 派生路径 ----------
    @property
    def data_dir(self) -> Path:
        return Path(self.app.data_dir)

    @property
    def uia_tree_dir(self) -> Path:
        return Path(self.uia_tree.dir)

    @property
    def anchors_dir(self) -> Path:
        return Path(self.uia_tree.anchors_dir)

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def screenshots_dir(self) -> Path:
        return self.data_dir / "screenshots"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backup"

    @property
    def history_db_path(self) -> Path:
        return self.data_dir / "chat_history.db"

    @property
    def memory_db_path(self) -> Path:
        return self.data_dir / "memory.db"

    # ---------- 派生值 ----------
    def profile_name(self) -> str:
        if self.uia_tree.profile != "auto":
            return self.uia_tree.profile
        scale = f"{self.display.dpi_scale:g}"
        return f"{self.display.width}x{self.display.height}@{scale}"

    def profile_path(self) -> Path:
        return self.uia_tree_dir / f"{self.profile_name()}.json"

    def profile_anchors_dir(self) -> Path:
        return self.anchors_dir / self.profile_name()

    def ensure_dirs(self) -> tuple[Path, ...]:
        dirs = (
            self.data_dir,
            self.uia_tree_dir,
            self.anchors_dir,
            self.profile_anchors_dir(),
            self.logs_dir,
            self.screenshots_dir,
            self.backup_dir,
        )
        for path in dirs:
            path.mkdir(parents=True, exist_ok=True)
        return dirs

    def api_key(self) -> str | None:
        value = os.environ.get(ENV_API_KEY, "").strip()
        return value or None

    def api_key_masked(self) -> str:
        return _mask_secret(self.api_key())

    def masked_dump(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        data["secrets"] = {ENV_API_KEY: self.api_key_masked()}
        return data


# ============================================================================
# .env / YAML 加载
# ============================================================================
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


def _load_yaml(path: Path) -> Mapping[str, Any]:
    try:
        import yaml  # 延迟导入：缺少 PyYAML 时给出可读错误而不是 ImportError
    except ModuleNotFoundError as exc:
        raise ConfigError("缺少 PyYAML 依赖：请执行 pip install -r requirements-core.txt") from exc
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件（{path}）：{exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:  # type: ignore[attr-defined]
        raise ConfigError(f"YAML 解析失败（{path}）：{exc}") from exc
    if data is None:
        raise ConfigError(f"配置文件为空：{path}")
    if not isinstance(data, dict):
        raise ConfigError(f"配置文件顶层必须是映射（dict）：{path}")
    return data


# ============================================================================
# 各段落解析
# ============================================================================
def _resolve(base: Path, value: str, where: str) -> str:
    try:
        path = Path(value).expanduser()
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{where} 不是合法路径：{value!r}") from exc
    return str(path if path.is_absolute() else (base / path).resolve())


def _parse_app(raw: Mapping[str, Any], base: Path) -> AppConfig:
    _check_keys(raw, ("log_level", "data_dir", "dry_run", "tick_interval", "max_hours"), "app")
    return AppConfig(
        log_level=_as_str(raw.get("log_level"), "app.log_level", choices=_LOG_LEVELS),
        data_dir=_resolve(base, _as_str(raw.get("data_dir"), "app.data_dir"), "app.data_dir"),
        dry_run=_as_bool(raw.get("dry_run"), "app.dry_run"),
        tick_interval=_as_float(raw.get("tick_interval"), "app.tick_interval", minimum=0.2),
        max_hours=_as_float(raw.get("max_hours"), "app.max_hours", minimum=0.1),
    )


def _parse_platform(raw: Mapping[str, Any]) -> tuple[str, str, WechatConfig]:
    """platform 段结构校验 + 平台插件校验 options（默认值由内核深度合并）。"""
    platform_raw = _section(raw, "platform")
    _check_keys(platform_raw, ("kind", "options"), "platform")
    kind = _as_str(platform_raw.get("kind"), "platform.kind")
    plugin = platform_registry().get(kind)
    options_raw = _expect_mapping(platform_raw.get("options"), "platform.options")
    merged = merge_defaults(plugin.default_options(), options_raw)
    parsed = plugin.validate_options(merged)
    return kind, plugin.describe(), parsed


def _parse_uia_tree(raw: Mapping[str, Any], base: Path) -> UiaTreeConfig:
    _check_keys(
        raw,
        ("profile", "dir", "anchors_dir", "cache_ttl", "match", "locate_retries", "retry_wait", "allow_ratio_fallback"),
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
        dir=_resolve(base, _as_str(raw.get("dir"), "uia_tree.dir"), "uia_tree.dir"),
        anchors_dir=_resolve(base, _as_str(raw.get("anchors_dir"), "uia_tree.anchors_dir"), "uia_tree.anchors_dir"),
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
    )


def _parse_capture(raw: Mapping[str, Any]) -> CaptureConfig:
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
    _check_keys(drag_raw, ("from", "to", "steps", "duration"), "capture.drag")
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


def _parse_llm(raw: Mapping[str, Any]) -> LlmConfig:
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
        ),
        "llm",
    )
    base_url = _as_str(raw.get("base_url"), "llm.base_url")
    if not base_url.startswith(("http://", "https://")):
        raise ConfigError(f"llm.base_url 必须是 http(s) 地址，实际为 {base_url!r}")
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
    )


def _parse_humanize(raw: Mapping[str, Any]) -> HumanizeConfig:
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


def _parse_ratelimit(raw: Mapping[str, Any]) -> RatelimitConfig:
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


def _parse_safety(raw: Mapping[str, Any]) -> SafetyConfig:
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


def _parse_control(raw: Mapping[str, Any]) -> ControlConfig:
    _check_keys(raw, ("nlu_enabled", "confirm_override_send"), "control")
    return ControlConfig(
        nlu_enabled=_as_bool(raw.get("nlu_enabled"), "control.nlu_enabled"),
        confirm_override_send=_as_bool(raw.get("confirm_override_send"), "control.confirm_override_send"),
    )


def _parse_plugins(raw: Mapping[str, Any]) -> PluginsConfig:
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


# ============================================================================
# 显示器探测（仅用于 profile 命名与自检展示；精确校准在 M1 calibrate 完成）
# ============================================================================
def detect_display() -> DisplayInfo:
    """探测主显示器分辨率与系统 DPI 缩放；失败回退 1920x1080@1.0 并标记 detected=False。"""
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
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


# ============================================================================
# 对外入口
# ============================================================================
def default_config_path() -> Path:
    value = get_env(ENV_CONFIG_OVERRIDE, ENV_CONFIG_OVERRIDE_LEGACY)
    return Path(value) if value else Path(DEFAULT_CONFIG_NAME)


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """加载配置：框架内核解析+升级 YAML -> 应用层逐段校验 -> 返回不可变 Config。"""
    config_path = Path(path) if path is not None else default_config_path()
    if not config_path.is_file():
        raise ConfigError(
            f"找不到配置文件：{config_path.resolve()}（确认在项目根目录执行，或复制仓库中的 config.yaml）"
        )
    config_path = config_path.resolve()
    base = config_path.parent

    raw, migration = load_document(
        config_path,
        legacy_sections=platform_registry().legacy_section_map(),
    )
    migrations: tuple[str, ...] = ()
    if migration is not None:
        message = migration.message()
        migrations = (message,)
        warnings.warn(message, UserWarning, stacklevel=2)

    if "wechat" in raw:
        raise ConfigError(
            "schema v2 不再支持顶层 wechat 段：请改用 platform: {kind: wechat, options: {...}}；"
            "或将文件声明为 schema: 1 交由迁移器自动升级"
        )
    _check_keys(raw, _TOP_KEYS, "根")
    schema = _as_int(raw.get("schema"), "schema", minimum=1)
    if schema != SUPPORTED_SCHEMA:
        raise ConfigError(f"不支持的配置 schema={schema}（本版本为 {SUPPORTED_SCHEMA}）")

    env_loaded = tuple(load_dotenv(base / ".env").keys())
    platform_kind, platform_plugin, wechat_cfg = _parse_platform(raw)

    return Config(
        schema=schema,
        path=config_path,
        platform_kind=platform_kind,
        platform_plugin=platform_plugin,
        app=_parse_app(_section(raw, "app"), base),
        wechat=wechat_cfg,
        uia_tree=_parse_uia_tree(_section(raw, "uia_tree"), base),
        capture=_parse_capture(_section(raw, "capture")),
        llm=_parse_llm(_section(raw, "llm")),
        humanize=_parse_humanize(_section(raw, "humanize")),
        ratelimit=_parse_ratelimit(_section(raw, "ratelimit")),
        safety=_parse_safety(_section(raw, "safety")),
        control=_parse_control(_section(raw, "control")),
        plugins=_parse_plugins(_section(raw, "plugins")),
        display=detect_display(),
        env_loaded=env_loaded,
        migrations=migrations,
    )


# ============================================================================
# selftest（M0-02 DoD 入口）
# ============================================================================
SELFTEST_ALLOWED_FLAGS = ("--json", "--config")
SELFTEST_PENDING_FLAGS = {
    "--redlines": "红线扫描将在 M0-09 交付；当前可用 `python -m pytest tests/test_interfaces.py` 验证红线 R1/R3"
}


def _parse_selftest_args(args: Sequence[str]) -> tuple[bool, str | None, str | None]:
    """解析 selftest 参数；返回 (json_mode, config_path, error)。未知参数一律报错，避免被静默忽略。"""
    json_mode = False
    config_path: str | None = None
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--json":
            json_mode = True
        elif arg == "--config":
            if index + 1 >= len(args):
                return json_mode, None, "参数错误：--config 需要一个路径参数"
            config_path = args[index + 1]
            index += 1
        elif arg in SELFTEST_PENDING_FLAGS:
            return json_mode, None, f"参数错误：{arg} 尚未交付（{SELFTEST_PENDING_FLAGS[arg]}）"
        else:
            return json_mode, None, f"参数错误：未知选项 {arg!r}（可用：--json、--config PATH）"
        index += 1
    return json_mode, config_path, None


def _writable(path: Path) -> tuple[bool, str]:
    probe = path / ".dsh_write_probe"
    try:
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
        return True, "ok"
    except OSError as exc:
        with contextlib.suppress(OSError):
            probe.unlink(missing_ok=True)
        return False, str(exc)


def _run_logging_self_check(log_dir: Path) -> dict[str, Any]:
    """调用 core.logging.self_check；任何异常降级为一条失败检查，不让 selftest 崩溃。"""
    try:
        from vrpa.logging import self_check as _self_check

        return _self_check(log_dir)
    except Exception as exc:  # noqa: BLE001 - 自检必须自身不崩
        return {
            "ok": False,
            "log_path": str(log_dir / "agent.log"),
            "audit_path": str(log_dir / "audit.jsonl"),
            "checks": [{"name": "logging", "ok": False, "detail": repr(exc)}],
        }


def _run_db_self_check(cfg: Config) -> dict[str, Any]:
    """初始化双库并校验结构；任何异常降级为一条失败检查（selftest 不得崩溃）。"""
    try:
        from wechat_agent.memory.db import init_databases, verify_schema
    except Exception as exc:  # noqa: BLE001 - 模块不可用也要给可读结论
        return {"ok": False, "detail": f"数据库模块不可用：{exc!r}", "databases": []}
    try:
        dbs = init_databases(cfg.data_dir)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"数据库初始化失败：{exc!r}", "databases": []}

    databases: list[dict[str, Any]] = []
    ok = True
    try:
        for kind, conn in dbs.as_pairs():
            problems = verify_schema(conn, kind)
            ok = ok and not problems
            databases.append(
                {
                    "kind": kind,
                    "path": str(dbs.path(kind)),
                    "version": dbs.schema_version(kind),
                    "tables": len(dbs.table_names(kind)),
                    "problems": problems,
                }
            )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"数据库校验失败：{exc!r}", "databases": databases}
    finally:
        with contextlib.suppress(Exception):
            dbs.close()
    detail = "，".join(f"{item['kind']}: {item['tables']} 表 / v{item['version']}" for item in databases)
    return {"ok": ok, "detail": detail, "databases": databases}


def _adapter_self_check(cfg: Config) -> dict[str, Any]:
    """经 AdapterRegistry 装配当前平台适配器，输出身份与能力（M0-F-05）。"""
    try:
        from wechat_agent.adapters import ADAPTER_REGISTRY

        adapter = ADAPTER_REGISTRY.get(cfg.platform_kind)
        info = AdapterInfo.from_adapter(adapter)
    except Exception as exc:  # noqa: BLE001 - 自检不允许抛出，落成 FAIL 项
        return {"ok": False, "detail": f"适配器装配失败：{exc}"}
    capabilities = ",".join(info.capabilities)
    return {
        "ok": True,
        "kind": info.kind,
        "display_name": info.display_name,
        "version": info.adapter_version,
        "capabilities": list(info.capabilities),
        "detail": f"{info.kind} v{info.adapter_version} caps={capabilities}",
    }


def build_selftest_report(cfg: Config) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    dirs = cfg.ensure_dirs()
    dir_entries: list[dict[str, Any]] = []
    for path in dirs:
        ok, detail = _writable(path)
        dir_entries.append({"path": str(path), "writable": ok, "detail": detail})
        add(f"dir:{path.name}", ok, detail if not ok else "ok")

    add("config", True, f"schema={cfg.schema} path={cfg.path}")

    add("platform", True, f"kind={cfg.platform_kind} plugin={cfg.platform_plugin}")
    adapter_info = _adapter_self_check(cfg)
    add("adapter", adapter_info["ok"], adapter_info["detail"])

    try:
        re.compile(cfg.wechat.window_title_regex)
        add("platform.window_title_regex", True, "ok")
    except re.error as exc:
        add("platform.window_title_regex", False, str(exc))

    if cfg.migrations:
        add("config.migration", True, "；".join(cfg.migrations))

    add(
        "display",
        cfg.display.detected,
        (
            f"{cfg.display.width}x{cfg.display.height}@{cfg.display.dpi_scale}"
            f" ({'detected' if cfg.display.detected else 'fallback'})"
        ),
    )

    profile_json = cfg.profile_path()
    add(
        "uia_tree.profile",
        True,
        f"已存在：{profile_json}" if profile_json.is_file() else f"待 M1 校准生成：{profile_json}",
    )

    add(
        "llm.api_key",
        True,
        (
            f"{cfg.llm.provider}/{cfg.llm.model} key={cfg.api_key_masked()}"
            if cfg.api_key()
            else f"{cfg.llm.provider}/{cfg.llm.model} key=<未设置，M5 前不阻塞>"
        ),
    )

    add("redline.allow_ratio_fallback", not cfg.uia_tree.allow_ratio_fallback, "False（符合红线 R3）")

    db_report = _run_db_self_check(cfg)
    db_entries: list[dict[str, Any]] = list(db_report.get("databases", []))
    add("db:init", db_report["ok"], db_report.get("detail", ""))

    add("dry_run", True, f"{cfg.app.dry_run}（首次运行必须为 True）")

    logging_report = _run_logging_self_check(Path(cfg.logs_dir))
    add("logging", logging_report["ok"], f"log={logging_report['log_path']}")
    for item in logging_report["checks"]:
        if not item["ok"]:
            add(f"logging:{item['name']}", False, item["detail"])

    ok = all(item["ok"] for item in checks)
    return {
        "ok": ok,
        "config": {"path": str(cfg.path), "schema": cfg.schema},
        "platform": {"kind": cfg.platform_kind, "plugin": cfg.platform_plugin},
        "adapter": adapter_info,
        "migrations": list(cfg.migrations),
        "display": {
            "width": cfg.display.width,
            "height": cfg.display.height,
            "dpi_scale": cfg.display.dpi_scale,
            "detected": cfg.display.detected,
            "profile": cfg.profile_name(),
        },
        "data_dir": str(cfg.data_dir),
        "directories": dir_entries,
        "databases": db_entries,
        "llm": {
            "provider": cfg.llm.provider,
            "base_url": cfg.llm.base_url,
            "model": cfg.llm.model,
            "api_key": cfg.api_key_masked(),
        },
        "runtime": {
            "dry_run": cfg.app.dry_run,
            "log_level": cfg.app.log_level,
            "moments_enabled": cfg.plugins.moments.enabled,
            "allow_ratio_fallback": cfg.uia_tree.allow_ratio_fallback,
            "env_loaded": list(cfg.env_loaded),
        },
        "logging": logging_report,
        "checks": checks,
    }


def render_selftest(report: Mapping[str, Any]) -> str:
    status = "PASS" if report.get("ok") else "FAIL"
    config = report["config"]
    display = report["display"]
    llm = report["llm"]
    runtime = report["runtime"]
    lines = [
        "== VRPA-WeChat-Agent selftest (M0 框架底座) ==",
        f"CONFIG OK  path={config['path']}  schema={config['schema']}",
        f"platform   : kind={report.get('platform', {}).get('kind', '-')}"
        f"  plugin={report.get('platform', {}).get('plugin', '-')}",
        f"adapter    : {report.get('adapter', {}).get('detail', '-')}",
        f"display    : {display['width']}x{display['height']} @{display['dpi_scale']}"
        f"  profile={display['profile']}  detected={display['detected']}",
        f"data_dir   : {report['data_dir']}",
        f"llm        : {llm['provider']}/{llm['model']}  key={llm['api_key']}  base_url={llm['base_url']}",
        f"runtime    : dry_run={runtime['dry_run']}  log_level={runtime['log_level']}"
        f"  moments={runtime['moments_enabled']}  allow_ratio_fallback={runtime['allow_ratio_fallback']}",
        f"logging    : {report.get('logging', {}).get('log_path', '-')}",
        f"audit      : {report.get('logging', {}).get('audit_path', '-')}",
        "dirs       :",
    ]
    for entry in report["directories"]:
        lines.append(f"  - {entry['path']}  {'ok' if entry['writable'] else 'FAIL: ' + entry['detail']}")
    lines.append("databases  :")
    for entry in report["databases"]:
        db_status = "ok" if not entry["problems"] else "FAIL: " + "; ".join(entry["problems"])
        lines.append(
            f"  - {entry['kind']}: {entry['path']}  version={entry['version']}  tables={entry['tables']}  {db_status}"
        )
    lines.append("checks     :")
    for check in report["checks"]:
        lines.append(f"  [{'OK' if check['ok'] else 'FAIL'}] {check['name']} :: {check['detail']}")
    lines.append(f"RESULT: {status}")
    return "\n".join(lines)


def run_selftest(argv: Sequence[str]) -> int:
    """`python -m wechat_agent selftest [--json] [--config PATH]`"""
    json_mode, config_path, error = _parse_selftest_args(list(argv))
    if error:
        print(error, file=sys.stderr)
        return 2
    try:
        cfg = load_config(config_path)
        report = build_selftest_report(cfg)
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"DATA DIR ERROR: {exc}", file=sys.stderr)
        return 2
    if json_mode:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_selftest(report))
    return 0 if report["ok"] else 2
