"""Unit tests for shorts_captions: ASS subtitle generation for burned-in pop captions."""
from __future__ import annotations

import re

from docu_studio.shorts.capability_resolvers import WordTiming
from docu_studio.shorts.shorts_captions import (
    SAFE_AREA_BOTTOM_MARGIN,
    generate_ass,
    group_words,
    write_ass_file,
)
from docu_studio.shorts.shorts_config import SHORTS_HEIGHT


def _fake_timings(words: list[str], word_duration: float = 0.4) -> list[WordTiming]:
    timings = []
    cursor = 0.0
    for w in words:
        timings.append(WordTiming(word=w, start=cursor, end=cursor + word_duration))
        cursor += word_duration
    return timings


class TestGroupWords:
    def test_empty_returns_empty(self) -> None:
        assert group_words([]) == []

    def test_all_groups_within_bounds_for_various_lengths(self) -> None:
        for n in (2, 3, 4, 5, 6, 7, 9, 11, 13, 20):
            timings = _fake_timings([f"w{i}" for i in range(n)])
            groups = group_words(timings)
            assert sum(len(g) for g in groups) == n
            for g in groups:
                assert 2 <= len(g) <= 4

    def test_single_word_script_returns_single_group(self) -> None:
        groups = group_words(_fake_timings(["solo"]))
        assert len(groups) == 1
        assert len(groups[0]) == 1
        assert groups[0][0].word == "solo"

    def test_thirteen_words_borrows_to_avoid_trailing_singleton(self) -> None:
        groups = group_words(_fake_timings([f"w{i}" for i in range(13)]))
        assert [len(g) for g in groups] == [4, 4, 3, 2]


class TestGenerateAss:
    def test_contains_required_sections(self) -> None:
        ass = generate_ass(_fake_timings(["the", "quick", "brown", "fox", "jumps"]))
        assert "[Script Info]" in ass
        assert "[V4+ Styles]" in ass
        assert "[Events]" in ass
        assert "Style: Pop," in ass

    def test_dialogue_lines_are_word_level(self) -> None:
        timings = _fake_timings(["the", "quick", "brown", "fox", "jumps"])
        ass = generate_ass(timings)
        dialogue_lines = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
        assert len(dialogue_lines) == len(timings)

    def test_times_are_monotonically_non_decreasing(self) -> None:
        timings = _fake_timings(["one", "two", "three", "four", "five", "six", "seven"])
        ass = generate_ass(timings)
        starts = []
        for line in ass.splitlines():
            if line.startswith("Dialogue:"):
                m = re.match(r"Dialogue: 0,([\d:.]+),", line)
                starts.append(m.group(1))
        assert starts == sorted(starts)

    def test_safe_area_margin_clears_bottom_15_percent(self) -> None:
        assert SAFE_AREA_BOTTOM_MARGIN >= round(SHORTS_HEIGHT * 0.15)

    def test_margin_v_is_embedded_in_style_line(self) -> None:
        ass = generate_ass(_fake_timings(["hi", "there"]))
        style_line = next(l for l in ass.splitlines() if l.startswith("Style: Pop,"))
        fields = style_line.split(",")
        assert int(fields[-2]) == SAFE_AREA_BOTTOM_MARGIN

    def test_active_word_gets_pop_transform(self) -> None:
        ass = generate_ass(_fake_timings(["hello", "world"]))
        assert r"\t(0,120" in ass

    def test_empty_timings_produces_header_only(self) -> None:
        ass = generate_ass([])
        assert "Dialogue:" not in ass

    def test_2_to_4_word_groups_present_in_a_longer_sentence(self) -> None:
        words = "a short burst of narration with several words in it total".split()
        timings = _fake_timings(words)
        groups = group_words(timings)
        assert all(2 <= len(g) <= 4 for g in groups)
        assert sum(len(g) for g in groups) == len(words)


class TestWriteAssFile:
    def test_writes_readable_utf8_file(self, tmp_path) -> None:
        out = tmp_path / "captions.ass"
        write_ass_file(_fake_timings(["hello", "world"]), str(out))
        content = out.read_text(encoding="utf-8")
        assert "[Script Info]" in content
        assert "Dialogue:" in content
