"""Unit tests for common/captions.py — ASS subtitle generation for burned-in
"pop" captions, shared by the Shorts and Slideshow pipelines.

Union of the test classes formerly duplicated across test_shorts_captions.py
and test_slideshow_captions.py (deduped where both asserted the same
behavior — e.g. slideshow's gapless/empty-timings/margin-embedding checks
were subsumed by shorts' more thorough equivalents once both now share one
generate_ass). Shorts-flavored tests pass SHORTS_WIDTH/SHORTS_HEIGHT
(1080x1920, matching Shorts' former hardcoded dimensions); Slideshow-flavored
tests pass explicit non-default dimensions (e.g. 1920x1080) to exercise the
width/height parameterization.

TestPunchWindowWithNonDefaultDimensions is new: it exercises punch_window
together with a non-default out_width/out_height, a combination neither
source file covered (Shorts never varied dimensions, Slideshow never had
punch_window) — the one genuinely new scenario this merge creates.
"""
from __future__ import annotations

import re

from docu_studio.common.captions import (
    WordTiming,
    estimate_word_timestamps,
    generate_ass,
    group_words,
    write_ass_file,
)
from docu_studio.shorts.shorts_config import SHORTS_HEIGHT, SHORTS_WIDTH
from docu_studio.shorts.shorts_cuts import Segment
from docu_studio.shorts.shorts_sentence_cuts import insert_punch_card_scoped


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


class TestEstimateWordTimestamps:
    def test_distributes_words_across_duration(self) -> None:
        timings = estimate_word_timestamps("one two three", 9.0)
        assert len(timings) == 3
        assert timings[0].start == 0.0
        assert timings[-1].end == 9.0

    def test_weights_by_character_length(self) -> None:
        timings = estimate_word_timestamps("a bb", 3.0)
        span_a = timings[0].end - timings[0].start
        span_bb = timings[1].end - timings[1].start
        assert span_bb == 2 * span_a

    def test_empty_script_returns_empty_list(self) -> None:
        assert estimate_word_timestamps("", 5.0) == []

    def test_zero_duration_returns_empty_list(self) -> None:
        assert estimate_word_timestamps("hello", 0.0) == []


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

    def test_groups_of_four_by_default(self) -> None:
        timings = _fake_timings([f"w{i}" for i in range(8)])
        groups = group_words(timings)
        assert [len(g) for g in groups] == [4, 4]

    def test_single_word_script_returns_single_group(self) -> None:
        groups = group_words(_fake_timings(["solo"]))
        assert len(groups) == 1
        assert len(groups[0]) == 1
        assert groups[0][0].word == "solo"

    def test_thirteen_words_borrows_to_avoid_trailing_singleton(self) -> None:
        groups = group_words(_fake_timings([f"w{i}" for i in range(13)]))
        assert [len(g) for g in groups] == [4, 4, 3, 2]

    def test_2_to_4_word_groups_present_in_a_longer_sentence(self) -> None:
        words = "a short burst of narration with several words in it total".split()
        timings = _fake_timings(words)
        groups = group_words(timings)
        assert all(2 <= len(g) <= 4 for g in groups)
        assert sum(len(g) for g in groups) == len(words)


