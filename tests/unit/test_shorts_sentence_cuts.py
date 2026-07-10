"""Unit tests for plan_sentence_scoped_cuts — the sentence-scoped cut
planner: per-sentence footage pools stay separate, micro-cuts respect their
own sentence's span bounds exactly, and no cut sequence steals across a
sentence boundary."""
from __future__ import annotations

import pytest

from docu_studio.shorts.shorts_cuts import MIN_SEGMENT_DURATION, Segment
from docu_studio.shorts.shorts_sentence_cuts import (
    apply_loop_revisit,
    insert_punch_card_scoped,
    plan_sentence_scoped_cuts,
)


class TestPlanSentenceScopedCuts:
    def test_short_span_gets_a_single_segment_spanning_the_whole_sentence(self) -> None:
        spans = [(0.0, 3.0)]
        segments = plan_sentence_scoped_cuts(spans, pool_sizes=[2], pool_sources=["sentence"], seed=1)
        assert len(segments) == 1
        assert segments[0].start == pytest.approx(0.0)
        assert segments[0].duration == pytest.approx(3.0)
        assert segments[0].sentence_index == 0
        assert segments[0].pool_source == "sentence"

    def test_long_span_is_split_into_multiple_micro_cuts(self) -> None:
        spans = [(0.0, 10.0)]
        segments = plan_sentence_scoped_cuts(spans, pool_sizes=[4], pool_sources=["sentence"], seed=1)
        assert len(segments) >= 2
        for seg in segments:
            assert seg.sentence_index == 0
            assert seg.start >= 0.0 - 1e-9
            assert seg.start + seg.duration <= 10.0 + 1e-9

    def test_micro_cuts_stay_entirely_inside_their_own_sentences_span(self) -> None:
        spans = [(0.0, 5.0), (5.0, 16.0), (16.0, 19.0)]
        segments = plan_sentence_scoped_cuts(
            spans, pool_sizes=[2, 3, 1], pool_sources=["sentence"] * 3, seed=7,
        )
        for seg in segments:
            span_start, span_end = spans[seg.sentence_index]
            assert seg.start >= span_start - 1e-9
            assert seg.start + seg.duration <= span_end + 1e-9

    def test_two_adjacent_short_sentences_never_steal_across_their_shared_boundary(self) -> None:
        spans = [(0.0, 2.1), (2.1, 4.0)]
        segments = plan_sentence_scoped_cuts(
            spans, pool_sizes=[1, 1], pool_sources=["sentence", "sentence"], seed=2,
        )
        assert len(segments) == 2
        assert segments[0].duration == pytest.approx(2.1)
        assert segments[1].duration == pytest.approx(1.9)

    def test_min_segment_duration_floor_holds_on_both_sides_of_a_sentence_boundary(self) -> None:
        spans = [(0.0, 9.0), (9.0, 20.0)]
        segments = plan_sentence_scoped_cuts(
            spans, pool_sizes=[3, 4], pool_sources=["sentence", "sentence"], seed=11,
        )
        sentence_a_segments = [s for s in segments if s.sentence_index == 0]
        sentence_b_segments = [s for s in segments if s.sentence_index == 1]
        last_of_a = sentence_a_segments[-1]
        first_of_b = sentence_b_segments[0]
        assert first_of_b.duration >= MIN_SEGMENT_DURATION - 1e-9 or len(sentence_b_segments) == 1
        assert last_of_a.start + last_of_a.duration == pytest.approx(9.0, abs=0.02)
        assert first_of_b.start == pytest.approx(9.0, abs=0.02)

    def test_clip_index_only_ever_refers_to_its_own_sentences_pool_size(self) -> None:
        spans = [(0.0, 12.0), (12.0, 14.0)]
        segments = plan_sentence_scoped_cuts(
            spans, pool_sizes=[3, 1], pool_sources=["sentence", "fallback"], seed=5,
        )
        for seg in segments:
            expected_n = [3, 1][seg.sentence_index]
            assert 0 <= seg.clip_index < expected_n

    def test_pool_source_is_stamped_per_sentence(self) -> None:
        spans = [(0.0, 3.0), (3.0, 6.0)]
        segments = plan_sentence_scoped_cuts(
            spans, pool_sizes=[1, 1], pool_sources=["sentence", "fallback"], seed=1,
        )
        by_sentence = {s.sentence_index: s.pool_source for s in segments}
        assert by_sentence[0] == "sentence"
        assert by_sentence[1] == "fallback"

    def test_segments_are_globally_reindexed_in_order(self) -> None:
        spans = [(0.0, 3.0), (3.0, 6.0), (6.0, 9.0)]
        segments = plan_sentence_scoped_cuts(
            spans, pool_sizes=[1, 1, 1], pool_sources=["sentence"] * 3, seed=1,
        )
        assert [s.index for s in segments] == list(range(len(segments)))

    def test_reproducible_by_seed(self) -> None:
        spans = [(0.0, 12.0), (12.0, 20.0)]
        a = plan_sentence_scoped_cuts(spans, pool_sizes=[3, 2], pool_sources=["sentence"] * 2, seed=9)
        b = plan_sentence_scoped_cuts(spans, pool_sizes=[3, 2], pool_sources=["sentence"] * 2, seed=9)
        assert a == b

    def test_rejects_zero_pool_size(self) -> None:
        with pytest.raises(ValueError):
            plan_sentence_scoped_cuts([(0.0, 3.0)], pool_sizes=[0], pool_sources=["sentence"], seed=1)

    def test_rejects_mismatched_list_lengths(self) -> None:
        with pytest.raises(ValueError):
            plan_sentence_scoped_cuts(
                [(0.0, 3.0), (3.0, 6.0)], pool_sizes=[1], pool_sources=["sentence"], seed=1,
            )


