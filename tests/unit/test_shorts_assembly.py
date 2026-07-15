"""Unit tests for shorts_assembly's pure-ish helper functions: _build_segment
(speed ramp + loop-revisit alternate window), _search_dedup/_collect_clips
(footage fetch dedupe + download capping). ShortsFFmpeg and FootageProvider
are always MagicMocks/fakes — no real ffmpeg calls or network.

Note: the plan's brief for this test file also references _insert_punch_card
(time-stealing math) — that helper is added in a later task and its import
will be added back to this file when it lands."""
from __future__ import annotations

import queue
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.adapters.footage.base import FootageClip
from docu_studio.shorts.shorts_assembly import (
    SPEED_RAMP_FACTOR,
    _build_segment,
    _collect_clips,
    _collect_clips_per_sentence,
    _insert_punch_card,
    _search_dedup,
)
from docu_studio.shorts.shorts_cuts import Segment
from docu_studio.shorts.shorts_script_gen import ShortsScript

_CLIP = {"path": "/clips/a.mp4", "width": 1920, "height": 1080}


def _script(n_sentences: int) -> ShortsScript:
    sentences = [f"Sentence number {i} of the short." for i in range(n_sentences)]
    queries = [f"query {i}" for i in range(n_sentences)]
    return ShortsScript(text=" ".join(sentences), sentences=sentences, visual_queries=queries)


def _ffmpeg(raw_duration: float, motion_start: float, method: str = "fallback") -> MagicMock:
    ffmpeg = MagicMock()
    ffmpeg.get_duration.return_value = raw_duration
    ffmpeg.detect_motion_window.return_value = (motion_start, method)
    return ffmpeg


class TestBuildSegmentSpeedRamp:
    def test_slow_fallback_long_clip_gets_sped_up_when_enabled(self, tmp_path: Path) -> None:
        seg = Segment(index=0, start=0.0, duration=3.0, clip_index=0)
        ffmpeg = _ffmpeg(raw_duration=20.0, motion_start=0.0, method="fallback")

        path, sped_count, _ = _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=True, sped_count=0, max_sped_segments=5,
        )

        assert sped_count == 1
        ffmpeg.apply_speed_ramp.assert_called_once()

    def test_fast_motion_clip_not_sped_up(self, tmp_path: Path) -> None:
        seg = Segment(index=0, start=0.0, duration=3.0, clip_index=0)
        ffmpeg = _ffmpeg(raw_duration=20.0, motion_start=2.0, method="motion")

        _, sped_count, _ = _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=True, sped_count=0, max_sped_segments=5,
        )

        assert sped_count == 0
        ffmpeg.apply_speed_ramp.assert_not_called()

    def test_short_source_clip_not_sped_up_even_if_fallback(self, tmp_path: Path) -> None:
        seg = Segment(index=0, start=0.0, duration=3.0, clip_index=0)
        ffmpeg = _ffmpeg(raw_duration=10.0, motion_start=0.0, method="fallback")  # <15s

        _, sped_count, _ = _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=True, sped_count=0, max_sped_segments=5,
        )

        assert sped_count == 0
        ffmpeg.apply_speed_ramp.assert_not_called()

    def test_disabled_flag_never_speeds_up(self, tmp_path: Path) -> None:
        seg = Segment(index=0, start=0.0, duration=3.0, clip_index=0)
        ffmpeg = _ffmpeg(raw_duration=20.0, motion_start=0.0, method="fallback")

        _, sped_count, _ = _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=False, sped_count=0, max_sped_segments=5,
        )

        assert sped_count == 0
        ffmpeg.apply_speed_ramp.assert_not_called()

    def test_source_window_is_cut_longer_by_the_speed_factor(self, tmp_path: Path) -> None:
        seg = Segment(index=0, start=0.0, duration=3.0, clip_index=0)
        ffmpeg = _ffmpeg(raw_duration=30.0, motion_start=0.0, method="fallback")

        _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=True, sped_count=0, max_sped_segments=5,
        )

        trim_call = ffmpeg.trim_clip.call_args
        trimmed_duration = trim_call[0][2]
        assert trimmed_duration == pytest.approx(3.0 * SPEED_RAMP_FACTOR, abs=0.01)

    def test_ken_burns_duration_matches_plan_duration_when_sped(self, tmp_path: Path) -> None:
        seg = Segment(index=0, start=0.0, duration=3.0, clip_index=0)
        ffmpeg = _ffmpeg(raw_duration=30.0, motion_start=0.0, method="fallback")

        _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=True, sped_count=0, max_sped_segments=5,
        )

        kb_call = ffmpeg.apply_ken_burns.call_args
        assert kb_call[0][2] == pytest.approx(3.0)  # duration arg == seg.duration exactly

    def test_cap_is_enforced_via_sped_count_and_max_param(self, tmp_path: Path) -> None:
        seg = Segment(index=0, start=0.0, duration=3.0, clip_index=0)
        ffmpeg = _ffmpeg(raw_duration=30.0, motion_start=0.0, method="fallback")

        _, sped_count, _ = _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=True, sped_count=2, max_sped_segments=2,  # already at cap
        )

        assert sped_count == 2
        ffmpeg.apply_speed_ramp.assert_not_called()

    def test_speed_factor_is_within_spec_band(self) -> None:
        assert 1.25 <= SPEED_RAMP_FACTOR <= 1.5


