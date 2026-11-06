## 变更说明

<!-- 一句话说明这个 PR 做什么、为什么 -->

## 改动范围

- [ ] 框架 `vrpa/`
- [ ] 应用 `wechat_agent/`
- [ ] 配置 / 脚本
- [ ] 文档 / 测试

## 验证方式

<!-- 贴命令与结果；真机相关请注明 Windows/管理员 PowerShell -->

```text
ruff check / format --check / mypy / pytest 结果
```

## 安全确认

- [ ] 默认仍为 `dry_run=true`，未擅自开放真实发送
- [ ] 未提交 `.env`、`data/`、`data/identity.toml`、真实聊天记录或 API Key
- [ ] 未引入图像识别消息（R3）
- [ ] 单元测试不触发真实 UI / 付费 LLM
- [ ] 若涉及真实发送，已附真机验收说明并保持开关默认关闭

## 关联 Issue

Closes #