class TestApplyLoopRevisit:
    def test_reserves_final_segment_sourced_from_sentence_zero(self) -> None:
        segments = [
            Segment(index=0, start=0.0, duration=20.0, clip_index=0, sentence_index=0, pool_source="sentence"),
        ]
        result = apply_loop_revisit(segments, total_duration=20.0, sentence_zero_pool_source="sentence")
        last = result[-1]
        assert last.loop_revisit is True
        assert last.sentence_index == 0
        assert last.clip_index == 0
        assert last.pool_source == "sentence"

    def test_revisit_duration_matches_the_reserved_band(self) -> None:
        segments = [
            Segment(index=0, start=0.0, duration=20.0, clip_index=0, sentence_index=0, pool_source="sentence"),
        ]
        result = apply_loop_revisit(segments, total_duration=20.0, sentence_zero_pool_source="sentence")
        assert result[-1].duration == pytest.approx(1.75)

    def test_total_duration_preserved(self) -> None:
        segments = [
            Segment(index=0, start=0.0, duration=20.0, clip_index=0, sentence_index=0, pool_source="sentence"),
        ]
        result = apply_loop_revisit(segments, total_duration=20.0, sentence_zero_pool_source="sentence")
        assert sum(s.duration for s in result) == pytest.approx(20.0, abs=0.02)

    def test_skipped_when_last_segment_too_short_to_carve_the_floor(self) -> None:
        # Synthetic segments: last segment is 3.0s; carving 1.75s would leave
        # 1.25s < MIN_SEGMENT_DURATION (2.0s) — must skip, not shrink below it.
        segments = [
            Segment(index=0, start=0.0, duration=5.0, clip_index=0, sentence_index=0, pool_source="sentence"),
            Segment(index=1, start=5.0, duration=3.0, clip_index=0, sentence_index=1, pool_source="sentence"),
        ]
        result = apply_loop_revisit(segments, total_duration=8.0, sentence_zero_pool_source="sentence")
        assert result == segments
        assert all(not s.loop_revisit for s in result)

    def test_skipped_when_total_duration_too_short(self) -> None:
        spans = [(0.0, 5.0)]
        segments = plan_sentence_scoped_cuts(spans, pool_sizes=[1], pool_sources=["sentence"], seed=1)
        result = apply_loop_revisit(segments, total_duration=5.0, sentence_zero_pool_source="sentence")
        assert result == segments

    def test_skipped_when_last_segment_too_short_even_when_it_belongs_to_sentence_zero(self) -> None:
        # Regression test: the last (and only) segment belongs to sentence 0.
        # Carving 1.75s from its 3.0s duration would leave 1.25s <
        # MIN_SEGMENT_DURATION (2.0s) — must skip regardless of sentence_index.
        segments = [
            Segment(index=0, start=0.0, duration=3.0, clip_index=0, sentence_index=0, pool_source="sentence"),
        ]
        result = apply_loop_revisit(segments, total_duration=8.0, sentence_zero_pool_source="sentence")
        assert result == segments
        assert all(not s.loop_revisit for s in result)


