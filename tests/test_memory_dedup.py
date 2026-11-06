"""M3-02 测试：尾部锚点去重对齐。"""

from __future__ import annotations

from vrpa.memory.dedup import align_tail


def test_empty_observed() -> None:
    result = align_tail(["a"], [])
    assert result.reason == "empty_observed"
    assert result.added_count == 0


def test_no_known_all_new() -> None:
    result = align_tail([], ["a", "b"])
    assert result.reason == "no_known"
    assert result.anchored is False
    assert result.added_start == 0 and result.added_count == 2
    assert result.confidence == 0.3


def test_full_duplicate() -> None:
    result = align_tail(["a", "b"], ["a", "b"])
    assert result.reason == "full_duplicate"
    assert result.overlap == 2 and result.added_count == 0 and result.duplicates == 2
    assert result.anchored is True and result.confidence == 1.0


def test_tail_anchor_new_messages() -> None:
    result = align_tail(["a", "b"], ["a", "b", "c", "d"])
    assert result.reason == "tail_anchor"
    assert result.overlap == 2 and result.added_start == 2 and result.added_count == 2
    assert result.anchored is True and result.confidence == 0.98


def test_single_overlap_lower_confidence() -> None:
    result = align_tail(["a", "b"], ["b", "c"])
    assert result.reason == "tail_anchor"
    assert result.overlap == 1 and result.added_count == 1
    assert result.confidence == 0.8


def test_no_overlap_not_anchored() -> None:
    result = align_tail(["a", "b"], ["c", "d"])
    assert result.reason == "no_overlap"
    assert result.anchored is False and result.added_count == 2
    assert result.confidence == 0.1


def test_observed_fully_inside_known() -> None:
    result = align_tail(["a", "b", "c"], ["b", "c"])
    assert result.reason == "full_duplicate"
    assert result.overlap == 2 and result.added_count == 0


def test_known_fully_in_observed_prefix() -> None:
    result = align_tail(["a", "b"], ["a", "b", "c"])
    assert result.reason == "tail_anchor"
    assert result.overlap == 2 and result.added_count == 1
