# 贡献指南（Contributing）

## 开发环境

- Windows 10/11、Python 3.14；
- 安装依赖：`pip install -r requirements.txt`；
- 质量门禁：`scripts/quality.bat`（ruff + mypy strict + pytest + coverage）。

## 提交前必须通过

```powershell
.\venv\Scripts\python.exe -m ruff check .
.\venv\Scripts\python.exe -m ruff format --check .
.\venv\Scripts\python.exe -m mypy
.\venv\Scripts\python.exe -m pytest tests -q --cov --cov-report=term
```

覆盖率门禁 ≥85%。

## 安全红线

- 消息内容只允许通过“鼠标框选 + `Ctrl+C`”采集，禁止图像识别消息；
- 单元测试不得触发真实鼠标/键盘、真实微信或付费 LLM；
- 不得提交 `.env`、`data/`、`data/identity.toml`、真实聊天记录或 API Key；
- 真实发送相关改动必须保持默认关闭，并附真机验收说明。

## Issue / PR

- Bug 请用 Issue 模板，附环境、命令、脱敏输出、`capture_info` / dump；
- PR 请保持单一主题，说明改动、验证方式、安全影响；
- 提交信息使用 `feat:` / `fix:` / `docs:` / `test:` / `chore:` 前缀。

## 版本与路线

- V1.0：微信 4.x 真机 dry-run 与验收；
- V1.1：表情/语音/撤回/插件生态；
- V1.2：学习型操作策略（鼠标路径、输入节奏、人设相关）与行为克隆。