class TestBuildSegmentLoopRevisit:
    def test_loop_revisit_segment_never_sped_even_if_candidate(self, tmp_path: Path) -> None:
        seg = Segment(index=5, start=28.0, duration=1.75, clip_index=0, loop_revisit=True)
        ffmpeg = _ffmpeg(raw_duration=30.0, motion_start=0.0, method="fallback")

        _, sped_count, _ = _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=True, sped_count=0, max_sped_segments=5,
        )

        assert sped_count == 0
        ffmpeg.apply_speed_ramp.assert_not_called()

    def test_picks_alternate_window_when_source_long_enough(self, tmp_path: Path) -> None:
        seg = Segment(index=5, start=28.0, duration=1.75, clip_index=0, loop_revisit=True)
        # motion detection would pick start=0.0 again, same as the (avoided) original
        ffmpeg = _ffmpeg(raw_duration=30.0, motion_start=0.0, method="motion")

        _, _, window_start = _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=False, sped_count=0, max_sped_segments=5,
            avoid_start=0.0,
        )

        assert window_start != 0.0
        assert window_start == pytest.approx(30.0 - 1.75)

    def test_falls_back_to_same_window_when_source_too_short(self, tmp_path: Path) -> None:
        seg = Segment(index=5, start=8.0, duration=1.75, clip_index=0, loop_revisit=True)
        # raw_duration - window = 2.0 - 1.75 = 0.25s < _LOOP_REVISIT_MIN_GAP -> no room to differ
        ffmpeg = _ffmpeg(raw_duration=2.0, motion_start=0.1, method="motion")

        _, _, window_start = _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=False, sped_count=0, max_sped_segments=5,
            avoid_start=0.1,
        )

        assert window_start == 0.1

    def test_no_avoid_start_leaves_window_untouched(self, tmp_path: Path) -> None:
        seg = Segment(index=0, start=0.0, duration=3.0, clip_index=0)
        ffmpeg = _ffmpeg(raw_duration=30.0, motion_start=5.0, method="motion")

        _, _, window_start = _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=False, sped_count=0, max_sped_segments=5,
        )

        assert window_start == 5.0


def _plain_segments(*durations: float) -> list[Segment]:
    segs = []
    start = 0.0
    for i, d in enumerate(durations):
        segs.append(Segment(index=i, start=start, duration=d, clip_index=i))
        start += d
    return segs


