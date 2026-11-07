"""后处理与安全过滤（M5-03，平台无关）：去 Markdown / 链接过滤 / 敏感词打码 / 截断。"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["ProcessedReply", "postprocess", "strip_markdown"]

_CODE_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\s*\n?(.*?)```", re.S)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_BULLET = re.compile(r"^\s{0,3}[-*+]\s+", re.M)
_QUOTE = re.compile(r"^\s{0,3}>\s?", re.M)
_BOLD = re.compile(r"(\*\*|__)(.+?)\1", re.S)
_STRAY_MARKDOWN = re.compile(r"\*+|__|`")
_HR = re.compile(r"^\s*([-*_])\1{2,}\s*$", re.M)
_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"!?\[([^\]]*)\]\(([^)]*)\)")
_URL = re.compile(r"https?://[^\s，。；;）)]+")
_WHITESPACE = re.compile(r"[ \t]+")


@dataclass(frozen=True)
class ProcessedReply:
    """后处理结果。"""

    text: str
    blocked: bool = False
    truncated: bool = False
    removed_links: int = 0
    masked_words: tuple[str, ...] = ()
    markdown_removed: bool = False


def strip_markdown(text: str) -> tuple[str, bool]:
    """去掉常见 Markdown 痕迹，返回 (清理后文本, 是否发生改写)。"""
    original = text
    text = _CODE_FENCE.sub(lambda match: match.group(1).strip(), text)
    text = _INLINE_CODE.sub(lambda match: match.group(1), text)
    text = _LINK.sub(lambda match: match.group(1) if match.group(1) else "", text)
    text = _BOLD.sub(lambda match: match.group(2), text)
    text = _ITALIC.sub(lambda match: match.group(1), text)
    text = _HEADING.sub("", text)
    text = _BULLET.sub("", text)
    text = _QUOTE.sub("", text)
    text = _HR.sub("", text)
    text = _STRAY_MARKDOWN.sub("", text)
    text = "\n".join(_WHITESPACE.sub(" ", line).strip() for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, text != original


def postprocess(
    raw: str,
    *,
    max_chars: int = 300,
    sensitive_words: tuple[str, ...] = (),
    block_links: bool = True,
) -> ProcessedReply:
    """去 Markdown -> 去链接 -> 敏感词打码 -> 截断。"""
    text, markdown_removed = strip_markdown(raw or "")
    removed_links = 0
    if block_links:
        text, removed_links = _URL.subn("", text)
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip()).strip()

    masked: list[str] = []
    for word in sensitive_words:
        if word and word in text:
            text = text.replace(word, "*" * len(word))
            masked.append(word)

    truncated = False
    limit = max(1, int(max_chars))
    if len(text) > limit:
        text = text[: max(1, limit - 1)].rstrip() + "…"
        truncated = True

    blocked = not text.strip()
    return ProcessedReply(
        text=text,
        blocked=blocked,
        truncated=truncated,
        removed_links=removed_links,
        masked_words=tuple(masked),
        markdown_removed=markdown_removed,
    )
