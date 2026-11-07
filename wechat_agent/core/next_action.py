"""统一失败提示：把退出码/阶段转换成用户下一步动作。"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["FailureHint", "explain_exit", "explain_failure", "explain_reason"]

_EXIT_MAP: dict[int, tuple[str, str, bool]] = {
    2: ("参数/配置错误", "运行 first-run --json 或检查 config.yaml；修正后重试", True),
    3: ("元素定位失败", "运行 validate-tree --strict；必要时重新 calibrate", True),
    4: ("发送校验失败", "检查微信焦点/输入框；可能已发送，先人工确认再决定是否重试", False),
    5: ("LLM 失败", "运行 llm-ping；检查 DEEPSEEK_API_KEY 与网络", True),
    6: ("数据库失败", "停止操作，备份 data 后运行 db-check；不要继续发送", False),
    7: ("分辨率/DPI 不符", "恢复校准时的分辨率/DPI，或重新 calibrate", True),
    8: ("红线违规", "立即停止；检查日志，禁止绕过 R3", False),
    130: ("用户中断", "已停止；确认临时配置已清理后重新开始", True),
}


@dataclass(frozen=True)
class FailureHint:
    code: int | None
    title: str
    next_action: str
    safe_to_retry: bool


def explain_exit(exit_code: int) -> FailureHint:
    title, action, retry = _EXIT_MAP.get(
        int(exit_code),
        ("未知失败", "打开日志 data/logs/agent.log；运行 first-run --json 获取环境结论", False),
    )
    return FailureHint(int(exit_code), title, action, retry)


def explain_failure(exit_code: int, output: str = "") -> FailureHint:
    """优先按输出文本识别真实阶段，再退回退出码映射。"""
    for keyword in ("管理员", "激活", "前台", "剪贴板", "回读", "校验", "去重", "未锚定", "LLM", "校准", "定位"):
        if keyword.lower() in output.lower():
            hint = explain_reason(output)
            return FailureHint(int(exit_code), hint.title, hint.next_action, hint.safe_to_retry)
    return explain_exit(exit_code)


def explain_reason(reason: str) -> FailureHint:
    text = reason.lower()
    if "管理员" in reason or "admin" in text:
        return FailureHint(None, "权限不足", "用管理员 PowerShell 重新运行；dry-run 可普通权限", True)
    if "激活" in reason or "foreground" in text:
        return FailureHint(None, "微信未置前", "切到微信主窗口，确认未锁屏后重试；不要同时操作 GUI", True)
    if "剪贴板" in reason or "capture" in text:
        return FailureHint(None, "采集为空", "确认有文本消息；用 probe --debug 诊断；不要盲目重发", False)
    if "回读" in reason or "verify" in text or "校验" in reason:
        return FailureHint(None, "发送结果不确定", "先人工确认测试账号是否收到；不要自动重试", False)
    if "去重" in reason or "dedup" in text or "未锚定" in reason:
        return FailureHint(None, "去重未锚定", "停止并备份 data；运行 report / first-run，不要继续发送", False)
    if "llm" in text or "api" in text:
        return FailureHint(None, "LLM 失败", "运行 llm-ping；检查 API Key/余额/网络", True)
    if "校准" in reason or "profile" in text or "定位" in reason:
        return FailureHint(None, "视觉定位失败", "运行 validate-tree --strict；必要时重新 calibrate", True)
    return FailureHint(None, "未知失败", "打开 data/logs/agent.log；运行 first-run --json", False)