class TestInsertPunchCard:
    def test_shrinks_adjacent_segment_and_preserves_total_duration(self) -> None:
        segments = _plain_segments(3.0, 3.0, 3.0)
        total_before = sum(s.duration for s in segments)

        new_segments, window = _insert_punch_card(
            segments, punch=(1, "90 PERCENT"), sentence_starts=[0.0, 3.0, 6.0],
        )

        assert window is not None
        assert sum(s.duration for s in new_segments) == pytest.approx(total_before)

    def test_card_segment_is_flagged_and_carries_text(self) -> None:
        segments = _plain_segments(3.0, 3.0, 3.0)
        new_segments, window = _insert_punch_card(
            segments, punch=(1, "90 PERCENT"), sentence_starts=[0.0, 3.0, 6.0],
        )
        punch_segs = [s for s in new_segments if s.is_punch]
        assert len(punch_segs) == 1
        assert punch_segs[0].punch_text == "90 PERCENT"
        assert punch_segs[0].duration == pytest.approx(window[1] - window[0])

    def test_card_placed_before_target_when_not_the_first_segment(self) -> None:
        segments = _plain_segments(3.0, 3.0, 3.0)
        new_segments, window = _insert_punch_card(
            segments, punch=(1, "90 PERCENT"), sentence_starts=[0.0, 3.0, 6.0],
        )
        card_index = next(i for i, s in enumerate(new_segments) if s.is_punch)
        # the shrunk original target must immediately follow the card
        assert not new_segments[card_index + 1].is_punch
        assert new_segments[card_index + 1].start == pytest.approx(window[1])

    def test_card_steals_from_the_end_when_target_is_first_segment(self) -> None:
        segments = _plain_segments(3.0, 3.0, 3.0)
        new_segments, window = _insert_punch_card(
            segments, punch=(0, "90 PERCENT"), sentence_starts=[0.0, 3.0, 6.0],
        )
        assert window is not None
        assert window[0] > 0.0  # card doesn't start at t=0
        first = new_segments[0]
        assert not first.is_punch
        assert first.start == 0.0

    def test_returns_unchanged_when_no_footage_segments(self) -> None:
        segments = [Segment(index=0, start=28.0, duration=1.75, clip_index=0, loop_revisit=True)]
        new_segments, window = _insert_punch_card(
            segments, punch=(0, "90 PERCENT"), sentence_starts=[0.0],
        )
        assert window is None
        assert new_segments == segments

    def test_skips_gracefully_when_target_segment_too_short_to_steal_from(self) -> None:
        segments = _plain_segments(0.4, 3.0)  # first segment too short for a 1.0s card
        new_segments, window = _insert_punch_card(
            segments, punch=(0, "90 PERCENT"), sentence_starts=[0.0, 0.4],
        )
        assert window is None
        assert new_segments == segments

    def test_sentence_index_out_of_range_returns_unchanged(self) -> None:
        segments = _plain_segments(3.0, 3.0)
        new_segments, window = _insert_punch_card(
            segments, punch=(5, "90 PERCENT"), sentence_starts=[0.0, 3.0],
        )
        assert window is None
        assert new_segments == segments

    def test_loop_revisit_segment_is_never_chosen_as_the_target(self) -> None:
        segments = [
            Segment(index=0, start=0.0, duration=3.0, clip_index=0),
            Segment(index=1, start=3.0, duration=1.75, clip_index=0, loop_revisit=True),
        ]
        # sentence start lands exactly on the revisit segment's start
        new_segments, window = _insert_punch_card(
            segments, punch=(0, "90 PERCENT"), sentence_starts=[3.0],
        )
        assert window is not None
        assert window[1] <= 3.0  # card placed within the non-revisit segment only


