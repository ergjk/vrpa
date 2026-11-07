"""执行层：真实发送前三重校验（M6-01，应用层）。

三道防线（任一失败抛 ``VerifyFailed``，绝不发送）：
    1. 内容校验：非空、无 NUL、长度不超过安全上限、不含敏感词；
    2. 目标校验：窗口存在且已置前（真实发送） / 安全开关已显式授权；
    3. 发送后回读校验：会话采集文本必须包含刚发出的内容。

``dry_run`` 永远不触碰键鼠；真实发送还额外要求 ``allow_real_send=True``。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from vrpa.errors import VerifyFailed
from vrpa.ports import SendOutcome

if TYPE_CHECKING:  # pragma: no cover
    from wechat_agent.core.config import Config

__all__ = ["SendChecks", "WeChatExecutor"]


@dataclass(frozen=True)
class SendChecks:
    """三重校验结果（可审计）。"""

    content_ok: bool
    target_ok: bool
    verify_ok: bool
    issues: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.content_ok and self.target_ok and self.verify_ok and not self.issues


def _normalize_for_compare(value: str) -> str:
    """输入框复制出的换行是 \r\n，LLM 文本是 \n；比较前统一。"""
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


class WeChatExecutor:
    """发送执行器：dry_run 安全隔离 + 三重校验。"""

    def __init__(
        self,
        config: Config,
        *,
        window: Any | None = None,
        driver: Any | None = None,
        capture: Any | None = None,
        tree: Any | None = None,
        allow_real_send: bool = False,
        sleep: Any = time.sleep,
    ) -> None:
        self._config = config
        self._window = window
        self._driver = driver
        self._capture = capture
        self._tree = tree
        self._allow_real_send = allow_real_send
        self._sleep = sleep
        self.checks: SendChecks | None = None
        self.last_observed = ""

    # ------------------------------------------------------------ 查询
    def is_dry_run(self) -> bool:
        return bool(self._config.app.dry_run)

    def clear_input(self) -> str:
        return ""

    def validate(self, session: str, text: str) -> SendChecks:
        """只做静态内容校验（dry-run/控制台预检可用）。"""
        issues = self._content_issues(text)
        target_ok = self.is_dry_run() or (self._window is not None and self._driver is not None)
        if not session.strip():
            issues.append("目标会话为空")
        return SendChecks(
            content_ok=not issues,
            target_ok=target_ok,
            verify_ok=self.is_dry_run() or self._capture is not None,
            issues=tuple(issues),
        )

    # ------------------------------------------------------------ 发送
    def send(self, session: str, text: str, *, trigger: str = "auto", click_input: bool = True) -> SendOutcome:
        self.checks = self.validate(session, text)
        if self.checks.issues:
            raise VerifyFailed("内容校验失败：" + "；".join(self.checks.issues))
        if self.is_dry_run():
            return SendOutcome(ok=True, stage="dry_run", detail=f"checks=content,target,verify trigger={trigger}")
        if not self._allow_real_send:
            raise VerifyFailed(
                "真实发送被安全开关拒绝：allow_real_send=False（dry_run=false 必须显式授权并完成真机验收）"
            )
        if self._window is None or self._driver is None or self._capture is None or self._tree is None:
            raise VerifyFailed("目标校验失败：真实发送缺少 window/driver/capture/tree 依赖")
        try:
            self._window.ensure_foreground()
            try:
                input_rect = self._tree.locate("input_box_area")
            except Exception:
                input_rect = self._tree.locate("input_box")
        except Exception as exc:  # noqa: BLE001 - 统一转换为校验失败
            raise VerifyFailed(f"目标校验失败：{exc}") from exc

        def _paste_and_readback() -> bool:
            self._driver.hotkey("ctrl", "a")
            self._driver.clipboard_set(text)
            self._driver.hotkey("ctrl", "v")
            self._sleep(0.35)
            self._driver.clipboard_set("__vrpa_input_check__")
            self._driver.hotkey("ctrl", "a")
            self._driver.hotkey("ctrl", "c")
            self._sleep(0.2)
            return _normalize_for_compare(str(self._driver.clipboard_get())) == _normalize_for_compare(text)

        # 首选：不移动鼠标，直接粘贴（微信切回会话后输入框通常已聚焦）
        # 仅当直接粘贴回读失败时，才点击输入框作为第二选项。
        if click_input:
            self._driver.click(*input_rect.center)
            self._sleep(0.3)
        pasted = _paste_and_readback()
        if not pasted and not click_input:
            self._driver.click(*input_rect.center)
            self._sleep(0.3)
            pasted = _paste_and_readback()
        if not pasted:
            raise VerifyFailed("回读校验失败：输入框内容与待发文本不一致（直接粘贴与点击兜底均失败）")
        # 取消 Ctrl+A 选区：否则 Enter 会用换行替换整段选中文本（不会发送）
        self._driver.hotkey("end")
        self._driver.hotkey("enter")
        self._sleep(1.0)
        observed = str(self._capture(session))
        self.last_observed = observed
        if _normalize_for_compare(text) not in _normalize_for_compare(observed):
            raise VerifyFailed(
                f"回读校验失败：发送后在会话 {session!r} 未观察到内容"
                "（Enter 已按下，消息可能已发送；请人工确认，勿自动重试）"
            )
        return SendOutcome(ok=True, stage="sent", detail=text)

    # ------------------------------------------------------------ 内部
    def _content_issues(self, text: str) -> list[str]:
        issues: list[str] = []
        if not isinstance(text, str) or not text.strip():
            issues.append("内容为空")
            return issues
        if "\x00" in text:
            issues.append("内容含控制字符")
        limit = int(self._config.safety.max_reply_chars)
        if len(text) > limit:
            issues.append(f"内容长度 {len(text)} 超过上限 {limit}")
        sensitive = [word for word in self._config.safety.sensitive_words if word and word in text]
        if sensitive:
            issues.append(f"内容含敏感词：{', '.join(sensitive)}")
        return issues
