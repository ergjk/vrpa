"""moments 示例插件（M6-04）：朋友圈定时草稿，仅产出计划、绝不直接发送。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from vrpa.plugins import PluginContext, PluginMeta

__all__ = ["MomentDraft", "MomentsPlugin"]


@dataclass(frozen=True)
class MomentDraft:
    content: str
    visibility: str
    scheduled_for: str
    chat: str = ""


class MomentsPlugin:
    """到点生成朋友圈草稿（dry_run 下只记录，不执行真实操作）。"""

    meta = PluginMeta(name="moments", version="0.1", description="朋友圈定时草稿（示例插件）")

    def __init__(
        self,
        *,
        schedule: tuple[str, ...] = ("09:00",),
        visibility: str = "private",
        generator: Callable[[date], str] | None = None,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._schedule = tuple(schedule)
        self._visibility = visibility
        self._generator = generator or (lambda day: f"今日分享 {day.isoformat()}")
        self._clock = clock
        self.drafts: list[MomentDraft] = []
        self._posted_days: set[date] = set()

    def _now(self) -> datetime:
        return self._clock()

    def on_start(self, context: PluginContext) -> None:
        return None

    def on_stop(self, context: PluginContext) -> None:
        return None

    def on_message(self, context: PluginContext, chat: str, content: str) -> None:
        return None

    def on_tick(self, context: PluginContext, tick: int) -> None:
        now = self._now()
        current = f"{now.hour:02d}:{now.minute:02d}"
        today = now.date()
        if current not in self._schedule or today in self._posted_days:
            return
        self._posted_days.add(today)
        self.drafts.append(
            MomentDraft(
                content=self._generator(today),
                visibility=self._visibility,
                scheduled_for=now.isoformat(timespec="minutes"),
                chat="",
            )
        )

    def drain(self) -> tuple[MomentDraft, ...]:
        drafts = tuple(self.drafts)
        self.drafts.clear()
        return drafts
