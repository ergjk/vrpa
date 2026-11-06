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
from vrpa.config.schema import (
    AppConfig,
    CaptureConfig,
    ControlConfig,
    DisplayInfo,
    HumanizeConfig,
    LlmConfig,
    PluginsConfig,
    RatelimitConfig,
    SafetyConfig,
    UiaTreeConfig,
    load_dotenv,
    parse_framework_sections,
)
from vrpa.config.validators import (
    as_int as _as_int,
)
from vrpa.config.validators import (
    as_str as _as_str,
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
# 平台配置对象由 wechat_agent/config/wechat_schema.py 提供；保留旧名便于应用层引用
WechatConfig = WechatPlatformOptions


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
# ============================================================================
# 各段落解析
# ============================================================================
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


# ============================================================================
# 显示器探测（仅用于 profile 命名与自检展示；精确校准在 M1 calibrate 完成）
# ============================================================================
# ============================================================================
# 对外入口
# ============================================================================
def default_config_path() -> Path:
    value = get_env(ENV_CONFIG_OVERRIDE)
    return Path(value) if value else Path(DEFAULT_CONFIG_NAME)


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """加载配置：框架内核解析/升级 -> 框架通用段校验 -> 微信专属段校验。"""
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
    sections = parse_framework_sections(raw, base)

    return Config(
        schema=schema,
        path=config_path,
        platform_kind=platform_kind,
        platform_plugin=platform_plugin,
        app=sections.app,
        wechat=wechat_cfg,
        uia_tree=sections.uia_tree,
        capture=sections.capture,
        llm=sections.llm,
        humanize=sections.humanize,
        ratelimit=sections.ratelimit,
        safety=sections.safety,
        control=sections.control,
        plugins=sections.plugins,
        display=sections.display,
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
    """调用 vrpa.logging.self_check；任何异常降级为一条失败检查，不让 selftest 崩溃。"""
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
        from vrpa.memory.db import init_databases, verify_schema
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
