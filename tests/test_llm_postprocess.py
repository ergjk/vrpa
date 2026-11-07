"""M5-03 测试：后处理与安全过滤。"""

from __future__ import annotations

from vrpa.llm.postprocess import postprocess, strip_markdown


def test_strip_markdown_common_syntax() -> None:
    raw = "# 标题\n- 第一点\n- 第二点\n**加粗**与*斜体*，`行内代码`"
    text, changed = strip_markdown(raw)
    assert changed is True
    assert "标题" in text and "第一点" in text
    assert "**" not in text and "#" not in text
    assert "加粗" in text and "斜体" in text and "行内代码" in text


def test_strip_code_fence_and_link() -> None:
    raw = "```python\nprint('hi')\n```\n详见 [文档](https://example.com/doc)。"
    text, _ = strip_markdown(raw)
    assert "print('hi')" in text
    assert "文档" in text and "](https://" not in text


def test_postprocess_removes_links() -> None:
    result = postprocess("看这里 https://example.com/a 和 https://b.cn", block_links=True)
    assert result.removed_links == 2
    assert "http" not in result.text


def test_postprocess_keeps_links_when_disabled() -> None:
    result = postprocess("看这里 https://example.com/a", block_links=False)
    assert result.removed_links == 0
    assert "example.com" in result.text


def test_postprocess_masks_sensitive_words() -> None:
    result = postprocess("我的密码是abc123，别再问了", sensitive_words=("密码", "abc123"))
    assert "密码" not in result.text and "abc123" not in result.text
    assert "****" in result.text
    assert result.masked_words == ("密码", "abc123")


def test_postprocess_truncates() -> None:
    result = postprocess("这是一条很长的回复" * 20, max_chars=20)
    assert result.truncated is True
    assert len(result.text) <= 20
    assert result.text.endswith("…")


def test_postprocess_empty_is_blocked() -> None:
    result = postprocess("   ", max_chars=20)
    assert result.blocked is True
    assert result.text == ""


def test_strip_multiline_and_stray_markdown() -> None:
    raw = "**第一行\n第二行** 和一些残留 ** 与 ` 标记"
    text, changed = strip_markdown(raw)
    assert changed is True
    assert "第一行" in text and "第二行" in text
    assert "**" not in text and "`" not in text


def test_strip_horizontal_rule() -> None:
    text, _ = strip_markdown("上一段\n---\n下一段")
    assert "---" not in text
    assert "上一段" in text and "下一段" in text


def test_strip_triple_stars() -> None:
    text, _ = strip_markdown("银行***只能你自己知道")
    assert "*" not in text
    assert "银行" in text and "只能你自己知道" in text
