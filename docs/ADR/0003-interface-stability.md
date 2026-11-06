# ADR-0003：接口稳定、适配器契约与合规测试套件

- 状态：**Accepted / 已实现（M0-F-04 契约套件；M0-F-05 应用层统一并接入微信适配器，2026-11-06）**
- 日期：2026-11-06
- 决策人：主控官
- 关联：ADR-0001、ADR-0002

## 背景

「可替换感知层」若没有机器可验证的契约，就会退化为文档承诺。当前 `wechat_agent.core.interfaces`
只有 Protocol 与空接口，缺少适配器协议、注册表、能力声明与第三方合规测试。

## 决策

### 1. 版本化契约

- `vrpa.INTERFACE_VERSION` 采用语义化版本（MAJOR.MINOR）：
  - MAJOR：删除/重命名端口方法、改变 DTO 必需字段、改变失败语义；
  - MINOR：新增端口方法（必须带默认实现或标注 optional 能力）、新增 DTO 可选字段；
- 任何 MAJOR 变更必须：新增 ADR + CHANGELOG 条目 + 迁移说明 + contracts kit 同步升级；
- PATCH 级别不涉及契约。

### 2. 端口最小能力集（冻结）

`ElementTree` / `Perception` / `Executor` / `Brain` / `MemoryStore` 五个端口，行为语义：

| 端口 | 必须满足 |
|---|---|
| `ElementTree` | 定位失败必须抛 `ElementNotVisible`，**禁止返回兜底坐标**；动作后必须可失效缓存 |
| `Perception` | 消息内容唯一来源是采集通道（剪贴板/接口），**禁止图像识别消息内容**；会话切换失败必须抛 `SessionSwitchFailed` |
| `Executor` | 发送前必须完成三重校验；失败必须抛 `VerifyFailed` 且不得留下半成品消息 |
| `Brain` | 超时/失败必须抛 `LLMError`，不得返回空串冒充成功 |
| `MemoryStore` | 写回幂等；去重相关查询必须返回旧→新顺序 |

### 3. PlatformAdapter 与注册表

```python
class PlatformAdapter(Protocol):
    kind: str  # "wechat" / "qq" / "dingtalk"

    def capabilities(self) -> frozenset[str]: ...
    def create_ports(self, config) -> Ports: ...
    def config_schema(self) -> PlatformConfigSchema: ...
    def element_tree_profile_spec(self) -> ProfileSpec: ...
    def parser_pack(self) -> ParserPack: ...
```

- `AdapterRegistry.register(adapter)` / `.create(kind, config)`；重复注册、未知 kind 给可读 `ConfigError`；
- 平台能力用字符串集合声明（`group_chat` / `moments` / `file_transfer` …），应用据此降级。

### 4. 合规测试套件（唯一判定标准）

`vrpa.testing.contracts` 提供 `run_all(adapter_factory) -> ContractReport`，至少覆盖：

1. 端口存在性与签名（含 keyword-only 参数、返回 DTO 类型）；
2. 失败语义：定位失败不兜底、发送校验失败不回车、LLM 失败不返回伪造成功；
3. **消息流边界**：消息路径模块不得出现图像/OCR 依赖（R3 红线）；
4. 幂等：重复 init/迁移/写回不产生重复数据；
5. Fake 适配器必须全绿，故意破坏的适配器必须被检出（meta-test）。

验收：`tests/test_contracts_kit.py` 中 Fake 适配器全绿 + 3 个反例被检出。

## 兼容与弃用

- 旧 `wechat_agent.core.interfaces` 保留 re-export shim（`DeprecationWarning`）；
- 弃用窗口 = 一个里程碑；删除时升 MAJOR 并更新 CHANGELOG；
- 第三方适配器不需要改应用代码即可接入（契约测试 + 注册表）。

## 风险

- 契约测试过度约束实现细节 → 只约束行为语义，不约束定位/解析技术路线；
- 端口最小集不够用 → 应用层可在端口之上扩展接口，不修改框架。