class TestSearchDedupClipId:
    def test_dedupes_by_clip_id_even_when_url_differs(self) -> None:
        # Real-run regression: a provider can return a different signed/
        # tokenized download URL for the same underlying clip across two
        # separate search calls — url-based dedup alone would miss this.
        clip_a = FootageClip(
            url="https://cdn/a-token1.mp4", duration=20.0, width=1920, height=1080,
            clip_id="123",
        )
        clip_b = FootageClip(
            url="https://cdn/a-token2.mp4", duration=20.0, width=1920, height=1080,
            clip_id="123",
        )
        provider = MagicMock()
        provider.search.side_effect = [[clip_a], [clip_b]]

        result = _search_dedup([provider], ["query one", "query two"], min_duration=10.0)

        assert len(result) == 1
        assert result[0][0] == "https://cdn/a-token1.mp4"  # first-seen kept

    def test_falls_back_to_url_when_clip_id_missing(self) -> None:
        clip = FootageClip(url="https://cdn/x.mp4", duration=20.0, width=1920, height=1080)
        same_url_clip = FootageClip(url="https://cdn/x.mp4", duration=20.0, width=1920, height=1080)
        provider = MagicMock()
        provider.search.side_effect = [[clip], [same_url_clip]]

        result = _search_dedup([provider], ["q1", "q2"], min_duration=10.0)

        assert len(result) == 1

    def test_distinct_clip_ids_are_not_deduped(self) -> None:
        clip_a = FootageClip(url="https://cdn/a.mp4", duration=20.0, width=1920, height=1080, clip_id="1")
        clip_b = FootageClip(url="https://cdn/b.mp4", duration=20.0, width=1920, height=1080, clip_id="2")
        provider = MagicMock()
        provider.search.side_effect = [[clip_a], [clip_b]]

        result = _search_dedup([provider], ["q1", "q2"], min_duration=10.0)

        assert len(result) == 2


class TestSearchDedupCandidateCap:
    def test_caps_candidates_kept_per_query(self) -> None:
        # Real-run regression: each provider.search() call can return up to
        # 20 results (per_page=20) for a single query — taking all of them
        # unconditionally is what caused a real run to download 29 clips
        # against a target of 6-12.
        clips = [
            FootageClip(url=f"https://cdn/{i}.mp4", duration=20.0, width=1920, height=1080, clip_id=str(i))
            for i in range(20)
        ]
        provider = MagicMock()
        provider.search.return_value = clips

        result = _search_dedup([provider], ["one query"], min_duration=10.0, max_per_query=2)

        assert len(result) == 2

    def test_default_cap_is_small(self) -> None:
        clips = [
            FootageClip(url=f"https://cdn/{i}.mp4", duration=20.0, width=1920, height=1080, clip_id=str(i))
            for i in range(20)
        ]
        provider = MagicMock()
        provider.search.return_value = clips

        result = _search_dedup([provider], ["one query"], min_duration=10.0)

        assert len(result) <= 2


