# VRPA-WeChat-Agent

> **VRPA（Vision RPA）通用 RPA 框架底座 + 微信参考实现** · MIT License
> 状态：**M0 ~ M6 全部阶段已完成，真机联调进行中**（微信 4.x / Windows；537 项测试全绿 · 覆盖率 86.84% · ruff / mypy strict 全绿 · 默认 `dry_run`）
> M4：队列/拟人延迟/限流/状态机熔断/`--simulate`/接管；M5：OpenAI 兼容客户端（重试+用量）、Prompt 预算裁剪、后处理安全过滤、人设热加载、`llm-ping`。

---

## 1. 这是什么：两层结构

本项目**不是**一个"微信专属脚本"，而是一个可以复用的 **Vision RPA 框架 + 参考实现**：

| 层 | 包 | 定位 | 依赖 |
|---|---|---|---|
| **通用框架底座** | `vrpa` | 把 RPA 场景中的通用能力沉淀为平台无关的框架：**双库记忆存储引擎、异常与退出码契约、拟人化调度队列、视觉锚点匹配、配置/日志/审计、平台适配器契约与合规测试套件** | Python 标准库（视觉子系统需 `numpy` + `opencv-python`） |
| **微信参考实现** | `wechat_agent` | 基于 `vrpa` 接入微信 PC 的真实实现：**假 UIA 树视觉定位、框选 + 剪贴板采集、状态回写去重**、LLM 推理、HITL 控制台与插件 | `vrpa` + RPA/LLM 第三方库 |

```
┌──────────────────────────────────────────────────────────────┐
│  wechat_agent —— 微信参考实现                                 │
│  假 UIA 树视觉定位 · 剪贴板采集 · 状态回写去重 · 控制台/插件    │
│  （QQ / 钉钉开发者：在你的应用包里写同位置的适配器即可）        │
└───────────────────────────┬──────────────────────────────────┘
                            │ 只依赖 vrpa 的公共契约
┌───────────────────────────▼──────────────────────────────────┐
│  vrpa —— 通用 RPA 框架底座（Vision RPA）                      │
│  双库存储引擎 · 异常/退出码契约 · 拟人化调度队列 · 视觉锚点匹配  │
│  配置内核 · 日志审计 · 平台适配器接口 · 适配器合规测试套件       │
└───────────────────────────┬──────────────────────────────────┘
                            │ 标准库（视觉：numpy/opencv）
                        Python stdlib
```

依赖方向是**单向**的：`wechat_agent → vrpa → stdlib`。第三方平台（QQ / 钉钉 / 飞书）只需实现 `vrpa` 的适配器契约，**不需要修改底座**；微信实现可作为参考样板。

**状态图例**：已实现（M0）／规划中（已设计，按 M1~M6 里程碑交付，任务与 DoD 见 [docs/行动清单-V1.0.md](docs/行动清单-V1.0.md)）

---

## 2. 受众导航：我该看哪一部分？