class TestGenerateAss:
    def test_contains_required_sections(self) -> None:
        ass = generate_ass(
            _fake_timings(["the", "quick", "brown", "fox", "jumps"]),
            SHORTS_WIDTH, SHORTS_HEIGHT,
        )
        assert "[Script Info]" in ass
        assert "[V4+ Styles]" in ass
        assert "[Events]" in ass
        assert "Style: Pop," in ass

    def test_header_uses_caller_dimensions(self) -> None:
        timings = estimate_word_timestamps("hello there", 2.0)
        doc = generate_ass(timings, out_width=1920, out_height=1080)
        assert "PlayResX: 1920" in doc
        assert "PlayResY: 1080" in doc

    def test_dialogue_lines_are_word_level(self) -> None:
        timings = _fake_timings(["the", "quick", "brown", "fox", "jumps"])
        ass = generate_ass(timings, SHORTS_WIDTH, SHORTS_HEIGHT)
        dialogue_lines = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
        assert len(dialogue_lines) == len(timings)

    def test_times_are_monotonically_non_decreasing(self) -> None:
        timings = _fake_timings(["one", "two", "three", "four", "five", "six", "seven"])
        ass = generate_ass(timings, SHORTS_WIDTH, SHORTS_HEIGHT)
        starts = []
        for line in ass.splitlines():
            if line.startswith("Dialogue:"):
                m = re.match(r"Dialogue: 0,([\d:.]+),", line)
                starts.append(m.group(1))
        assert starts == sorted(starts)

    def test_margin_v_is_22_percent_of_height(self) -> None:
        timings = estimate_word_timestamps("hello there", 2.0)
        doc = generate_ass(timings, out_width=1080, out_height=1920)
        # Style line's MarginV is the second-to-last field before Encoding.
        style_line = next(l for l in doc.splitlines() if l.startswith("Style:"))
        margin_v = style_line.split(",")[-2]
        assert margin_v == str(round(1920 * 0.22))
        # also clears the literal bottom-15%-UI floor the margin exists for
        assert int(margin_v) >= round(1920 * 0.15)

    def test_active_word_gets_pop_transform(self) -> None:
        ass = generate_ass(_fake_timings(["hello", "world"]), SHORTS_WIDTH, SHORTS_HEIGHT)
        assert r"\t(0,60" in ass

    def test_empty_timings_produces_header_only(self) -> None:
        ass = generate_ass([], SHORTS_WIDTH, SHORTS_HEIGHT)
        assert "Dialogue:" not in ass

    def test_pop_transform_completes_within_120ms(self) -> None:
        ass = generate_ass(_fake_timings(["hello", "world"]), SHORTS_WIDTH, SHORTS_HEIGHT)
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
        ass = generate_ass(
            timings, SHORTS_WIDTH, SHORTS_HEIGHT, audio_duration=timings[-1].end + 1.0,
        )
        events = _dialogue_times(ass)
        assert len(events) == len(timings)
        for (_, end), (next_start, _) in zip(events, events[1:]):
            assert end == next_start

    def test_last_event_extends_to_audio_duration(self) -> None:
        timings = _fake_timings(["only", "two", "words"])
        ass = generate_ass(timings, SHORTS_WIDTH, SHORTS_HEIGHT, audio_duration=5.0)
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
        ass = generate_ass(timings, SHORTS_WIDTH, SHORTS_HEIGHT, audio_duration=3.6)
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
        ass = generate_ass(
            timings, SHORTS_WIDTH, SHORTS_HEIGHT, audio_duration=timings[-1].end + 1.0,
        )
        events = _dialogue_times(ass)
        boundary_end = events[3][1]
        next_group_start = events[4][0]
        assert boundary_end == next_group_start


class TestWriteAssFile:
    def test_writes_readable_utf8_file(self, tmp_path) -> None:
        out = tmp_path / "captions.ass"
        write_ass_file(_fake_timings(["hello", "world"]), str(out), SHORTS_WIDTH, SHORTS_HEIGHT)
        content = out.read_text(encoding="utf-8")
        assert "[Script Info]" in content
        assert "Dialogue:" in content

    def test_writes_utf8_file_with_slideshow_dimensions(self, tmp_path) -> None:
        timings = estimate_word_timestamps("hi there", 2.0)
        out = tmp_path / "captions.ass"
        write_ass_file(timings, str(out), 1080, 1920)
        assert out.exists()
        assert "Dialogue:" in out.read_text(encoding="utf-8")


