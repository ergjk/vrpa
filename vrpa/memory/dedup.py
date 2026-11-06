"""去重核心（M3-02，平台无关）：尾部锚点对齐。

输入是「已知尾部哈希（旧→新）」与「本次观察到的哈希（旧→新）」，
输出：新增消息起点、重复条数、是否成功锚定与置信度。

异常路径（不锚定）由调用方按 ``low_confidence_policy`` 决定：
    ignore         丢弃本次观察（默认，宁漏勿重）
    queue_confirm  入库但标记 pending_confirm（人工确认）
禁止任何「按条数硬猜」的兜底（会重复回复/漏回复）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ["Alignment", "align_tail"]


@dataclass(frozen=True)
class Alignment:
    """一次尾部对齐结果。"""

    known_count: int
    observed_count: int
    overlap: int = 0
    added_start: int = 0
    added_count: int = 0
    duplicates: int = 0
    anchored: bool = False
    confidence: float = 0.0
    reason: str = ""

    @property
    def has_new(self) -> bool:
        return self.added_count > 0


def align_tail(known: Sequence[str], observed: Sequence[str]) -> Alignment:
    """用 known 的尾部与 observed 的头部求最长重叠。"""
    known_tuple = tuple(known)
    observed_tuple = tuple(observed)
    if not observed_tuple:
        return Alignment(
            known_count=len(known_tuple),
            observed_count=0,
            reason="empty_observed",
        )
    if not known_tuple:
        return Alignment(
            known_count=0,
            observed_count=len(observed_tuple),
            added_start=0,
            added_count=len(observed_tuple),
            anchored=False,
            confidence=0.3,
            reason="no_known",
        )

    # 允许跳过库尾部少量“不在本次采集窗口内”的消息（例如 dry-run 未真实发送的 out、
    # 或界面窗口裁剪），但必须找到重叠锚点；最多跳过 20 条。
    max_skip = min(20, max(0, len(known_tuple) - 1))
    for skip in range(0, max_skip + 1):
        prefix = known_tuple[: len(known_tuple) - skip] if skip else known_tuple
        if not prefix:
            continue
        max_overlap = min(len(prefix), len(observed_tuple))
        # 1) 观察完全包含在已知尾部（整屏都是重复）
        if max_overlap == len(observed_tuple) and prefix[-len(observed_tuple) :] == observed_tuple:
            return Alignment(
                known_count=len(known_tuple),
                observed_count=len(observed_tuple),
                overlap=len(observed_tuple),
                added_start=len(observed_tuple),
                added_count=0,
                duplicates=len(observed_tuple),
                anchored=True,
                confidence=1.0 if skip == 0 else 0.9,
                reason="full_duplicate" if skip == 0 else "tail_anchor_skipped",
            )
        # 2) 尾部锚点：最长 k 使 prefix[-k:] == observed[:k]
        for overlap in range(max_overlap, 0, -1):
            if prefix[-overlap:] == observed_tuple[:overlap]:
                return Alignment(
                    known_count=len(known_tuple),
                    observed_count=len(observed_tuple),
                    overlap=overlap,
                    added_start=overlap,
                    added_count=len(observed_tuple) - overlap,
                    duplicates=overlap,
                    anchored=True,
                    confidence=(0.98 if overlap >= 2 else 0.8) if skip == 0 else 0.85,
                    reason="tail_anchor" if skip == 0 else "tail_anchor_skipped",
                )
    # 3) 无法锚定：不得猜测条数
    return Alignment(
        known_count=len(known_tuple),
        observed_count=len(observed_tuple),
        added_start=0,
        added_count=len(observed_tuple),
        anchored=False,
        confidence=0.1,
        reason="no_overlap",
    )