| 你是…… | 建议入口 |
|---|---|
| **只想跑一个微信机器人** | [§6.1 WeChat 快速开始](#61-wechat-快速开始) |
| **想开发 QQ / 钉钉机器人** | [§6.2 VRPA 适配器快速开始](#62-vrpa-适配器快速开始qq--钉钉--其他平台)，完整指南见 [docs/writing-an-adapter.md](docs/writing-an-adapter.md) |
| 想理解分层与依赖规则 | [docs/architecture.md](docs/architecture.md)（含 ADR 决策记录 [docs/ADR/](docs/ADR/)） |
| 想参与实现 / 验收 | [docs/行动清单-V1.0.md](docs/行动清单-V1.0.md)（M0~M6 任务、DoD、阶段门禁） |
| 想先看技术细节 | [docs/技术方案-V1.0.md](docs/技术方案-V1.0.md)（含 M0 已落地部分 + M1~M6 设计） |

---

## 3. 能力矩阵

### 3.1 框架层特性（由 `vrpa` 提供）

| 能力 | 说明 | 状态 |
|---|---|---|
| 双库存储引擎 | 流水库（历史上下文）+ 核心档案库（长期记忆）双库分离；WAL、幂等迁移、预迁移备份、FTS5 全文检索、软删 | 已实现 M0-06；M0-F-05 引擎已上提 `vrpa.memory`（应用仅保留薄适配） |
| 异常与退出码契约 | 统一异常家族 + 进程退出码（0/1/2/3/4/5/6/7/8/130），`to_dict`/`to_audit` 结构化、自动脱敏 | 已实现 M0-04 |
| 日志 / 审计 / 脱敏 | RotatingFileHandler、trace_id 贯穿、JSONL 审计、API Key / 手机号 / 身份证 / 邮箱打码 | 已实现 M0-03 |
| 配置内核 | 通用配置加载、校验、环境变量覆盖（`VRPA_*`）；通用段（app/uia_tree/capture/llm/humanize/ratelimit/safety/control/plugins/display）已上提 `vrpa.config.schema`，平台字段由适配器插件校验 | 已完成 M0-F-03 / F-06 |
| 拟人化调度队列 | 优先级 FIFO、跨会话轮转、限流 / 静默时段、可打断的拟人延迟（思考 / 打字 / 发送节奏） | 已实现 M4（queue / delay / scheduler / machine / loop）；人手化节奏为 V1.0 启发式，V1.2 计划学习真人节奏 |
| 视觉锚点匹配 | 元素树 profile + 多尺度模板匹配定位（失败即中止，禁止坐标兜底），供各平台适配器复用 | 已实现 M1（`vrpa.vision`：profile / matcher / locator / calibration） |
| 平台适配器契约 | `PlatformAdapter` 协议 + `AdapterRegistry` + **适配器合规测试套件**（`vrpa.testing.contracts`，第三方实现必须全绿才能接入） | 已实现 M0-F-04（微信适配器 M0-F-05 全绿接入） |

### 3.2 应用层特性（由 `wechat_agent` 提供，可作为适配器示例）

| 能力 | 说明 | 状态 |
|---|---|---|
| 假 UIA 树视觉定位 | 微信 4.x 无原生控件树，自建 JSON 元素树 + 锚点图匹配定位点击目标（只服务"操作界面"） | 已实现 M1-01~06（calibrate / validate-tree / locate 可用） |
| 剪贴板纯文本采集 | 消息流**唯一**来源：鼠标框选 + `Ctrl+C`，禁止对消息做图像识别（红线 R3） | 已实现 M2-01~06；微信 4.x 三段式格式已适配（`wechat_block`） |
| 状态回写去重 | 发送后立即以 `assistant` 写库；下轮抓屏按文本哈希去重；无前缀消息识别为主人多端发送，入库不回复 | 已实现 M3-01~07（去重/多端/回写/档案/job/回放） |
| LLM 推理 | Persona + 长期记忆 + 最近 N 轮上下文，Token 预算裁剪、输出清洗与安全过滤 | 规划中 M5 |
| 发送三重校验 | 会话 / 焦点 / 内容三校验通过才回车；失败清空重试，绝不重发 | 规划中 M6 |
| HITL 控制台 | 暂停/恢复、人设热更新、记忆查询、`/say` 接管、急停热键 | 规划中 M6 |
| 可插拔插件 | 插件协议 + `#发圈` 示例（默认关闭） | 规划中 M6 |
| 微信适配器装配 | `WeChatAdapter` 实现 `PlatformAdapter` 并注册到 `ADAPTER_REGISTRY`；`create_ports()` 组装记忆 / 元素树 / 感知 / 执行 / 推理五端口（记忆已可用，其余按 M1/M2/M5/M6 就绪） | 已实现 M0-F-05 |

---

## 4. 仓库结构

```
vrpa/                     # 通用框架底座（可独立发布/复用）
  __init__.py             #   框架版本 + 契约版本 INTERFACE_VERSION
  logging.py              #   日志 / 审计 / trace_id / 脱敏（命名空间可配置）
  errors.py               #   平台无关异常族 + 退出码契约
  element_tree.py         #   通用 profile 元素树（严格失败语义，M0-F-05）
  memory/                 #   双库引擎 / SQLite MemoryStore（M0-F-05）
                          #   HistoryStore / 尾部去重 / 档案库 / 异步 job（M3）
  knowledge/             #   只读知识块 / Provider 协议 / 检索门面 / 文件热加载（M5-02）
  llm/                    #   client / prompt 预算 / postprocess / persona / policy（M5）
  plugins/                #   插件协议与故障隔离管理器（M6-04）
  runtime/                #   失败自保 / 崩溃恢复快照（M6-03）
  scheduling/             #   队列 / 拟人延迟 / 限流调度 / 状态机与熔断 / 编排循环（M4）
  vision/                 #   profile schema / 多尺度匹配 / 定位缓存 / 校准核心（M1）
                          #   窗口后端（win32 优先）/ DPI 感知 / 输入驱动 / 校准包（M2-M6）
  parsing/                #   解析策略分发器（StrategyDispatcher，M2-04）
  config/                 #   配置内核：env / validators / plugin / loader / schema（通用段）
  ports.py                #   五端口协议 + 跨层 DTO（M0-F-04）
  platform.py             #   PlatformAdapter 协议 + AdapterRegistry（M0-F-04）
  testing/                #   Fakes + contracts 合规测试套件（M0-F-04）
tests/                    # 537 项测试（配置/日志/异常/接口/双库/CLI/端口/契约/兼容 shim）
docs/                     # 技术方案、行动清单、架构、ADR、适配器指南
scripts/quality.ps1|.bat  # 一键质量门禁（ruff + mypy strict + pytest + coverage）
scripts/mouse_record.py   # 真机调试：记录手动拖选鼠标轨迹（用于校准 capture.drag）
scripts/input_check.py    # 真机调试：检查鼠标注入/剪贴板是否可用（无需微信）
wechat_agent/             # 微信参考实现（六层模块见 §5.1）
  main.py                 #   CLI 入口 / 子命令注册 / 退出码映射
  adapter.py adapters.py  #   WeChatAdapter（五端口装配）+ ADAPTER_REGISTRY（M0-F-05）
  core/                   #   配置、日志、异常 shim、接口契约（与 vrpa.ports 统一）
  memory/                 #   双库门面 shim + Config 薄适配（引擎已上提 vrpa.memory）
  perception/             #   ProfileElementTree 绑定 + 剪贴板采集 Perception（M1-M2）
  brain/ act/             #   推理 Brain（M5）；执行 Executor（M6，干跑已可用）
  control/ plugins/ tools/  #   控制台（M6）；插件（M6）；calibrate / locate / validate-tree / probe / replay / run / llm-ping / send / plugin / report / soak / acceptance / db-check 工具
  personas/               #   人设文件（mtime 变化自动热加载，M5-04）
  data/knowledge/         #   静态只读知识（global/ 与 chats/<chat_id>/，绝不写入记忆库）
  perception/             #   ElementTree / 窗口 / 会话切换 / 采集 / 解析器（M1-M2）
```

---

## 5. 微信参考实现（`wechat_agent`）

### 5.1 六层模块

| 层 | 组件 | 职责 | 状态 |
|---|---|---|---|
| 感知层 | `pywinauto` + 假 UIA 树 + `pyperclip` | 定位界面元素、框选并复制消息文本 | 已实现 M1-M2（ElementTree / 窗口 / 会话切换 / 采集） |
| 记忆层 | SQLite 双库 + 去重对齐 | 流水去重、长期记忆提炼与召回 | 已实现 M3（HistoryStore / 尾部对齐 / LongTermMemory / 异步 job） |
| 推理层 | DeepSeek / OpenAI 兼容 API | 上下文组装、回复生成与清洗 | 已实现 M5（客户端/预算/后处理/人设热加载/llm-ping） |
| 执行层 | `pyautogui` + 三重校验 | 粘贴、校验、回车、状态回写 | 已实现 M6-01（内容/目标/回读三重校验；默认 dry_run，真实发送需显式授权 + 真机验收） |
| 控制层 | CLI 控制台 | 暂停/恢复、人设热更新、`/say` 接管 | 已实现 M6-02（指令集 + 中文 NLU 路由；GUI 托盘待后续） |
| 扩展层 | 插件协议 + Task Scheduler | `#发圈` 等 RPA 指令 | 已实现 M6-04（Plugin 协议 + 故障隔离 + moments 示例）；Task Scheduler 待后续 |

### 5.2 感知层规范：假 UIA 树（微信适配器实现要点）

> 完整设计见 [docs/技术方案-V1.0.md](docs/技术方案-V1.0.md) §4.3 / §6。本节只保留**适配器作者需要遵守的要点**。

1. **定义**：用本地 JSON 描述界面元素树（"假 UIA 树"），替代微信 4.x 缺失的原生控件树；它只回答"点哪里/输到哪"，**不读取消息内容**。
2. **元素结构**：相对比例坐标（0~1，相对父元素）+ 特征截图（Anchor Image，可多张按序匹配）+ `role`（container / region / anchor）+ `purpose`（click / input / drag / guard / plugin）。
3. **定位原理**：取顶层窗口客户区 → 沿父链裁剪屏幕 → OpenCV 多尺度模板匹配（`TM_CCOEFF_NORMED`）→ 比例换算绝对坐标。
4. **失败语义（硬性）**：匹配低于阈值即 `ElementNotVisible`，立即中止并重试，**绝不复用旧坐标、绝不用比例坐标兜底**；分辨率/DPI/窗口矩形变化时 `ProfileMismatch`，要求重新校准。
5. **边界（红线 R3）**：假 UIA 树仅用于操作界面；**消息流只准走「鼠标框选 + `Ctrl+C` 剪贴板」**，禁止对消息做图像识别 / OCR。
6. **校准**：`calibrate` 逐元素框选 → 存锚点图 → 立即回验；`validate-tree --strict` 现场自检（M1-04/05 已交付）。

### 5.3 工作机理与数据流

1. **触发**：定时器 tick；假 UIA 树切到目标会话并定位消息区。
2. **采集**：框选消息区 → `Ctrl+C` → 剪贴板文本（唯一消息来源）。
3. **清洗与路由**：解析为结构化消息；与流水库尾部锚点对齐：
   - 已入库 → 忽略（去重）；
   - 无前缀且不在库 → 判定为主人多端发送，入库不回复；
   - 有前缀（他人）→ 合并入 FIFO 队列。
4. **上下文**：核心档案库召回 + 会话摘要 + 最近 N 轮流水 + Persona。
5. **推理**：LLM 生成回复，施加拟人化随机延迟（拟思考 / 拟打字）。
6. **执行**：假 UIA 树定位输入框 → 粘贴 → 三重校验 → 回车 / 点发送。
7. **回写**：发送成功即以 `assistant` 写库，闭合去重与自指识别。

---

## 6. 快速开始

### 6.1 WeChat 快速开始

> 适合：已有微信 PC 4.x、想直接跑微信机器人的开发者。

```powershell
# 1) 安装依赖（Python 3.10+，当前验证环境 3.14.7）
pip install -r requirements.txt

# 2) 配置
copy .env.example .env        # 填入 DEEPSEEK_API_KEY
# 编辑 config.yaml（schema v2：platform.kind / platform.options；
# 若沿用 v1 的顶层 wechat 段，加载时会自动升级并打印迁移提示）
# 目标会话、限流、拟人延迟、dry_run 保持 true

# 3) 环境自检 + 双库初始化
python -m wechat_agent doctor                  # 依赖/DPI/微信窗口/写权限体检
python -m wechat_agent selftest
python -m wechat_agent db-check

# 4) 视觉校准与自检（微信 4.x）
python -m wechat_agent calibrate --warmup 10 --elements main_window,chat_title,search_box,message_area,input_box,send_button
python -m wechat_agent validate-tree --strict          # 现场自检（真实截屏）
python -m wechat_agent locate input_box --json         # 打印坐标/分数/缩放
python -m wechat_agent probe --chat 目标会话 --warmup 5 --debug --dump data/probe_raw.txt  # 真实采集诊断（只读，不落库不回复）
python -m wechat_agent probe --text 样例.txt --json    # 离线解析诊断
python -m wechat_agent replay --scenario tests/fixtures/dedup_scenarios/01_basic_overlap.json  # 去重回放
python -m wechat_agent run --simulate --scenario tests/fixtures/simulation/01_basic_flow.json   # 全链路 dry-run 模拟
python -m wechat_agent run --real --chat 目标会话 --warmup 8 --settle 3 --json  # 真机 dry-run（真实采集/入库/LLM，不真实发送）
# run --real 输出 timing（warmup/activate/switch_session/capture/ingest/reply/ticks/total 毫秒）
python -m wechat_agent llm-ping                # LLM 连通性（需 DEEPSEEK_API_KEY）
python -m wechat_agent send --chat 张三 --text 你好   # 控制台发送（默认 dry_run）
python -m wechat_agent report                  # 运行报告（只读）
python -m wechat_agent soak --iterations 5     # 浸泡测试（simulate，纯 Fake）
python -m wechat_agent acceptance              # 生成真机验收清单

# 4.1) 分享/复用校准包（可选）
python -m wechat_agent calibrate --export ./share/wechat-1280x720@1      # 导出
python -m wechat_agent calibrate --import ./share/wechat-1280x720@1      # 导入（目标已存在需 --force）
# 或直接用外部路径（无需复制）：config.yaml -> uia_tree.profile_path / anchors_root 填绝对路径
# 详见 docs/calibration-package.md

# 5) 真机联调说明
python -m wechat_agent run --simulate --scenario <场景.json>  # Fake 全链路（不触发真实键鼠）
# 真实 dry-run 已可用：采集→解析→去重入库→LLM→dry_run 三重校验→回写
# 真实发送仍必须 dry_run=false + allow_real_send=true + 逐项验收。
```

> 首次真实发送前必须完成：M1 校准通过 + M2 采集验收 + M6 三重校验；`dry_run: true` 期间不会发出任何消息。

### 6.1.1 真机联调现状（V1.0，微信 4.x / Windows）

**已完成验证**

- 环境体检 `doctor`：Python/依赖/分辨率/微信窗口/写权限全部 PASS（微信未启动时窗口项为 WARN）；
- 视觉校准：`calibrate --warmup 10` 交互框选 6 个元素；`main_window`/`message_area` 为容器静态矩形（窗口位置必须固定），其余 4 个控件走锚点匹配；
- `validate-tree --strict` 全绿；真实 `probe --chat 会话` 成功采集并解析微信 4.x 三段式文本（`发送者 / 日期时间 / 内容`）。

**微信 4.x / 本机适配要点**

- 进程名为 `Weixin.exe`（配置已加入 `platform.options.process_names`）；窗口枚举 **win32 优先、UIA 兜底**，规避 UIA 枚举为空/阻塞；
- 启用 **Per-Monitor DPI 感知**，截图与鼠标坐标统一为物理像素；
- 采集剪贴板加 **防伪哨兵**：`Ctrl+C` 未生效时直接报错，不会把终端/旧剪贴板内容当消息；
- 部分 Windows 环境下 `pyautogui` 需要**管理员 PowerShell** 才能注入鼠标；可用 `scripts/input_check.py` 自测；
- 微信窗口位置/大小/DPI 必须与校准时一致（容器为静态坐标）。
- 身份映射（可选）：`data/identity.toml`（示例 `identity.example.toml`，手写 TOML、支持注释）。有备注时会话名=备注、昵称写入 `nicknames` 用于切会话校验；**无备注时会话名=昵称**，此时可不配映射，但昵称变更会改变会话主键，建议常用联系人设置备注。

**当前边界**

- 消息流只支持**文本**（含 Unicode emoji 字符）；原生表情包/图片/语音/文件/引用回复不在 V1.0 范围（`text_only`，红线 R3 禁止图像识别）；
- 真实 dry-run 已接为命令：`run --real --chat 会话 --warmup 8 --settle 3`（真实采集/入库/LLM，不真实发送；单次 `--ticks 1` 只处理 1 条回复，队列剩余属正常）；切会话每个操作间隔由 `capture.switch_delay`（默认 0.5s）控制；去重允许跳过库尾部不在本次窗口内的消息（如 dry-run 未发送的 out）；
- 人手化拖拽/停留为 **V1.0 启发式**（时长、抖动、泊松停留），仅作节奏过渡；V1.2 计划用授权采样学习真人节奏（不记录消息内容）。

### 6.2 VRPA 适配器快速开始（QQ / 钉钉 / 其他平台）

> 适合：想复用 VRPA 底座做新平台机器人的开发者。**不要改 `vrpa` 底座**，只写适配器。

1. 阅读 [docs/writing-an-adapter.md](docs/writing-an-adapter.md)（适配器契约、能力矩阵、校准规范、常见坑）；
2. 实现 5 个端口（Ports）：`ElementTree` / `Perception` / `Executor` / `Brain` / `MemoryStore`；
3. 提供平台配置校验器（`PlatformAdapter.config_schema()`）与元素树 profile 规范；
4. 提供消息解析策略包（输入=采集通道原始文本，输出=`IncomingMessage` 列表，附 ≥15 份真实样例）；
5. 实现 `PlatformAdapter` 并注册到 `AdapterRegistry`；
6. 跑合规测试套件 `python -m vrpa.testing.contracts --adapter <模块>:<类> --json`（M0-F-04 已交付）与 `scripts\quality.bat`，全绿即接入成功。

> 参考实现：本仓库微信适配器即样例——`python -m vrpa.testing.contracts --adapter wechat_agent.adapter:WeChatAdapter`（M0-F-05 起 10/10 全绿），可对照 `wechat_agent/adapter.py` + `wechat_agent/adapters.py` 实现。

---

## 7. 运行环境与依赖

- **操作系统**：Windows 10 / 11（RPA 依赖 Win32 窗口与键鼠模拟）
- **Python**：3.10+（当前验证：3.14.7；3.11/3.12 为兼容性推荐）
- **微信**：PC 版 **4.x**（假 UIA 树按该版本校准）
- **核心依赖**：`pyautogui` / `pywinauto` / `pyperclip`（RPA）、`opencv-python` + `numpy` + `Pillow`（锚点匹配）、`openai`（LLM）、`PyYAML`（配置）、`pytest`（测试）
- **权限**：普通用户即可；不要求管理员、不装驱动、不注入进程

---

## 8. 质量门禁与测试

```powershell
.\scripts\quality.bat          # 一键：ruff check → ruff format → mypy strict → pytest+coverage
python -m pytest tests -q     # 单元测试（当前 537 passed）
python -m mypy                # vrpa 框架包 strict
```

| 门禁 | 工具 | 当前状态 |
|---|---|---|
| 静态检查 | ruff（E/F/I/UP/B/SIM） | 全绿 |
| 格式 | ruff format | 全绿 |
| 类型 | mypy strict（`vrpa`） | 0 error |
| 测试 | pytest | 537 passed |
| 覆盖率 | pytest-cov | 86.84%（门禁 ≥85%） |
| 一键 | `scripts\quality.bat` | `QUALITY GATE: PASS` |

---

## 9. 文档索引

| 文档 | 内容 | 状态 |
|---|---|---|
| [README.md](README.md) | 分层定位、能力矩阵、受众导航、微信实现说明、红线 | 本文件 |
| [docs/architecture.md](docs/architecture.md) | 目标架构：双包分层（`vrpa` + `wechat_agent`）、依赖规则、M0-F 迁移路线 | Accepted |
| [docs/writing-an-adapter.md](docs/writing-an-adapter.md) | **VRPA 适配器指南**：QQ / 钉钉等平台接入步骤 | 定稿 v1.0（M0-F-06） |
| [docs/calibration-package.md](docs/calibration-package.md) | **校准包分享指南**：profile/anchors 包结构、导出/导入/外部路径 | 新增（M1） |
| [docs/ADR/](docs/ADR/) | ADR-0001 框架分层 / 0002 配置 schema v2 / 0003 接口稳定与适配器契约 | Accepted |
| [docs/技术方案-V1.0.md](docs/技术方案-V1.0.md) | 详细技术设计：假 UIA 树算法、双库、去重、队列/延迟、控制台、异常、测试策略 | M0 框架底座已完成 |
| [docs/行动清单-V1.0.md](docs/行动清单-V1.0.md) | 施工图：M0~M6 全量任务（任务描述 / 输入输出 / DoD）、阶段门禁 | M0 框架底座已完成 |
| [CHANGELOG.md](CHANGELOG.md) | 版本变更记录（Keep a Changelog） | 维护中 |
| [LICENSE](LICENSE) | MIT License（版权人：ergjk） | 生效 |

---

## 10. 工程红线与范围冻结

### 红线 1：严禁超前开发（V1.0 范围冻结）

- 当前只做 **V1.0 核心架构**；V1.1（表情/语音/撤回）与 V1.2（行为克隆/生图）**不得出现具体实现代码**；
- 最多只允许在 `vrpa` 的接口文件中保留空 Protocol，不实现、不接线、不加测试。

### 红线 2：Git 由主控官监督、Agent 执行

- 版本控制、分支管理与推送由 **Agent 执行，主控官监督与验收**；
- 每次里程碑 DoD 通过后原子提交并推送，提交信息可回溯；
- 破坏性操作（force push / 历史重写 / 删除远端分支）必须获得主控官明确指令。

### 红线 3：感知层消息流边界

- 假 UIA 树只服务"操作界面"；**消息流只准走「鼠标框选 + `Ctrl+C` 剪贴板」**；
- 禁止用图像识别 / OCR / 模板匹配读取、判断、推断消息内容；
- 由 `tests/test_boundary.py`（M2）与 `selftest --redlines`（M0-09）在 DoD 中强制。

---

## 11. 局限性与安全声明

1. **独占限制**：RPA 运行期间抢占鼠标键盘；建议副屏/虚拟机隔离运行，并提供全局急停热键与暂停指令。
2. **分辨率 / 主题依赖**：元素定位依赖锚点图；窗口大小、DPI 缩放、深色/浅色主题变化后需重新校准。校准失效时系统**中止动作而非猜测**（表现为"暂时不回复"）。
3. **富文本局限**：只处理纯文本，不解析图片 / 语音 / 视频 / 复杂富文本。
4. **平台突变**：客户端大版本更新可能导致 UI 不可匹配，需重录锚点图或升级适配器。
5. **账号风险**：采用零注入 + 低频拟人化降低风险，但第三方自动化仍有平台规则风险；仅用于个人合规场景，勿用于营销群发、自动加好友。
6. **平台无关性**：以上局限中，1/2/4 属于通用 RPA 约束；3/5 中的平台规则部分由各适配器自行声明。

---

## 12. Roadmap（V1.1 / V1.2，仅规划，V1.0 不实现）

> 以下功能在 V1.0 阶段**仅保留空接口**，需主控官立项后再开发。

- **V1.1**：动画表情（本地表情截图库 + 情绪标签匹配）、语音/TTS（虚拟声卡 + RPA 长按）、消息撤回与情绪模拟（二次审查 + 右键菜单 RPA）、开放插件生态（`#红包` / `#拍一拍`）。
- **V1.2**：行为克隆（回复节奏 / 口癖 / 常用语学习）、生图等多模态扩展。

---

## 13. AI 生成声明（AI-Generated Declaration）

1. 本项目的大量代码与文档由大语言模型（如 DeepSeek 等）辅助生成，并经主控官审阅、测试与验收后提交。
2. 本项目遵循 MIT 开源协议（详见 LICENSE 文件）；AI 生成内容不代表任何平台（包括但不限于微信、QQ、钉钉、飞书等）的官方立场，也不构成任何平台授权或背书。
3. 使用本项目进行自动化操作时，请自行遵守目标平台的服务条款与当地法律法规；因使用本项目产生的风险与责任由使用者自行承担。

## 14. License

[MIT License](LICENSE) © 2026 ergjk
