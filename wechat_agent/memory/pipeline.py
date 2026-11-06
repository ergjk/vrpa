"""微信入库闭环（M3-03/04）：去重对齐 -> 多端识别 -> 入库 -> 状态回写。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from vrpa.memory.dedup import Alignment, align_tail
from vrpa.memory.history import HistoryRecord, HistoryStore
from vrpa.memory.store import content_hash
from vrpa.ports import IncomingMessage

__all__ = ["IngestResult", "MessagePipeline"]


@dataclass(frozen=True)
class IngestResult:
    """一次采集入库结果。"""

    alignment: Alignment
    inserted: tuple[HistoryRecord, ...] = ()
    queued: tuple[HistoryRecord, ...] = ()
    self_messages: tuple[HistoryRecord, ...] = ()
    duplicates: int = 0
    reason: str = "ok"


class MessagePipeline:
    """把一次采集到的消息对齐、分类并写入流水库。"""

    def __init__(
        self,
        history: HistoryStore,
        *,
        dedup_window: int = 200,
        low_confidence_policy: str = "ignore",
    ) -> None:
        if low_confidence_policy not in {"ignore", "queue_confirm"}:
            raise ValueError(f"未知 low_confidence_policy：{low_confidence_policy}")
        self._history = history
        self._dedup_window = max(1, dedup_window)
        self._policy = low_confidence_policy

    # ------------------------------------------------------------ 入库
    def ingest(self, chat: str, incoming: Sequence[IncomingMessage]) -> IngestResult:
        self._history.ensure_chat(chat)
        observed_hashes = [content_hash(message.content) for message in incoming]
        known_hashes = self._history.tail_hashes(chat, self._dedup_window)
        alignment = align_tail(known_hashes, observed_hashes)

        if alignment.reason == "empty_observed":
            return IngestResult(alignment=alignment, reason="empty_observed")
        if known_hashes and alignment.reason == "no_overlap":
            if self._policy == "ignore":
                return IngestResult(alignment=alignment, reason="low_confidence_ignored")
            return self._insert(
                chat,
                incoming[alignment.added_start :],
                alignment,
                status="pending_confirm",
                reason="low_confidence_confirm",
                queue=False,
            )
        return self._insert(chat, incoming[alignment.added_start :], alignment)

    def _insert(
        self,
        chat: str,
        messages: Sequence[IncomingMessage],
        alignment: Alignment,
        *,
        status: str = "ok",
        reason: str = "ok",
        queue: bool = True,
    ) -> IngestResult:
        inserted: list[HistoryRecord] = []
        queued: list[HistoryRecord] = []
        self_messages: list[HistoryRecord] = []
        for item in messages:
            if not item.content.strip():
                continue
            # 多端识别：无发送者前缀 = 主人在其它设备发送，入库但不回复
            direction = "self" if item.sender is None else "in"
            message_id = self._history.append(
                chat,
                item.content,
                direction=direction,
                role="assistant" if direction == "self" else "user",
                sender=item.sender,
                ts=item.ts,
                source="rpa_capture",
                status=status,
                raw_meta={"confidence": item.confidence, "reason": item.reason},
            )
            record = self._history.get(message_id)
            if record is None:  # pragma: no cover - 理论上不可能
                continue
            inserted.append(record)
            if direction == "self":
                self_messages.append(record)
            elif queue:
                queued.append(record)
        return IngestResult(
            alignment=alignment,
            inserted=tuple(inserted),
            queued=tuple(queued),
            self_messages=tuple(self_messages),
            duplicates=alignment.duplicates,
            reason=reason,
        )

    # ------------------------------------------------------------ 状态回写
    def writeback(self, chat: str, text: str) -> int:
        """发送成功后回写（幂等：尾部哈希相同则复用最后一条 id）。"""
        self._history.ensure_chat(chat)
        text_hash = content_hash(text)
        last = self._history.last(chat)
        if last is not None and last.content_hash == text_hash and last.direction == "out":
            return last.id
        return self._history.append(
            chat,
            text,
            direction="out",
            role="assistant",
            source="self_writeback",
            status="ok",
        )
