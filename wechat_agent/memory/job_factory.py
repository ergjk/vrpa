"""把 LLM 记忆筛选器接入 M3 异步提炼 job。"""

from __future__ import annotations

from typing import Any

from vrpa.memory.jobs import MemoryExtractJob, TaskQueue
from vrpa.memory.long_term import LongTermMemory
from vrpa.ports import MemoryStore
from wechat_agent.memory.selector import LLMMemorySelector, selector_from_config

__all__ = ["build_memory_extract_job"]


def build_memory_extract_job(
    config: Any,
    databases: Any,
    memory_store: MemoryStore,
    *,
    selector: LLMMemorySelector | None = None,
) -> MemoryExtractJob | None:
    """无 API Key 时返回 None（调用方跳过提炼，不影响主链路）。"""
    if selector is None:
        if not config.api_key():
            return None
        selector = selector_from_config(config)
    return MemoryExtractJob(
        TaskQueue(databases),
        LongTermMemory(memory_store),
        extractor=selector,
    )
