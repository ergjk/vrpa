"""微信推理层（M5-01~04）：Prompt 预算 + 真实 LLM 调用 + 后处理 + 人设热加载。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from vrpa.errors import LLMError
from vrpa.knowledge import KnowledgeBase
from vrpa.llm.client import LLMClient
from vrpa.llm.persona import PersonaLoader
from vrpa.llm.policy import TrimPolicyResolver
from vrpa.llm.postprocess import postprocess
from vrpa.llm.prompt import fit_prompt
from vrpa.ports import LLMResult, MemoryStore
from wechat_agent.identity import IdentityMap
from wechat_agent.knowledge.provider import build_knowledge_base

if TYPE_CHECKING:  # pragma: no cover
    from wechat_agent.core.config import Config


class WeChatBrain:
    """微信 Brain 端口实现：组装 Prompt -> LLM -> 后处理。"""

    def __init__(
        self,
        config: Config,
        *,
        client: LLMClient | None = None,
        memory: MemoryStore | None = None,
        identity: IdentityMap | None = None,
        persona: PersonaLoader | None = None,
        knowledge: KnowledgeBase | None = None,
        sessions_root: Path | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._memory = memory
        self._identity = identity
        self._persona = persona or PersonaLoader(config.llm.persona_path)
        self._knowledge = knowledge if knowledge is not None else build_knowledge_base(config)
        self._trim_policy = TrimPolicyResolver(
            config.llm.prompt_trim_policy,
            sessions_root if sessions_root is not None else config.data_dir / "sessions",
        )

    def _ensure_client(self) -> LLMClient:
        if self._client is None:
            api_key = self._config.api_key()
            if not api_key:
                raise LLMError(
                    "未配置 DEEPSEEK_API_KEY（或 llm api_key），无法调用 LLM",
                    hint="在 .env 中设置 DEEPSEEK_API_KEY 后重试",
                )
            self._client = LLMClient(
                api_key=api_key,
                base_url=self._config.llm.base_url,
                model=self._config.llm.model,
                timeout=self._config.llm.timeout,
                retries=self._config.llm.retries,
            )
        return self._client

    def generate(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        session: str | None = None,
    ) -> LLMResult:
        client = self._ensure_client()
        incoming = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                incoming = str(message.get("content", ""))
                break
        if not incoming.strip():
            raise LLMError("Prompt 缺少用户消息，拒绝调用 LLM")

        memories: list[str] = []
        history: list[tuple[str, str]] = []
        if self._memory is not None and session:
            try:
                recalled = list(self._memory.recall(session, incoming, self._config.llm.memory_top_k))
                if not recalled:
                    recalled = list(self._memory.recall(session, "", self._config.llm.memory_top_k))
                memories = [item.content for item in recalled]
                history = [
                    (record.role or "user", record.content)
                    for record in self._memory.history(session, self._config.llm.history_turns)
                ]
            except Exception:  # noqa: BLE001 - 记忆失败降级为无记忆
                memories, history = [], []

        knowledge_chunks = self._knowledge.select(session, incoming)
        persona = self._persona.load()
        note = self._identity_note(session)
        if note:
            persona = f"{persona}\n\n{note}"
        plan = fit_prompt(
            persona,
            knowledge_chunks,
            memories,
            history,
            incoming,
            max_tokens=self._config.llm.max_prompt_tokens,
            history_limit=self._config.llm.history_turns,
            memory_limit=self._config.llm.memory_top_k,
            trim_policy=self._trim_policy.resolve(session),
        )
        result = client.complete(
            list(plan.messages),
            temperature=self._config.llm.temperature,
            max_tokens=self._config.llm.max_tokens,
        )
        processed = postprocess(
            result.text,
            max_chars=self._config.safety.max_reply_chars,
            sensitive_words=self._config.safety.sensitive_words,
            block_links=self._config.safety.block_links,
        )
        if processed.blocked:
            raise LLMError("模型输出为空或被安全过滤，转人工处理", hint="检查 sensitive_words/max_reply_chars 配置")
        return LLMResult(
            text=processed.text,
            model=result.model,
            usage=result.usage,
            latency_ms=result.latency_ms,
        )

    def _identity_note(self, session: str | None) -> str:
        if self._identity is None or self._identity.is_empty():
            return ""
        self_names = "、".join(self._identity.self_nicknames)
        other_names = "、".join(self._identity.nicknames_for(session or ""))
        parts: list[str] = []
        if self_names:
            parts.append(f"你是「{self_names}」")
        if other_names:
            parts.append(f"当前对方是「{other_names}」")
        if not parts:
            return ""
        note = "；".join(parts) + "。"
        note += "你自己发出的消息在上下文里标记为 assistant；不要把你自己当成第三方，也不要使用“你俩”这种把自己排除在外的说法。"
        return note

    def ping(self) -> float:
        return self._ensure_client().ping()
