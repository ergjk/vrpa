"""M2-04 测试：解析器 + 15 份样例库 golden 校验。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wechat_agent.perception.parser import (
    PARSER_STRATEGIES,
    WeChatParser,
    parse_block,
    parse_sender_colon,
    parse_timestamp_prefix,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "tests" / "fixtures" / "parser_samples"
GOLDEN = json.loads((SAMPLES / "golden.json").read_text(encoding="utf-8"))


def test_golden_samples_exist() -> None:
    assert len(GOLDEN) >= 15
    for name in GOLDEN:
        assert (SAMPLES / f"{name}.txt").is_file()


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_parser_matches_golden(name: str) -> None:
    text = (SAMPLES / f"{name}.txt").read_text(encoding="utf-8")
    messages = WeChatParser().parse(text)
    actual = [
        {
            "content": message.content,
            "sender": message.sender,
            "ts": message.ts,
            "strategy": message.reason,
        }
        for message in messages
    ]
    assert actual == GOLDEN[name]


def test_strategy_names_order() -> None:
    assert WeChatParser().strategy_names == PARSER_STRATEGIES


def test_empty_or_unparsable_text() -> None:
    parser = WeChatParser()
    assert parser.parse("") == ()
    assert parser.parse("   \n\n  ") == ()
    assert parser.parse("纯文本没有前缀") == ()


def test_unknown_strategy_order_rejected() -> None:
    with pytest.raises(ValueError, match="未知解析策略"):
        WeChatParser(order=("timestamp_prefix", "nope"))


def test_timestamp_requires_timestamp() -> None:
    assert parse_timestamp_prefix("张三: 你好") == ()
    assert parse_timestamp_prefix("10:00 张三: 你好")[0].sender == "张三"


def test_sender_colon_fullwidth_and_continuation() -> None:
    messages = parse_sender_colon("张三：第一行\n第二行")
    assert len(messages) == 1
    assert messages[0].content == "第一行\n第二行"
    assert messages[0].strategy == "sender_colon"


def test_block_parser_blank_line_blocks() -> None:
    messages = parse_block("张三: 第一段\n\n李四: 第二段")
    assert len(messages) == 2
    assert [message.sender for message in messages] == ["张三", "李四"]
    assert [message.strategy for message in messages] == ["multi_line_block", "multi_line_block"]