class TestPunchWindowTrimming:
    def test_event_fully_inside_card_window_is_dropped(self) -> None:
        timings = _fake_timings(["one", "two", "three", "four"], word_duration=0.5)
        # words at [0,0.5), [0.5,1.0), [1.0,1.5), [1.5,2.0) roughly (gapless End=next Start)
        ass = generate_ass(
            timings, SHORTS_WIDTH, SHORTS_HEIGHT,
            audio_duration=2.5, punch_window=(0.4, 1.6),
        )
        dialogue_lines = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
        # "two" ([0.5,1.0)) and "three" ([1.0,1.5)) fall fully inside (0.4,1.6) -> dropped
        assert len(dialogue_lines) < len(timings)

    def test_event_outside_card_window_is_unaffected(self) -> None:
        timings = _fake_timings(["one", "two", "three"], word_duration=0.5)
        ass_without = generate_ass(timings, SHORTS_WIDTH, SHORTS_HEIGHT, audio_duration=2.0)
        ass_with = generate_ass(
            timings, SHORTS_WIDTH, SHORTS_HEIGHT, audio_duration=2.0, punch_window=(5.0, 6.0),
        )
        assert ass_without == ass_with

    def test_event_overlapping_start_edge_is_clamped(self) -> None:
        timings = [
            WordTiming(word="alpha", start=0.0, end=0.9),
            WordTiming(word="beta", start=1.0, end=1.9),
        ]
        # card starts mid-way through "alpha"'s [0.0, 1.0) span (gapless End = next Start = 1.0)
        ass = generate_ass(
            timings, SHORTS_WIDTH, SHORTS_HEIGHT, audio_duration=2.0, punch_window=(0.5, 1.5),
        )
        events = _dialogue_times(ass)
        # "alpha"'s event must end at or before the card start
        assert events[0][1] <= 0.5

    def test_event_overlapping_end_edge_is_clamped_or_dropped(self) -> None:
        timings = [
            WordTiming(word="alpha", start=0.0, end=0.9),
            WordTiming(word="beta", start=1.0, end=1.9),
        ]
        ass = generate_ass(
            timings, SHORTS_WIDTH, SHORTS_HEIGHT, audio_duration=2.0, punch_window=(0.5, 1.5),
        )
        events = _dialogue_times(ass)
        # "beta" starts inside the card window (1.0 in [0.5,1.5)) -> either dropped
        # or its Start clamped to >= 1.5
        remaining_starts = [s for s, _ in events]
        assert all(s >= 1.5 or s <= 0.5 for s in remaining_starts)

    def test_no_punch_window_matches_original_output(self) -> None:
        timings = _fake_timings(["one", "two", "three"])
        assert generate_ass(
            timings, SHORTS_WIDTH, SHORTS_HEIGHT, audio_duration=2.0,
        ) == generate_ass(
            timings, SHORTS_WIDTH, SHORTS_HEIGHT, audio_duration=2.0, punch_window=None,
        )

    def test_gapless_invariant_preserved_between_kept_events_outside_window(self) -> None:
        timings = _fake_timings(
            ["one", "two", "three", "four", "five", "six", "seven", "eight"], word_duration=0.3,
        )
        # card window sits entirely after all these words -> nothing should change
        ass = generate_ass(
            timings, SHORTS_WIDTH, SHORTS_HEIGHT,
            audio_duration=timings[-1].end + 1.0, punch_window=(50.0, 51.0),
        )
        events = _dialogue_times(ass)
        for (_, end), (next_start, _) in zip(events, events[1:]):
            assert end == next_start

    def test_event_straddling_both_edges_is_split_not_truncated(self) -> None:
        # Only two words -> group_words produces a single [alpha, beta] group,
        # so "alpha"'s gapless span runs [0.3, 1.7) (End pinned to "beta"'s
        # Start). The punch window (0.5, 1.5) is a sub-interval of that span
        # entirely -> "alpha" must be split into a before-card occurrence
        # [0.3, 0.5) and an after-card occurrence [1.5, 1.7), not truncated
        # to just the first piece. "beta" itself starts at 1.7, fully outside
        # the window, and is untouched.
        timings = [
            WordTiming(word="alpha", start=0.3, end=0.3),  # end unused; gapless End = next Start
            WordTiming(word="beta", start=1.7, end=1.7),
        ]
        ass = generate_ass(
            timings, SHORTS_WIDTH, SHORTS_HEIGHT, audio_duration=2.0, punch_window=(0.5, 1.5),
        )
        events = _dialogue_times(ass)
        assert len(events) == 3
        assert events[0] == (0.3, 0.5)
        assert events[1] == (1.5, 1.7)
        assert events[2] == (1.7, 2.0)

        dialogue_lines = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
        # both the pre-card and post-card pieces render "alpha" as the active
        # (bolded/scaled) word -- same text, split across two time ranges.
        assert dialogue_lines[0].split(",", 9)[-1] == dialogue_lines[1].split(",", 9)[-1]
        assert "alpha" in dialogue_lines[0]
        assert "beta" in dialogue_lines[2]


