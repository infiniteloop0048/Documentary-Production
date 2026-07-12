"""Unit tests for slideshow_captions — pure text generation, no ffmpeg/I/O
beyond tmp_path for write_ass_file."""
from __future__ import annotations

from pathlib import Path

from docu_studio.slideshow.slideshow_captions import (
    WordTiming,
    estimate_word_timestamps,
    generate_ass,
    group_words,
    write_ass_file,
)


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
    def test_groups_of_four_by_default(self) -> None:
        timings = [WordTiming(word=str(i), start=float(i), end=float(i + 1)) for i in range(8)]
        groups = group_words(timings)
        assert [len(g) for g in groups] == [4, 4]

    def test_single_leftover_borrows_from_previous_group(self) -> None:
        timings = [WordTiming(word=str(i), start=float(i), end=float(i + 1)) for i in range(13)]
        groups = group_words(timings)
        assert [len(g) for g in groups] == [4, 4, 3, 2]

    def test_single_word_returns_one_group_below_floor(self) -> None:
        timings = [WordTiming(word="hi", start=0.0, end=1.0)]
        assert group_words(timings) == [[timings[0]]]

    def test_empty_input_returns_empty_list(self) -> None:
        assert group_words([]) == []


class TestGenerateAss:
    def test_header_uses_caller_dimensions(self) -> None:
        timings = estimate_word_timestamps("hello there", 2.0)
        doc = generate_ass(timings, out_width=1920, out_height=1080)
        assert "PlayResX: 1920" in doc
        assert "PlayResY: 1080" in doc

    def test_margin_v_is_22_percent_of_height(self) -> None:
        timings = estimate_word_timestamps("hello there", 2.0)
        doc = generate_ass(timings, out_width=1080, out_height=1920)
        # Style line's MarginV is the second-to-last field before Encoding.
        style_line = next(l for l in doc.splitlines() if l.startswith("Style:"))
        margin_v = style_line.split(",")[-2]
        assert margin_v == str(round(1920 * 0.22))

    def test_events_are_gapless(self) -> None:
        timings = estimate_word_timestamps("one two three four five", 5.0)
        doc = generate_ass(timings, out_width=1080, out_height=1920, audio_duration=5.0)
        dialogue_lines = [l for l in doc.splitlines() if l.startswith("Dialogue:")]
        assert len(dialogue_lines) == 5

    def test_empty_timings_produces_header_only(self) -> None:
        doc = generate_ass([], out_width=1080, out_height=1920)
        assert "Dialogue:" not in doc


class TestWriteAssFile:
    def test_writes_utf8_file(self, tmp_path: Path) -> None:
        timings = estimate_word_timestamps("hi there", 2.0)
        out = tmp_path / "captions.ass"
        write_ass_file(timings, str(out), 1080, 1920)
        assert out.exists()
        assert "Dialogue:" in out.read_text(encoding="utf-8")
