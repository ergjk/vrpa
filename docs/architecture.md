# 目标架构：双包分层（M0-F 框架硬化）

> 状态：**Accepted**（见 [ADR-0001](ADR/0001-framework-layering.md)）
> 基线：M0-F-01（2026-11-06）；F-02 起逐项落地。
> 约束：本文档描述**目标态**；当前状态在 §7 迁移路线中标注。

## 1. 分层与依赖规则

| 层 | 包 | 职责 | 允许依赖 |
|---|---|---|---|
| 框架底座 | `vrpa` | 配置内核、日志与审计、异常与退出码、端口协议（Ports）、DTO、平台适配器契约与注册表、CLI 骨架、测试工具（Fakes/Contracts） | **仅标准库** |
| 微信应用 | `wechat_agent` | 微信适配器（顶层窗口/假 UIA 树/锚点匹配/框选采集/解析）+ 记忆/推理/执行/控制/插件 + 组装入口 | `vrpa` + RPA/LLM 第三方库 |
| 工具与文档 | `tests/`、`scripts/`、`docs/` | 测试、质量门禁、ADR 与指南 | 两者 |

依赖方向（单向，禁止反向与横向）：

```
tests  ->  wechat_agent  ->  vrpa  ->  stdlib
```

- `vrpa` 内**不得** import `wechat_agent`；
- `wechat_agent` 内不得再出现「平台无关能力」的私有实现（配置加载/日志/异常/CLI 骨架必须用框架能力）；
- F-04 起由自动测试强制（import 边界扫描 + 平台名扫描）。

## 2. 目标目录树

```
vrpa/                       # 框架底座（可独立发布为 vrpa）
├── __init__.py                #   __version__ / INTERFACE_VERSION
├── config/                    #   通用配置：加载(YAML/.env)、校验、合并、schema 版本
├── logging.py                 #   日志/审计/trace_id/脱敏（名字空间中性）
├── errors.py                  #   异常族 + ExitCode 单真源
├── ports.py                   #   ElementTree / Perception / Executor / Brain / MemoryStore + DTO
├── platform.py                #   PlatformAdapter 协议 + AdapterRegistry + 能力声明
├── element_tree.py            #   通用 profile 元素树（严格失败语义，M0-F-05）
├── memory/                    #   双库引擎：DDL/迁移/备份/自检 + SQLite MemoryStore（M0-F-05）
├── cli.py                     #   通用 CLI 骨架（注册表/退出码/异常兜底/帮助）
└── testing/
    ├── fakes.py               #   Fake 全套（M4 全链路依赖）
    └── contracts.py           #   重点：适配器合规测试套件（第三方实现必须全绿）

wechat_agent/                  # 微信应用 + 微信适配器
├── adapters/wechat/           #   window/uia_tree/anchor_match/capture/parser/session_switch
├── config/wechat_schema.py    #   平台字段校验（插件式挂到框架 config）
├── memory/ brain/ act/ control/ plugins/
└── main.py                    #   组装：注册 wechat adapter + 应用子命令
```

## 3. 平台无关性红线（框架包）

1. `vrpa` 的**标识符与默认值**不得含平台名（`wechat` / `qq` / `dingtalk` …），只允许出现在文档字符串举例中；
2. 平台差异只能通过 `PlatformAdapter` 实现 + 配置插件注入；
3. 日志/错误/CLI 的名字空间、环境变量前缀、提示文案一律中性化（`VRPA_*`）。

## 4. 关键契约（F-02 ~ F-04 落地）

- **Ports**：`ElementTree`（元素定位，失败即中止）、`Perception`（会话切换 + 采集）、`Executor`（发送 + 三校验）、`Brain`（推理）、`MemoryStore`（双库门面）；
- **PlatformAdapter**：`kind` / `capabilities` / `create_perception()` / `create_element_tree()` / `create_parser()` / `create_session_switcher()` / `config_schema()`；
- **AdapterRegistry**：`register(adapter_cls)` / `create(kind, config)`；未知平台给可读错误；
- **Contracts kit**：`vrpa.testing.contracts.run_all(adapter_factory)`，覆盖端口行为、失败语义（不得兜底猜坐标）、消息流边界（图像识别不得出现在消息路径）。

