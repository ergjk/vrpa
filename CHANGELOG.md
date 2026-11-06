# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与
[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Changed
- 框架包名最终定名 **`vrpa`（Vision RPA）**；旧包名兼容 shim 已彻底移除；环境变量统一 `VRPA_*`（应用层保留 `WECHAT_AGENT_*` 回退）

### Added
- M0-F-02 `vrpa` 框架包落地：
  - `vrpa/__init__.py`：框架版本 `__version__` 与契约版本 `INTERFACE_VERSION = "1.0"`
  - `vrpa/logging.py`：命名空间可配置的日志/审计/trace_id/脱敏/自检（默认中性名 `vrpa`）
  - `vrpa/errors.py`：平台无关异常族（基类 `AgentFrameworkError`、`SessionSwitchFailed`）
  - `scripts/quality.bat`：绕过 PowerShell 执行策略的一键门禁入口
- 框架测试：`tests/test_framework_errors.py`、`tests/test_framework_logging.py`、`tests/test_deprecation.py`

### Changed
- `wechat_agent/main.py`、`core/config.py`、`memory/db.py` 改为直接使用 `vrpa.*`（应用内部不再依赖 shim）
- 旧应用层类名别名已按指令彻底移除（统一使用 `AgentFrameworkError` / `SessionSwitchFailed`）
- 启用 mypy strict（`vrpa` 3 个文件 0 error）；覆盖率门禁提升到 87%+
- 修复 `pyproject.toml` 无效配置 `cache_dir`（pytest 9 告警）

### Added
- M0-F-03 配置 schema v2 与平台插件：
  - `vrpa/config/`：env 解析、通用校验原语、平台插件协议与注册表、YAML 加载与 v1->v2 自动升级、默认值深度合并
  - `wechat_agent/config/wechat_schema.py`：微信平台插件（`platform.options` 校验 + 插件版本）
  - `config.yaml` 升级 schema 2（`platform.kind: wechat` + `platform.options`）
  - 环境变量统一 `VRPA_*`；旧名回退并打 DeprecationWarning；`selftest` 输出平台信息与迁移记录

- M0-F-04 平台适配器契约与合规测试套件：
  - `vrpa/ports.py`：五端口协议（ElementTree / Perception / Executor / Brain / MemoryStore）+ 跨层 DTO
  - `vrpa/platform.py`：`PlatformAdapter` 协议、`AdapterRegistry`、`AdapterInfo`（结构判定，避免 runtime_checkable 数据成员限制）
  - `vrpa/testing/fakes.py`：平台无关 Fakes（可注入定位 / 会话切换 / 发送 / LLM 失败场景）
  - `vrpa/testing/contracts.py`：适配器合规测试套件（10 项检查）+ CLI `python -m vrpa.testing.contracts --adapter 模块:属性 [--json]`
  - 判定标准：Fake 适配器全绿、反例可检出；第三方适配器必须全绿才能接入

### Planned
- M0-F-03：配置 schema v2（`platform:` 命名空间 + 平台插件式校验）
- M0-F-04：`PlatformAdapter` 协议 + 适配器注册表 + 合规测试套件 `vrpa.testing.contracts`
- M0-F-05：微信适配器注册、应用层去框架化
- M0-F-06：弃用清理、适配器编写指南定稿
- M0-07：环境体检 `doctor`
- M0-08：控制台骨架
- M0-09：红线自检 `selftest --redlines`

## [0.1.0] - 2026-11-06

### Added
- M0-01 包骨架与 CLI 骨架：子命令注册表、退出码契约、Ctrl+C 优雅退出
- M0-02 配置系统：`config.yaml` 全量 schema、`.env` 加载、密钥掩码、`selftest`
- M0-03 日志与审计：RotatingFileHandler、trace_id、JSONL 审计、脱敏、日志自检
- M0-04 统一异常体系：`ExitCode` 单真源、15 类异常、`to_dict`/`to_audit`、全局兜底
- M0-05 接口契约：5 个核心 Protocol、6 个 DTO、V1.1/V1.2 空接口、R1/R3 静态扫描
- M0-06 双库与迁移：`schema.sql` 单一真源、WAL、预迁移备份、`db-check --schema/--repair`
- M0-F-01 框架治理基线：ADR 0001-0003、目标架构文档、适配器编写指南、`pyproject.toml`、`scripts/quality.ps1`