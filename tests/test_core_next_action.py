"""统一失败提示测试。"""

from __future__ import annotations

from wechat_agent.core.next_action import explain_exit, explain_reason


def test_exit_codes_have_next_action() -> None:
    for code in (2, 3, 4, 5, 6, 7, 8, 130):
        hint = explain_exit(code)
        assert hint.next_action
        assert hint.title


def test_send_verify_is_not_safe_to_retry() -> None:
    hint = explain_exit(4)
    assert hint.safe_to_retry is False
    assert "确认" in hint.next_action


def test_reason_mapping() -> None:
    assert "管理员" in explain_reason("需要管理员 PowerShell").next_action
    assert "焦点" in explain_reason("窗口未置前").next_action or "窗口" in explain_reason("激活窗口失败").next_action
    assert explain_reason("回读校验失败").safe_to_retry is False
    assert explain_reason("dedup unanchored").safe_to_retry is False
