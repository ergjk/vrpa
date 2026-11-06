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

- M0-F-05 应用层去框架化与微信适配器：
  - `wechat_agent/core/interfaces.py`：与 `vrpa.ports` 统一（`UiaTree = ElementTree`、`MemoryHub = MemoryStore`、`ChatMessage = Message`），V1.1/V1.2 保留接口仍在应用层
  - `wechat_agent/adapter.py`：`WeChatAdapter` 实现 `PlatformAdapter`，`create_ports()` 装配五端口
  - `wechat_agent/adapters.py`：`ADAPTER_REGISTRY`（`vrpa.platform.AdapterRegistry` 实例）
  - 微信端口实现：`memory/store.py`（双库 MemoryStore：写入 / 历史 / 哈希 / 召回 / 软删）、`perception/element_tree.py`（profile 读取 + 严格 `ElementNotVisible`）、`perception/capture.py`、`act/executor.py`（dry_run 可用）、`brain/client.py`
  - `core/config.py`：平台插件经 `WeChatAdapter.config_plugin()` 装配；selftest 新增 `adapter` 检查
  - `vrpa.testing.contracts`：端口冒烟容忍「未就绪但失败语义正确」的领域错误；`run_all(adapter, options)` 支持注入配置
  - 微信适配器契约套件 **10/10 全绿**（CLI 可直接验证）

### Changed
- M0-F-05 框架化收口（按主控官指示：`wechat_agent` 降级为纯适配器插件，通用逻辑上提 `vrpa`）：
  - 双库引擎 `wechat_agent/memory/` -> `vrpa/memory/`（`db.py` 引擎 + `schema.sql` 去平台化）；应用层仅保留 db-check CLI 与引擎 API 再导出
  - `SQLiteMemoryStore` 上提 `vrpa/memory/store.py`（入参 `data_dir`）；`wechat_agent/memory/store.py` 退化为 `Config -> data_dir` 薄适配
  - `ProfileElementTree` 上提 `vrpa/element_tree.py`；微信侧只保留 required 元素集合与 Config 绑定
  - 端口资源释放：`Ports.close()` + 契约套件自动关闭 DB 连接，测试在 `-W error::ResourceWarning` 下干净通过
  - 解析策略分发（Strategy Dispatcher）确定由 `vrpa` 在 M2 提供，应用层只提供 parser pack

### Added
- M0-F-06 弃用清理、指南定稿与配置通用段上提：
  - 删除 `wechat_agent/core/errors.py`、`wechat_agent/core/logging.py` 兼容 shim（新代码直接 `vrpa.*`）
  - 删除 `wechat_agent/memory/db.py` 再导出模块；db-check CLI 迁至 `wechat_agent/tools/db_check.py`
  - 移除 `WECHAT_AGENT_CONFIG` / `WECHAT_AGENT_DATA_DIR` 旧环境变量回退（统一 `VRPA_*`）；`get_env` 取消 legacy 参数
  - 通用配置段（app / uia_tree / capture / llm / humanize / ratelimit / safety / control / plugins / display）与 `.env` 加载、显示器探测上提 `vrpa/config/schema.py`
  - `wechat_agent/core/config.py` 仅保留 `platform.options` 插件校验、`Config` 聚合与 selftest（989 -> 579 行）
  - `docs/writing-an-adapter.md` 定稿 v1.0（新增接入前检查清单）
  - 测试 206 passed / 覆盖率 91.25%

### Added
- M1 假 UIA 树校准与视觉定位（M1-01 ~ M1-06）：
  - `vrpa/vision/profile.py`：profile schema v1、加载/保存、锚点与父链/环检测（M1-01）
  - `vrpa/vision/matcher.py`：OpenCV 多尺度模板匹配（灰度、降采样、阈值失败返回 None）（M1-02）
  - `vrpa/vision/locator.py`：父区域裁剪、绝对坐标、TTL 缓存、严格 `ElementNotVisible`、validate 报告（M1-03）
  - `vrpa/vision/calibration.py` + `wechat_agent/tools/calibrate.py`：框选/离线双模式校准向导（M1-04）
  - `wechat_agent/tools/validate_tree.py`：`validate-tree --strict`（结构 + 现场定位 + `--image` 离线 + `--json`）（M1-05）
  - `wechat_agent/tools/locate.py`：`locate` 定位命令（坐标/分数/缩放）
  - `WeChatElementTree` 接入框架 `AnchorLocator`；CLI 注册 calibrate / validate-tree / locate
  - 校准包分享（M1 补充）：`vrpa.vision.package`（export/import/zip/清单校验）+ `calibrate --export/--import`
  - 配置口子：`uia_tree.profile_path` / `uia_tree.anchors_root` 支持外部绝对路径（优先于 data 目录）
  - 新增 `docs/calibration-package.md`：包结构、必需文件、导出/导入、外部路径与兼容性说明
  - 测试：profile / matcher / locator / calibration / CLI 离线链路 + 缓存性能 + 校准包；268 passed / 88.38%

### Added
- M2 框选 + Ctrl+C 采集与解析（M2-01 ~ M2-06）：
  - `vrpa/vision/window.py`：WindowBackend 协议 + pywinauto 实现（标题正则/进程名/客户端矩形/前台校验）
  - `vrpa/vision/driver.py`：Driver 协议 + pyautogui/pyperclip 实现（click/drag/hotkey/clipboard）
  - `vrpa/parsing/`：`StrategyDispatcher` + `ParsedMessage`/`ParseResult`（解析执行器归框架）
  - `wechat_agent/perception/window.py` / `session.py` / `capture.py` / `parser.py`：窗口、ensure_chat、框选采集、三种解析策略
  - `wechat_agent/tools/probe.py`：采集诊断（`--text` 离线 / `--chat` 真实，只读不落库不回复）
  - 样例库：`tests/fixtures/parser_samples/`（15 份文本 + golden 期望）
  - Fakes 扩展：`FakeWindowBackend` / `FakeDriver` / 按 id 指定矩形的 `FakeElementTree`（单测零物理环境依赖）
  - R3 红线：`tests/test_boundary.py` 静态扫描消息路径禁止 cv2/OCR/模板匹配
  - 契约套件：端口冒烟容忍 WindowNotFound/WindowNotForeground（无桌面环境仍可全绿）
  - 测试：323 passed / 86.85%

### Planned
- M1 / M2 已完成；下一步 M3（去重对齐与记忆提炼）待主控官立项
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