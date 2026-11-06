# ADR-0002：配置 schema v2（平台命名空间 + 插件式校验）

- 状态：**Accepted**
- 日期：2026-11-06
- 决策人：主控官
- 关联：ADR-0001、ADR-0003

## 背景

当前 `config.yaml` 顶层是 `schema: 1` + `wechat:` 段，`core/config.py`（967 行）里硬编码了
`WechatConfig`、`process_names`、`switch_chat`、`WECHAT_AGENT_CONFIG` 等平台字段与环境变量。
复用到底座的其他平台（QQ/钉钉）必须改核心校验器，违反 ADR-0001 的平台无关性红线。

## 决策

配置升级为 **schema v2**，结构：

```yaml
schema: 2
platform:
  kind: wechat            # 由适配器注册表解析，未知平台 -> ConfigError
  options:                # 平台私有配置，由该平台的校验插件负责
    window_title_regex: "^(微信|WeChat)$"
    process_names: ["WeChat.exe", "WeChatAppEx.exe"]
    switch_chat: search_box
# 通用段保持不变：app / uia_tree / capture / llm / humanize / ratelimit / safety / control / plugins
```

要点：

1. **框架内核只校验通用段**；`platform.options` 交给 `PlatformAdapter.config_schema()` 返回的校验器；
2. 环境变量前缀统一为 `VRPA_*`；旧 `WECHAT_AGENT_*` 保留一个版本，新名优先，读取旧名时打 `DeprecationWarning`；
3. 默认配置路径支持 `VRPA_CONFIG`，旧 `WECHAT_AGENT_CONFIG` 兼容；
4. `schema: 1` 配置在加载时**内存内自动升级**为 v2 并打印迁移提示；提供 `config upgrade` 子命令在 F-03 写回文件；
5. `selftest` 输出新增平台信息（kind / adapter 版本 / 能力矩阵）。

## 兼容与验收

- 现有 `tests/test_config.py` 全部保留并通过（v1 夹具自动升级路径必须被覆盖）；
- 新增测试：v2 正常加载、未知 platform.kind 报 ConfigError、平台 options 校验失败报错（指明平台）、
  新旧环境变量优先级、v1→v2 升级幂等；
- `docs/architecture.md` §5 兼容策略表为唯一依据。

## 影响文件

`wechat_agent/core/config.py`（拆分：通用内核 -> `vrpa/config/`；平台字段 -> `wechat_agent/config/wechat_schema.py`）、
`config.yaml`、`tests/test_config.py`、`README.md`（配置示例）。

## 风险

- 旧配置字段语义漂移：用「v1 夹具 + 升级后断言」双测兜住；
- 第三方平台配置滥用通用段：在 `selftest` 输出未识别字段警告（F-03 起）。