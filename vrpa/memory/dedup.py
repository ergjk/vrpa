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

    max_overlap = min(len(known_tuple), len(observed_tuple))
    # 1) 观察完全包含在已知尾部（整屏都是重复）
    if max_overlap == len(observed_tuple) and known_tuple[-len(observed_tuple) :] == observed_tuple:
        return Alignment(
            known_count=len(known_tuple),
            observed_count=len(observed_tuple),
            overlap=len(observed_tuple),
            added_start=len(observed_tuple),
            added_count=0,
            duplicates=len(observed_tuple),
            anchored=True,
            confidence=1.0,
            reason="full_duplicate",
        )
    # 2) 尾部锚点：最长 k 使 known[-k:] == observed[:k]
    for overlap in range(max_overlap, 0, -1):
        if known_tuple[-overlap:] == observed_tuple[:overlap]:
            return Alignment(
                known_count=len(known_tuple),
                observed_count=len(observed_tuple),
                overlap=overlap,
                added_start=overlap,
                added_count=len(observed_tuple) - overlap,
                duplicates=overlap,
                anchored=True,
                confidence=0.98 if overlap >= 2 else 0.8,
                reason="tail_anchor",
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
