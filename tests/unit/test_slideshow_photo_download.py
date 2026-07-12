"""Unit tests for fetch_topic_images's search/over-fetch/dedup/
partial-success orchestration. No real network calls — session and
providers are always mocks.

The resilient-download primitives this module builds on
(`build_download_session`, `download_resilient`) are now covered by
tests/unit/test_common_resilient_download.py — see that file for retry/
backoff/pacing/session-header coverage, deduped from this file's former
`TestRetryOnTransientFailures`/`TestNoRetryOnClientErrors`/
`TestSessionAndHeaders`/`TestSameHostPacing` classes (which asserted
identical behavior to test_shorts_footage_download.py's, just against
`download_photo_resilient` instead of `download_clip_resilient` — now one
shared `download_resilient`)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from docu_studio.adapters.photos.base import PhotoResult
from docu_studio.slideshow.slideshow_photo_download import fetch_topic_images


class TestFetchTopicImages:
    def test_downloads_up_to_count_and_returns_local_paths(self, tmp_path: Path) -> None:
        provider = MagicMock()
        provider.search.return_value = [
            PhotoResult(url=f"https://images.pexels.com/{i}.jpg", width=1920, height=1080, photo_id=str(i))
            for i in range(5)
        ]
        with patch(
            "docu_studio.slideshow.slideshow_photo_download.download_resilient",
            side_effect=lambda session, url, dest, last=None: dest,
        ):
            paths = fetch_topic_images("mountains", 3, [provider], tmp_path)

        assert len(paths) == 3

    def test_caps_candidate_pool_at_ceil_count_times_1_5(self, tmp_path: Path) -> None:
        provider = MagicMock()
        provider.search.return_value = [
            PhotoResult(url=f"https://images.pexels.com/{i}.jpg", width=1920, height=1080, photo_id=str(i))
            for i in range(20)
        ]
        attempted_urls: list[str] = []

        def _always_fail(session, url, dest, last=None):
            attempted_urls.append(url)
            raise requests.exceptions.ConnectionError("boom")

        with patch(
            "docu_studio.slideshow.slideshow_photo_download.download_resilient",
            side_effect=_always_fail,
        ):
            with pytest.raises(RuntimeError):
                fetch_topic_images("mountains", 4, [provider], tmp_path)

        # ceil(4 * 1.5) = 6 — the pool is capped there even though the
        # provider returned 20 candidates, so at most 6 download attempts
        assert len(attempted_urls) == 6

    def test_dedupes_by_photo_id_across_providers(self, tmp_path: Path) -> None:
        shared = PhotoResult(url="https://images.pexels.com/dup.jpg", width=1920, height=1080, photo_id="42")
        provider_a = MagicMock()
        provider_a.search.return_value = [shared]
        provider_b = MagicMock()
        provider_b.search.return_value = [
            PhotoResult(url="https://cdn.pixabay.com/dup-different-url.jpg", width=1920, height=1080, photo_id="42"),
            PhotoResult(url="https://cdn.pixabay.com/unique.jpg", width=1920, height=1080, photo_id="99"),
        ]

        with patch(
            "docu_studio.slideshow.slideshow_photo_download.download_resilient",
            side_effect=lambda session, url, dest, last=None: dest,
        ):
            # count=3 exceeds the 2 distinct photo_ids (42, 99) present across
            # all 3 raw results — if dedup were broken, the pool would contain
            # 3 raw entries and this would download 3 paths; correct dedup
            # caps the pool at 2 distinct photos, so the partial-success path
            # returns exactly 2 even though 3 were requested.
            paths = fetch_topic_images("mountains", 3, [provider_a, provider_b], tmp_path)

        assert len(paths) == 2  # only 2 distinct photo_ids exist (42, 99)

    def test_partial_success_returns_what_succeeded(self, tmp_path: Path) -> None:
        provider = MagicMock()
        provider.search.return_value = [
            PhotoResult(url=f"https://images.pexels.com/{i}.jpg", width=1920, height=1080, photo_id=str(i))
            for i in range(5)
        ]

        def _flaky_download(session, url, dest, last=None):
            if url.endswith("0.jpg"):
                raise requests.exceptions.ConnectionError("boom")
            return dest

        with patch(
            "docu_studio.slideshow.slideshow_photo_download.download_resilient",
            side_effect=_flaky_download,
        ):
            paths = fetch_topic_images("mountains", 5, [provider], tmp_path)

        assert 0 < len(paths) < 5

    def test_zero_successful_downloads_raises(self, tmp_path: Path) -> None:
        provider = MagicMock()
        provider.search.return_value = [
            PhotoResult(url="https://images.pexels.com/1.jpg", width=1920, height=1080, photo_id="1"),
        ]

        with patch(
            "docu_studio.slideshow.slideshow_photo_download.download_resilient",
            side_effect=requests.exceptions.ConnectionError("boom"),
        ):
            with pytest.raises(RuntimeError):
                fetch_topic_images("mountains", 1, [provider], tmp_path)

    def test_zero_or_negative_count_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            fetch_topic_images("mountains", 0, [MagicMock()], tmp_path)