「可替换感知层」的判定标准：**第三方适配器能通过 contracts kit 全绿**，而不是文档上说"支持"。

**平台通用逻辑归属（M0-F-05 收口）**：

- 双库引擎（`vrpa/memory/db.py` + `schema.sql`）、`SQLiteMemoryStore`（`vrpa/memory/store.py`）、
  profile 元素树（`vrpa/element_tree.py`）已上提框架；`wechat_agent` 只保留「Config 绑定 + 微信字段」薄适配。
- **解析策略分发（Strategy Dispatcher）**：策略执行器由 `vrpa` 在 M2 提供（`parser_pack` 目前仅声明策略名与
  样例要求）；应用层不承载分发逻辑，也不允许按平台写分支。

## 5. 兼容策略（已批准）

| 项 | 策略 |
|---|---|
| 旧模块路径 `wechat_agent.core.*` | 保留 shim 模块，re-export 框架符号；首次导出打 `DeprecationWarning`，下一里程碑删除 |
| 环境变量 | `WECHAT_AGENT_*` 与新 `VRPA_*` 并存一个版本；同时设置时新名优先 |
| 配置 | schema v1（`wechat:` 段）自动升级为 v2（`platform:` 段），升级时打印迁移提示 |
| 类名 | 旧应用层类名别名已按指令彻底移除（统一 `AgentFrameworkError`） |
| 接口 | `INTERFACE_VERSION` 语义化；破坏性变更必须升主版本并提供迁移说明 |

## 6. 质量门禁（M0-F-01 生效）

| 门禁 | 工具 | 范围 | 判定 |
|---|---|---|---|
| 静态检查 | `ruff check`（E/F/I/UP/B/SIM） | 全仓库 | 0 问题 |
| 格式化 | `ruff format --check` | 全仓库 | 无差异 |
| 类型 | `mypy --strict` | `vrpa`（F-02 起） | 0 error |
| 测试 | `pytest` | `tests/` | 全绿 |
| 覆盖率 | `pytest-cov` | 两包整体 | ≥ 85%（框架部分后续提高） |
| 一键 | `scripts\quality.bat`（推荐，自动绕过 PS 执行策略）/ `scripts/quality.ps1` | — | `QUALITY GATE: PASS` |

## 7. 迁移路线

| 子里程碑 | 内容 | 完成判据 |
|---|---|---|
| **M0-F-01（本轮）** | ADR 0001-0003、本文档、适配器指南、`pyproject.toml`、`scripts/quality.ps1`、`CHANGELOG.md` | 82 测试全绿；ruff/format 通过；覆盖率 ≥ 85% |
| M0-F-02 | `vrpa` 包：logging / errors / config 内核迁移 + `wechat_agent.core.*` shim | 旧 import 全部可用且打 warning；新包测试通过；mypy strict 生效 |
| M0-F-03（已完成） | 配置 schema v2：`platform:` 命名空间 + 插件式校验 + `VRPA_*` | 旧 `wechat:` 配置自动升级；`selftest` 输出平台信息 |
| M0-F-04（已完成） | `ports.py` / `platform.py` / `AdapterRegistry` / `testing.contracts` / `testing.fakes` | contracts kit 可运行；Fake 适配器全绿；反例可检出 |
| M0-F-05（已完成） | 微信适配器注册 + 应用层去框架化（memory/brain/act/control 接 ports） | `WeChatAdapter` 接入 `AdapterRegistry`；应用接口与 `vrpa.ports` 统一；契约套件 10/10 全绿 |
| M0-F-06 | 弃用清理、指南定稿、README/CHANGELOG 更新 | 无 DeprecationWarning；文档评审通过 |

## 8. 与 V1.0 功能里程碑的关系

框架硬化不改变 V1.0 功能边界：M0-07（doctor）、M0-08（控制台骨架）、M0-09（红线自检）在 F-06 后继续；
M1~M6 的功能实现直接长在新分层上，避免二次返工。