# 编写平台适配器（QQ / 钉钉 / 其他 RPA 场景）

> 状态：可用（M0-F-04：`vrpa.testing.contracts` 已交付并覆盖 10 项检查；新平台按本文接入）。
> 目标：任何人按本指南实现适配器 + 通过合规测试，即可把 `vrpa` 底座复用到新平台。

## 0. 适配器 = 平台差异的唯一载体

框架底座（`vrpa`）不包含任何平台名。新增平台只需：

1. 实现五个端口（Ports）；
2. 提供平台配置校验器；
3. 提供元素树 profile 规范与校准工具；
4. 提供消息解析策略包；
5. 实现 `PlatformAdapter` 并注册；
6. 通过 `vrpa.testing.contracts.run_all()`；
7. 补充平台文档（示例配置 / 校准步骤 / 已知限制 / 风控声明）。

## 1. 能力矩阵（先声明，再实现）

```python
CAPABILITIES = frozenset({"group_chat", "text_only"})  # 例：QQ 群聊纯文本
```

应用层只使用已声明能力；未声明能力对应功能自动降级为不可用（不抛异常、不静默乱跑）。

## 2. 端口实现清单

| 端口 | 必须回答的问题 | 禁止事项 |
|---|---|---|
| `ElementTree` | 每个可点击元素「在哪里」 | 匹配失败返回旧坐标/比例兜底 |
| `Perception` | 「当前会话的原始消息文本」 | 用图像识别/OCR 读消息内容（R3 红线） |
| `Executor` | 「把文本安全发出去」 | 跳过三重校验直接回车；重试导致重复发送 |
| `Brain` | 「生成回复」 | 失败时返回空串冒充成功 |
| `MemoryStore` | 「历史与档案的读写」 | 跨库 JOIN、破坏幂等 |

## 3. 元素树 profile 规范（模板）

```json
{
  "schema": 1,
  "profile": "<分辨率>@<DPI>",
  "platform": { "kind": "qq", "version": "9.x" },
  "root": { "id": "main_window", "rect_source": "os_window_client_rect" },
  "elements": [
    { "id": "message_area", "role": "region", "roi": {...}, "purpose": "drag" },
    { "id": "input_box", "role": "anchor", "roi": {...}, "anchor_images": ["input_box.png"], "purpose": "input" }
  ]
}
```

要求：比例坐标相对父元素；可点击元素必须有锚点图；`validate` 必须能现场自检并在失效时报错。

## 4. 解析策略包（Parser Pack）

- 输入：采集通道返回的原始文本（这是消息内容的唯一入口）；
- 输出：`Sequence[IncomingMessage]`（发送者/时间戳/内容/置信度）；
- 必须提供 ≥ 15 份真实样例夹具与 golden 期望；
- 无法解析时必须降级为「只入库不回复」，并记录 `parser_strategy`。

## 4.5 参考实现：微信适配器（M0-F-05）

本仓库的 `wechat_agent/adapter.py` 是可直接对照的参考实现：

- `WeChatAdapter`：kind / capabilities / config_plugin / element tree profile spec / parser pack / `create_ports()`；
- `wechat_agent/adapters.py`：`ADAPTER_REGISTRY = AdapterRegistry(); ADAPTER_REGISTRY.register(ADAPTER)`；
- 验证命令：`python -m vrpa.testing.contracts --adapter wechat_agent.adapter:WeChatAdapter`（10/10 全绿）。

可直接复用的框架构件（无需自己重写）：

| 构件 | 位置 | 用途 |
|---|---|---|
| `SQLiteMemoryStore` | `vrpa.memory.store` | 双库 MemoryStore 通用实现（传 `data_dir` 即可） |
| `ProfileElementTree` | `vrpa.element_tree` | profile JSON 元素树（传 profile 路径/名/元素集合） |
| `PlatformAdapter` / `AdapterRegistry` | `vrpa.platform` | 适配器契约与注册表 |
| `contracts` / `fakes` | `vrpa.testing` | 合规套件与无环境 Fake |

策略分发（解析策略执行器）将在 M2 由 `vrpa` 提供，适配器只需提供 `parser_pack` 数据。

## 5. 注册与装配

```python
from vrpa.platform import AdapterRegistry
from myqq.adapter import QQAdapter

registry = AdapterRegistry()
registry.register(QQAdapter())
adapter = registry.create("qq", config.platform)
```

应用 `main.py` 只做「读配置 -> 选适配器 -> 装配端口 -> 注册子命令」，不得包含平台分支逻辑。

## 6. 合规验收（必须全绿）

```powershell
python -m pytest tests -q
python -m vrpa.testing.contracts --adapter myqq.adapter:QQAdapter   # 已提供（M0-F-04）
```

## 7. 平台文档模板

- 支持的操作系统与客户端版本；
- 校准步骤（元素截图规范、深色模式、多屏/DPI）；
- 已知限制（富文本/表情/撤回等）；
- 风控声明（零注入、频率上限、人工在环）；
- 与微信实现的差异清单。

## 8. 常见坑（来自微信实现）

1. DPI 缩放导致锚点图失效 → 按「分辨率@DPI」分 profile；
2. 多显示器负坐标 → 截屏与定位统一用「窗口客户端矩形」；
3. 输入法干扰 → 一律剪贴板粘贴，禁止 `typewrite` 中文；
4. 会话切换后验证 → 用采集到的首条发送者比对，不读标题 OCR；
5. 窗口失焦 → 动作前校验前台，失败即中止而不是重试点错位置；
6. 重复文本歧义 → 去重必须用尾部锚点对齐 + 计数差分，不能只比最后一条。