class TestPunchWindowWithNonDefaultDimensions:
    """The one combination neither source test file covered: Shorts never
    varies out_width/out_height (always 1080x1920) and Slideshow never uses
    punch_window — this is the new scenario the merge into one
    width/height-parameterized generate_ass creates."""

    def test_punch_window_trimming_and_dimensions_both_apply(self) -> None:
        timings = _fake_timings(["one", "two", "three", "four"], word_duration=0.5)
        ass = generate_ass(
            timings, out_width=1920, out_height=1080,
            audio_duration=2.5, punch_window=(0.4, 1.6),
        )
        # dimensions land in the header exactly as requested, independent of
        # the punch_window branch being exercised
        assert "PlayResX: 1920" in ass
        assert "PlayResY: 1080" in ass
        style_line = next(l for l in ass.splitlines() if l.startswith("Style:"))
        margin_v = style_line.split(",")[-2]
        assert margin_v == str(round(1080 * 0.22))
        # "two" ([0.5,1.0)) and "three" ([1.0,1.5)) fall fully inside
        # (0.4, 1.6) -> dropped, same behavior as the 1080x1920 Shorts case
        dialogue_lines = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
        assert len(dialogue_lines) < len(timings)

    def test_split_event_at_non_default_dimensions(self) -> None:
        # Same straddling-split scenario as TestPunchWindowTrimming's
        # equivalent, but at 16:9 dimensions, to prove the split/clamp/drop
        # logic doesn't implicitly depend on Shorts' 9:16 aspect ratio.
        timings = [
            WordTiming(word="alpha", start=0.3, end=0.3),
            WordTiming(word="beta", start=1.7, end=1.7),
        ]
        ass = generate_ass(
            timings, out_width=1920, out_height=1080,
            audio_duration=2.0, punch_window=(0.5, 1.5),
        )
        events = _dialogue_times(ass)
        assert len(events) == 3
        assert events[0] == (0.3, 0.5)
        assert events[1] == (1.5, 1.7)
        assert events[2] == (1.7, 2.0)


class TestGaplessOnSentenceScopedPlan:
    def test_gapless_across_a_sentence_scoped_punch_window(self) -> None:
        # Build a small sentence-scoped plan (2 sentences), derive a
        # punch_window from it exactly as assemble_short does, and confirm
        # generate_ass's gapless invariant still holds end-to-end — segment
        # boundaries here are sentence-derived, not duration-derived, but
        # generate_ass only cares about (timings, punch_window), so this
        # proves the contract between the new planner and the existing
        # captions pipeline.
        timings = [
            WordTiming(word="Ninety", start=0.0, end=0.4),
            WordTiming(word="percent", start=0.4, end=0.9),
            WordTiming(word="of", start=0.9, end=1.0),
            WordTiming(word="oceans", start=1.0, end=1.5),
            WordTiming(word="unexplored.", start=1.5, end=2.0),
            WordTiming(word="That", start=2.3, end=2.6),
            WordTiming(word="changes", start=2.6, end=3.1),
            WordTiming(word="today.", start=3.1, end=3.6),
        ]
        spans = [(0.0, 2.0), (2.0, 6.0)]
        segments = [
            Segment(index=0, start=0.0, duration=2.0, clip_index=0, sentence_index=0, pool_source="sentence"),
            Segment(index=1, start=2.0, duration=4.0, clip_index=0, sentence_index=1, pool_source="sentence"),
        ]
        _new_segments, window = insert_punch_card_scoped(segments, punch=(1, "TODAY"), spans=spans)
        assert window == (5.0, 6.0)

        ass = generate_ass(timings, SHORTS_WIDTH, SHORTS_HEIGHT, audio_duration=6.0, punch_window=window)
        events = _dialogue_times(ass)
        assert len(events) == len(timings)
        for (_, end), (next_start, _) in zip(events, events[1:]):
            assert end == next_start
