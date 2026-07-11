"""Unit tests for the slideshow-only resilient photo downloader (mirrors
tests/unit/test_shorts_footage_download.py's structure) plus the
fetch_topic_images over-fetch/dedup/partial-success orchestration. No real
network calls — session and providers are always mocks."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from docu_studio.adapters.photos.base import PhotoResult
from docu_studio.slideshow.slideshow_photo_download import (
    BROWSER_USER_AGENT,
    build_download_session,
    download_photo_resilient,
    fetch_topic_images,
)


def _ok_response(body: bytes = b"photo-bytes") -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.iter_content.return_value = [body]
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def _http_error_response(status_code: int) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    error = requests.exceptions.HTTPError(f"{status_code} error")
    error.response = response
    response.raise_for_status.side_effect = error
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


class TestRetryOnTransientFailures:
    def test_retries_on_connection_error_and_succeeds_on_later_attempt(self, tmp_path: Path) -> None:
        session = MagicMock()
        session.get.side_effect = [
            requests.exceptions.ConnectionError("reset"),
            _ok_response(b"real-photo-data"),
        ]
        dest = str(tmp_path / "photo.jpg")

        with patch("docu_studio.slideshow.slideshow_photo_download.time.sleep"):
            result = download_photo_resilient(session, "https://images.pexels.com/a.jpg", dest)

        assert result == dest
        assert Path(dest).read_bytes() == b"real-photo-data"
        assert session.get.call_count == 2

    def test_retries_on_5xx_and_429(self, tmp_path: Path) -> None:
        for status in (429, 500, 503):
            session = MagicMock()
            session.get.side_effect = [_http_error_response(status), _ok_response()]
            dest = str(tmp_path / f"photo_{status}.jpg")

            with patch("docu_studio.slideshow.slideshow_photo_download.time.sleep"):
                result = download_photo_resilient(session, "https://cdn.pixabay.com/a.jpg", dest)

            assert result == dest
            assert session.get.call_count == 2

    def test_gives_up_after_max_attempts(self, tmp_path: Path) -> None:
        session = MagicMock()
        session.get.side_effect = requests.exceptions.ConnectionError("reset")
        dest = str(tmp_path / "photo.jpg")

        with patch("docu_studio.slideshow.slideshow_photo_download.time.sleep"):
            with pytest.raises(requests.exceptions.ConnectionError):
                download_photo_resilient(session, "https://images.pexels.com/a.jpg", dest)

        assert session.get.call_count == 3


class TestNoRetryOnClientErrors:
    def test_does_not_retry_on_404(self, tmp_path: Path) -> None:
        session = MagicMock()
        session.get.return_value = _http_error_response(404)
        dest = str(tmp_path / "photo.jpg")

        with patch("docu_studio.slideshow.slideshow_photo_download.time.sleep") as mock_sleep:
            with pytest.raises(requests.exceptions.HTTPError):
                download_photo_resilient(session, "https://images.pexels.com/a.jpg", dest)

        assert session.get.call_count == 1
        mock_sleep.assert_not_called()


class TestSessionAndHeaders:
    def test_build_download_session_sets_browser_user_agent(self) -> None:
        session = build_download_session()
        assert session.headers["User-Agent"] == BROWSER_USER_AGENT

    def test_get_called_with_stream_and_explicit_connect_read_timeouts(self, tmp_path: Path) -> None:
        session = MagicMock()
        session.get.return_value = _ok_response()
        dest = str(tmp_path / "photo.jpg")

        download_photo_resilient(session, "https://images.pexels.com/a.jpg", dest)

        _args, kwargs = session.get.call_args
        assert kwargs["stream"] is True
        assert kwargs["timeout"] == (10, 30)


class TestSameHostPacing:
    def test_sleeps_when_last_request_to_same_host_was_recent(self, tmp_path: Path) -> None:
        session = MagicMock()
        session.get.return_value = _ok_response()
        dest = str(tmp_path / "photo.jpg")
        last_request_at = {"images.pexels.com": 1000.0}

        with patch("docu_studio.slideshow.slideshow_photo_download.time.monotonic", return_value=1000.05):
            with patch("docu_studio.slideshow.slideshow_photo_download.time.sleep") as mock_sleep:
                download_photo_resilient(session, "https://images.pexels.com/a.jpg", dest, last_request_at)

        mock_sleep.assert_called_once()
        (delay,), _ = mock_sleep.call_args
        assert 0.0 < delay <= 0.5


class TestFetchTopicImages:
    def test_downloads_up_to_count_and_returns_local_paths(self, tmp_path: Path) -> None:
        provider = MagicMock()
        provider.search.return_value = [
            PhotoResult(url=f"https://images.pexels.com/{i}.jpg", width=1920, height=1080, photo_id=str(i))
            for i in range(5)
        ]
        with patch(
            "docu_studio.slideshow.slideshow_photo_download.download_photo_resilient",
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
            "docu_studio.slideshow.slideshow_photo_download.download_photo_resilient",
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
            "docu_studio.slideshow.slideshow_photo_download.download_photo_resilient",
            side_effect=lambda session, url, dest, last=None: dest,
        ):
            paths = fetch_topic_images("mountains", 2, [provider_a, provider_b], tmp_path)

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
            "docu_studio.slideshow.slideshow_photo_download.download_photo_resilient",
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
            "docu_studio.slideshow.slideshow_photo_download.download_photo_resilient",
            side_effect=requests.exceptions.ConnectionError("boom"),
        ):
            with pytest.raises(RuntimeError):
                fetch_topic_images("mountains", 1, [provider], tmp_path)

    def test_zero_or_negative_count_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            fetch_topic_images("mountains", 0, [MagicMock()], tmp_path)