class TestCollectClipsDownloadCap:
    @staticmethod
    def _provider_returning(n_per_query: int) -> MagicMock:
        provider = MagicMock()

        def fake_search(keywords, min_duration, page=1):
            q = keywords[0]
            return [
                FootageClip(
                    url=f"https://cdn/{q}-{i}.mp4", duration=30.0, width=1920, height=1080,
                    clip_id=f"{q}-{i}",
                )
                for i in range(n_per_query)
            ]

        provider.search.side_effect = fake_search
        return provider

    def test_download_count_capped_to_max_pool_multiplier(self, tmp_path: Path) -> None:
        # 10 sentences -> n_needed = max(6, 10) = 10 -> max_pool = ceil(10*1.5) = 15.
        # The per-query cap (2) x 10 unique-clip_id queries produces 20 raw
        # candidates, which must be truncated to 15 before any download happens.
        provider = self._provider_returning(20)
        script = _script(10)
        event_queue: queue.Queue = queue.Queue()

        with patch(
            "docu_studio.shorts.shorts_assembly.download_clip",
            side_effect=lambda url, dest: Path(dest).write_bytes(b"x"),
        ):
            downloaded = _collect_clips(script, [provider], tmp_path, event_queue)

        assert len(downloaded) == 15

    def test_download_count_not_capped_below_n_needed(self, tmp_path: Path) -> None:
        # 4 sentences -> n_needed = max(6, 4) = 6. The per-query cap alone
        # (2 x 4 = 8 unique candidates) already clears that floor, so the
        # topic-level padding fetch should never fire and downloads should
        # land near n_needed, not below it.
        provider = self._provider_returning(20)
        script = _script(4)
        event_queue: queue.Queue = queue.Queue()

        with patch(
            "docu_studio.shorts.shorts_assembly.download_clip",
            side_effect=lambda url, dest: Path(dest).write_bytes(b"x"),
        ):
            downloaded = _collect_clips(script, [provider], tmp_path, event_queue)

        assert 6 <= len(downloaded) <= 9  # max_pool = ceil(6 * 1.5) = 9

    def test_logs_over_fetch_cap_version_marker_unconditionally(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Real-run regression: a run well after the over-fetch-cap fix landed
        # on disk still downloaded 42 clips against a target of 6, because a
        # long-running app process keeps whatever module code was imported at
        # startup — editing the .py file has no effect until the process
        # restarts. This marker line lets any run's log prove the cap is
        # actually active instead of having to infer it from the download
        # count and message-format archaeology again.
        provider = self._provider_returning(2)
        script = _script(4)
        event_queue: queue.Queue = queue.Queue()

        with patch(
            "docu_studio.shorts.shorts_assembly.download_clip",
            side_effect=lambda url, dest: Path(dest).write_bytes(b"x"),
        ):
            with caplog.at_level("INFO"):
                _collect_clips(script, [provider], tmp_path, event_queue)

        messages = [r.message for r in caplog.records]
        assert any("over-fetch cap active" in m for m in messages)


class TestCollectClipsPerSentence:
    def test_each_sentences_pool_only_contains_clips_from_its_own_query(self, tmp_path: Path) -> None:
        def fake_search(keywords, min_duration, page=1):
            q = keywords[0]
            return [FootageClip(url=f"https://cdn/{q}.mp4", duration=30.0, width=1920, height=1080, clip_id=q)]

        provider = MagicMock()
        provider.search.side_effect = fake_search
        script = _script(3)  # queries: "query 0", "query 1", "query 2"
        event_queue: queue.Queue = queue.Queue()

        with patch(
            "docu_studio.shorts.shorts_assembly.download_resilient",
            side_effect=lambda session, url, dest, last_request_at=None: Path(dest).write_bytes(b"x"),
        ):
            pools, _fallback = _collect_clips_per_sentence(script, [provider], tmp_path, event_queue)

        assert len(pools) == 3
        for pool in pools:
            assert len(pool) == 1
        paths = [pool[0]["path"] for pool in pools]
        assert len(set(paths)) == 3  # each sentence's clip is a distinct download

    def test_identical_clip_across_two_sentence_queries_is_not_downloaded_twice(self, tmp_path: Path) -> None:
        shared_clip = FootageClip(
            url="https://cdn/shared.mp4", duration=30.0, width=1920, height=1080, clip_id="shared",
        )
        provider = MagicMock()
        provider.search.side_effect = lambda keywords, min_duration, page=1: [shared_clip]
        script = _script(2)
        event_queue: queue.Queue = queue.Queue()
        download_calls: list[str] = []

        with patch(
            "docu_studio.shorts.shorts_assembly.download_resilient",
            side_effect=lambda session, url, dest, last_request_at=None: (
                download_calls.append(url), Path(dest).write_bytes(b"x"),
            ),
        ):
            pools, _fallback = _collect_clips_per_sentence(script, [provider], tmp_path, event_queue)

        assert len(download_calls) == 1  # downloaded once even though both queries hit it
        assert len(pools[0]) == 1  # only the FIRST sentence to see it keeps it
        assert len(pools[1]) == 0

    def test_sentence_with_failed_provider_gets_empty_pool_not_a_borrowed_one(self, tmp_path: Path) -> None:
        def fake_search(keywords, min_duration, page=1):
            q = keywords[0]
            if q == "query 1":
                raise RuntimeError("provider down")
            return [FootageClip(url=f"https://cdn/{q}.mp4", duration=30.0, width=1920, height=1080, clip_id=q)]

        provider = MagicMock()
        provider.search.side_effect = fake_search
        script = _script(3)
        event_queue: queue.Queue = queue.Queue()

        with patch(
            "docu_studio.shorts.shorts_assembly.download_resilient",
            side_effect=lambda session, url, dest, last_request_at=None: Path(dest).write_bytes(b"x"),
        ):
            pools, _fallback = _collect_clips_per_sentence(script, [provider], tmp_path, event_queue)

        assert pools[1] == []
        assert len(pools[0]) == 1
        assert len(pools[2]) == 1

    def test_fallback_pool_is_built_from_the_first_sentences_query(self, tmp_path: Path) -> None:
        def fake_search(keywords, min_duration, page=1):
            q = keywords[0]
            return [FootageClip(url=f"https://cdn/{q}.mp4", duration=30.0, width=1920, height=1080, clip_id=q)]

        provider = MagicMock()
        provider.search.side_effect = fake_search
        script = _script(2)
        event_queue: queue.Queue = queue.Queue()

        with patch(
            "docu_studio.shorts.shorts_assembly.download_resilient",
            side_effect=lambda session, url, dest, last_request_at=None: Path(dest).write_bytes(b"x"),
        ):
            _pools, fallback = _collect_clips_per_sentence(script, [provider], tmp_path, event_queue)

        assert len(fallback) == 1

    def test_all_downloads_in_a_batch_share_one_session_and_pacing_dict(self, tmp_path: Path) -> None:
        def fake_search(keywords, min_duration, page=1):
            q = keywords[0]
            return [FootageClip(url=f"https://cdn/{q}.mp4", duration=30.0, width=1920, height=1080, clip_id=q)]

        provider = MagicMock()
        provider.search.side_effect = fake_search
        script = _script(3)
        event_queue: queue.Queue = queue.Queue()
        seen_sessions = []
        seen_pacing_dicts = []

        def fake_download(session, url, dest, last_request_at=None):
            seen_sessions.append(session)
            seen_pacing_dicts.append(id(last_request_at))
            Path(dest).write_bytes(b"x")

        with patch(
            "docu_studio.shorts.shorts_assembly.download_resilient",
            side_effect=fake_download,
        ):
            _collect_clips_per_sentence(script, [provider], tmp_path, event_queue)

        assert len(seen_sessions) == 3
        assert len(set(id(s) for s in seen_sessions)) == 1  # one shared Session for the whole batch
        assert len(set(seen_pacing_dicts)) == 1  # one shared pacing dict for the whole batch


class TestBuildSegmentOutputDimensions:
    def test_default_dimensions_pass_through_to_vertical_convert_and_ken_burns(
        self, tmp_path: Path
    ) -> None:
        seg = Segment(index=0, start=0.0, duration=3.0, clip_index=0)
        ffmpeg = _ffmpeg(raw_duration=20.0, motion_start=2.0, method="motion")

        _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=False, sped_count=0, max_sped_segments=5,
        )

        vc_call = ffmpeg.vertical_convert.call_args
        assert vc_call[0][3:] == (1080, 1920)
        kb_call = ffmpeg.apply_ken_burns.call_args
        assert kb_call[0][5:] == (1080, 1920)

    def test_custom_dimensions_pass_through_to_vertical_convert_and_ken_burns(
        self, tmp_path: Path
    ) -> None:
        seg = Segment(index=0, start=0.0, duration=3.0, clip_index=0)
        ffmpeg = _ffmpeg(raw_duration=20.0, motion_start=2.0, method="motion")

        _build_segment(
            seg, _CLIP, ffmpeg, tmp_path,
            speed_ramp_enabled=False, sped_count=0, max_sped_segments=5,
            output_dimensions=(1920, 1080),
        )

        vc_call = ffmpeg.vertical_convert.call_args
        assert vc_call[0][3:] == (1920, 1080)
        kb_call = ffmpeg.apply_ken_burns.call_args
        assert kb_call[0][5:] == (1920, 1080)
