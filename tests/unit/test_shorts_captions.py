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


def _dialogue_times(ass: str) -> list[tuple[float, float]]:
    """Parse (start, end) in seconds for every Dialogue line, in file order."""
    times = []
    for line in ass.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        m = re.match(r"Dialogue: 0,([\d:.]+),([\d:.]+),", line)
        times.append((_parse_ass_time(m.group(1)), _parse_ass_time(m.group(2))))
    return times


def _parse_ass_time(s: str) -> float:
    hours, minutes, rest = s.split(":")
    seconds, cs = rest.split(".")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(cs) / 100


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
        assert r"\t(0,60" in ass

    def test_empty_timings_produces_header_only(self) -> None:
        ass = generate_ass([])
        assert "Dialogue:" not in ass

    def test_2_to_4_word_groups_present_in_a_longer_sentence(self) -> None:
        words = "a short burst of narration with several words in it total".split()
        timings = _fake_timings(words)
        groups = group_words(timings)
        assert all(2 <= len(g) <= 4 for g in groups)
        assert sum(len(g) for g in groups) == len(words)

    def test_pop_transform_completes_within_120ms(self) -> None:
        ass = generate_ass(_fake_timings(["hello", "world"]))
        assert r"\t(0,60" in ass
        assert r"\t(60,120" in ass
        # old 240ms two-phase transform must be gone
        assert r"\t(0,120" not in ass
        assert r"\t(120,240" not in ass


class TestGaplessEvents:
    """Regression coverage for caption blinking: per-word Dialogue events must
    be gapless (event N's End == event N+1's Start) across the whole file,
    including at group boundaries, or the burned-in captions flicker between
    words and double-blink whenever a group swaps."""

    def test_zero_gap_zero_overlap_across_whole_file(self) -> None:
        timings = _fake_timings(
            ["one", "two", "three", "four", "five", "six", "seven", "eight"]
        )
        ass = generate_ass(timings, audio_duration=timings[-1].end + 1.0)
        events = _dialogue_times(ass)
        assert len(events) == len(timings)
        for (_, end), (next_start, _) in zip(events, events[1:]):
            assert end == next_start

    def test_last_event_extends_to_audio_duration(self) -> None:
        timings = _fake_timings(["only", "two", "words"])
        ass = generate_ass(timings, audio_duration=5.0)
        events = _dialogue_times(ass)
        assert events[-1][1] == 5.0

    def test_realistic_whisper_gaps_produce_gapless_events(self) -> None:
        # Real whisper output has inter-word silence: word N ends before word
        # N+1 starts (e.g. ends 1.42, next starts 1.51) — raw start/end pairs
        # like these are exactly what used to flicker.
        timings = [
            WordTiming(word="the", start=0.10, end=0.38),
            WordTiming(word="quick", start=0.44, end=0.81),
            WordTiming(word="brown", start=0.90, end=1.20),
            WordTiming(word="fox", start=1.42, end=1.51),
            WordTiming(word="jumps", start=1.60, end=1.95),
            WordTiming(word="over", start=2.05, end=2.30),
            WordTiming(word="lazy", start=2.50, end=2.88),
            WordTiming(word="dogs", start=2.95, end=3.20),
        ]
        ass = generate_ass(timings, audio_duration=3.6)
        events = _dialogue_times(ass)
        assert len(events) == len(timings)
        for (_, end), (next_start, _) in zip(events, events[1:]):
            assert end == next_start
        assert events[-1][1] == 3.6

    def test_group_boundary_swap_is_gapless(self) -> None:
        # 8 words -> two clean groups of 4; verify the boundary explicitly:
        # last event of group 0 must end exactly when the first event of
        # group 1 starts.
        timings = _fake_timings([f"w{i}" for i in range(8)])
        groups = group_words(timings)
        assert [len(g) for g in groups] == [4, 4]
        ass = generate_ass(timings, audio_duration=timings[-1].end + 1.0)
        events = _dialogue_times(ass)
        boundary_end = events[3][1]
        next_group_start = events[4][0]
        assert boundary_end == next_group_start


class TestWriteAssFile:
    def test_writes_readable_utf8_file(self, tmp_path) -> None:
        out = tmp_path / "captions.ass"
        write_ass_file(_fake_timings(["hello", "world"]), str(out))
        content = out.read_text(encoding="utf-8")
        assert "[Script Info]" in content
        assert "Dialogue:" in content