class TestInsertPunchCardScoped:
    def test_never_steals_from_a_neighboring_sentences_segment(self) -> None:
        spans = [(0.0, 3.0), (3.0, 6.0)]
        segments = [
            Segment(index=0, start=0.0, duration=3.0, clip_index=0, sentence_index=0, pool_source="sentence"),
            Segment(index=1, start=3.0, duration=3.0, clip_index=0, sentence_index=1, pool_source="sentence"),
        ]
        new_segments, window = insert_punch_card_scoped(segments, punch=(0, "90 PERCENT"), spans=spans)
        assert window is not None
        card = next(s for s in new_segments if s.is_punch)
        assert card.start >= spans[0][0] - 1e-9
        assert card.start + card.duration <= spans[0][1] + 1e-9
        sentence1_seg = next(s for s in new_segments if s.sentence_index == 1 and not s.is_punch)
        assert sentence1_seg.start == pytest.approx(3.0)
        assert sentence1_seg.duration == pytest.approx(3.0)

    def test_flicker_scenario_short_first_sentence_with_tight_neighbor_is_skipped_cleanly(self) -> None:
        # The exact production bug: a punch card tied to sentence 0, whose
        # own span is short (2.5s, single segment), immediately followed by
        # sentence 1's own tight segment. Old behavior stole down to a 0.3s
        # sliver right next to sentence 1's cut, causing flicker. New
        # behavior must skip the card entirely rather than produce that
        # sliver, since 2.5 - PUNCH_CARD_DURATION_SECONDS(1.0) = 1.5s <
        # the 2.0s minimum-duration floor.
        spans = [(0.0, 2.5), (2.5, 5.0)]
        segments = [
            Segment(index=0, start=0.0, duration=2.5, clip_index=0, sentence_index=0, pool_source="sentence"),
            Segment(index=1, start=2.5, duration=2.5, clip_index=0, sentence_index=1, pool_source="sentence"),
        ]
        new_segments, window = insert_punch_card_scoped(segments, punch=(0, "90 PERCENT"), spans=spans)
        assert window is None
        assert new_segments == segments

    def test_long_first_sentence_fits_the_card_with_a_clean_remainder(self) -> None:
        # sentence 0 long enough (4.5s single segment) to fit the card
        # (1.0s) and still leave >= MIN_SEGMENT_DURATION(2.0s) remainder
        # (3.5s) produces a clean single card segment, not a sliver.
        spans = [(0.0, 4.5), (4.5, 7.0)]
        segments = [
            Segment(index=0, start=0.0, duration=4.5, clip_index=0, sentence_index=0, pool_source="sentence"),
            Segment(index=1, start=4.5, duration=2.5, clip_index=0, sentence_index=1, pool_source="sentence"),
        ]
        new_segments, window = insert_punch_card_scoped(segments, punch=(0, "90 PERCENT"), spans=spans)
        assert window is not None
        card = next(s for s in new_segments if s.is_punch)
        assert card.duration == pytest.approx(1.0)
        remainder = next(s for s in new_segments if s.sentence_index == 0 and not s.is_punch)
        assert remainder.duration >= MIN_SEGMENT_DURATION - 1e-9

    def test_skips_gracefully_when_sentence_has_no_segments(self) -> None:
        spans = [(0.0, 0.0), (0.0, 5.0)]
        segments = [
            Segment(index=0, start=0.0, duration=5.0, clip_index=0, sentence_index=1, pool_source="sentence"),
        ]
        new_segments, window = insert_punch_card_scoped(segments, punch=(0, "90 PERCENT"), spans=spans)
        assert window is None
        assert new_segments == segments

    def test_sentence_index_out_of_range_returns_unchanged(self) -> None:
        spans = [(0.0, 3.0)]
        segments = [Segment(index=0, start=0.0, duration=3.0, clip_index=0, sentence_index=0, pool_source="sentence")]
        new_segments, window = insert_punch_card_scoped(segments, punch=(5, "90 PERCENT"), spans=spans)
        assert window is None
        assert new_segments == segments

    def test_loop_revisit_segment_is_never_chosen_as_the_target(self) -> None:
        spans = [(0.0, 3.0)]
        segments = [
            Segment(index=0, start=0.0, duration=3.0, clip_index=0, sentence_index=0,
                    pool_source="sentence", loop_revisit=True),
        ]
        new_segments, window = insert_punch_card_scoped(segments, punch=(0, "90 PERCENT"), spans=spans)
        assert window is None
        assert new_segments == segments
