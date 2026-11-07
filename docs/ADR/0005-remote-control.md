# ADR 0005：控制台与远程控制边界

- 状态：已接受（V1.0 只留接口，V1.1 再实现远程）
- 日期：2026-11-07

## 背景

当前控制入口是 CLI 与 Tkinter 本地窗口。两者都运行在 RPA 机器本机。用户提出希望未来远程查看/控制，并询问“会不会被劫持”。

## 决策

1. **V1.0 不监听任何网络端口**，只提供进程内 `LocalControlTransport`；
2. 抽象 `SessionController` / `ControlTransport` / `RemoteControlPolicy` 接口，供未来 CLI、GUI、远程复用；
3. 远程控制默认**只允许状态、暂停、恢复、停止**；
4. **远程启动/远程发送默认禁止**；即使显式开启，也必须：
   - token 常量时间校验；
   - 会话在远程允许列表；
   - 发送需二次确认；
5. V1.1 如实现远程，优先 **localhost HTTP / 命名管道**；局域网必须 HTTPS/VPN；**禁止直接公网暴露**；
6. 远程端不得执行任意 shell、不得修改配置、不得读取消息原文/密钥。

## 接口

```text
SessionController:
    status()
    start_dry_run(chat)
    pause() / resume() / stop()
    send_once(chat, text, confirmed)

ControlTransport:
    request(ControlRequest) -> ControlResponse
```

`RemoteControlPolicy` 默认值：

```python
enabled = False
bind_host = "127.0.0.1"
require_tls = True
token = ""
allowed_actions = {status, pause, resume, stop}
allow_send = False
allow_remote_start = False
max_requests_per_minute = 30
```

## 会不会被劫持？

### V1.0

**不会通过远程入口被劫持**，因为根本没有网络监听。风险只剩本机同用户恶意软件——这类程序本来就能操作键鼠/读剪贴板，属于操作系统信任边界，不是本项目能单独防御的。

### V1.1 远程模式（若实现）的威胁与控制

| 威胁 | 控制 |
|---|---|
| 局域网/公网未授权访问 | 默认仅 `127.0.0.1`；远程必须显式开启 + token；局域网走 HTTPS/VPN |
| token 被窃取 | 启动随机生成、短 TTL、常量时间比较；不放 URL/日志；可轮换 |
| 恶意网页 DNS rebinding / CSRF | 校验 Host/Origin；使用自定义 Header token，不用 Cookie；CORS 白名单 |
| 中间人 | 必须 TLS；不允许裸 HTTP 跨网段 |
| 任意发送/骚扰 | 远程发送默认禁止；开启后仍有会话 allowlist + 二次确认 |
| 远程启动无人值守发送 | `allow_remote_start` 默认 false |
| 命令注入 | 只接受枚举 `ControlAction` + 结构化 JSON，不执行 shell |
| 重放 | 请求带 nonce/时间戳；短有效期；频率限制 |
| 本地其他用户 | 优先命名管道 + ACL；TCP 模式绑定 localhost |
| 拒绝服务 | 限速、请求体大小限制、超时 |

### 残余风险

- 同用户/管理员权限恶意软件仍可控制 GUI/RPA；远程安全不能高于本机 OS 安全；
- 远程“停止”依赖 RPA 机器在线且进程存活；
- 若用户把端口直接暴露公网、关闭 TLS 或复用弱 token，风险由部署方式决定。

## 实施阶段

- **V1.0（本次）**：接口、策略、测试、ADR；GUI/CLI 仍本机；
- **V1.1**：本地 Web/托盘 + 全局热键；远程只读状态与暂停/停止；
- **更后**：如确需远程发送，必须单独安全评审，默认仍关闭。
