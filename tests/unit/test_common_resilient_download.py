"""Unit tests for the shared resilient-HTTP-download primitives: retry with
backoff on transient failures, no retry on client errors, session/header/
timeout consistency, and same-host pacing. No real network calls — session
is always a MagicMock.

Union of the former test_shorts_footage_download.py (the more complete of
the two, including caplog assertions on the retry log messages) and
test_slideshow_photo_download.py's primitive-coverage classes (deduped
where both asserted the same behavior with only a different function/module
name — `download_clip_resilient`/`download_photo_resilient` are now the
single `download_resilient` in docu_studio/common/resilient_download.py).
test_slideshow_photo_download.py keeps its `fetch_topic_images`-specific
`TestFetchTopicImages` class, which is feature-specific orchestration and
stays in slideshow/.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from docu_studio.common.resilient_download import (
    BROWSER_USER_AGENT,
    build_download_session,
    download_resilient,
)


def _ok_response(body: bytes = b"clip-bytes") -> MagicMock:
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
    def test_retries_on_connection_error_and_succeeds_on_later_attempt(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        session = MagicMock()
        session.get.side_effect = [
            requests.exceptions.ConnectionError(
                "('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))"
            ),
            _ok_response(b"real-clip-data"),
        ]
        dest = str(tmp_path / "clip.mp4")

        with patch("docu_studio.common.resilient_download.time.sleep") as mock_sleep:
            with caplog.at_level("INFO"):
                result = download_resilient(session, "https://videos.pexels.com/a.mp4", dest)

        assert result == dest
        assert Path(dest).read_bytes() == b"real-clip-data"
        assert session.get.call_count == 2
        mock_sleep.assert_called_once()
        messages = [r.message for r in caplog.records]
        assert any("download attempt 1/3" in m and "ConnectionError" in m for m in messages)

    def test_retries_on_5xx_and_429(self, tmp_path: Path) -> None:
        for status in (429, 500, 503):
            session = MagicMock()
            session.get.side_effect = [_http_error_response(status), _ok_response()]
            dest = str(tmp_path / f"clip_{status}.mp4")

            with patch("docu_studio.common.resilient_download.time.sleep"):
                result = download_resilient(session, "https://cdn.pixabay.com/a.mp4", dest)

            assert result == dest
            assert session.get.call_count == 2

    def test_gives_up_after_max_attempts_and_logs_clearly(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        session = MagicMock()
        session.get.side_effect = requests.exceptions.ConnectionError("reset")
        dest = str(tmp_path / "clip.mp4")

        with patch("docu_studio.common.resilient_download.time.sleep"):
            with caplog.at_level("INFO"):
                with pytest.raises(requests.exceptions.ConnectionError):
                    download_resilient(session, "https://videos.pexels.com/a.mp4", dest)

        assert session.get.call_count == 3
        messages = [r.message for r in caplog.records]
        assert any("download attempt 1/3" in m for m in messages)
        assert any("download attempt 2/3" in m for m in messages)
        assert not any("download attempt 3/3" in m for m in messages)


class TestNoRetryOnClientErrors:
    def test_does_not_retry_on_404(self, tmp_path: Path) -> None:
        session = MagicMock()
        session.get.return_value = _http_error_response(404)
        dest = str(tmp_path / "clip.mp4")

        with patch("docu_studio.common.resilient_download.time.sleep") as mock_sleep:
            with pytest.raises(requests.exceptions.HTTPError):
                download_resilient(session, "https://videos.pexels.com/a.mp4", dest)

        assert session.get.call_count == 1
        mock_sleep.assert_not_called()


class TestSessionAndHeaders:
    def test_build_download_session_sets_browser_user_agent(self) -> None:
        session = build_download_session()
        assert session.headers["User-Agent"] == BROWSER_USER_AGENT

    def test_get_called_with_stream_and_explicit_connect_read_timeouts(self, tmp_path: Path) -> None:
        session = MagicMock()
        session.get.return_value = _ok_response()
        dest = str(tmp_path / "clip.mp4")

        download_resilient(session, "https://videos.pexels.com/a.mp4", dest)

        _args, kwargs = session.get.call_args
        assert kwargs["stream"] is True
        assert kwargs["timeout"] == (10, 30)


class TestSameHostPacing:
    def test_sleeps_when_last_request_to_same_host_was_recent(self, tmp_path: Path) -> None:
        session = MagicMock()
        session.get.return_value = _ok_response()
        dest = str(tmp_path / "clip.mp4")
        last_request_at = {"videos.pexels.com": 1000.0}

        with patch("docu_studio.common.resilient_download.time.monotonic", return_value=1000.05):
            with patch("docu_studio.common.resilient_download.time.sleep") as mock_sleep:
                download_resilient(session, "https://videos.pexels.com/a.mp4", dest, last_request_at)

        mock_sleep.assert_called_once()
        (delay,), _ = mock_sleep.call_args
        assert 0.0 < delay <= 0.5

    def test_no_delay_for_a_different_host(self, tmp_path: Path) -> None:
        session = MagicMock()
        session.get.return_value = _ok_response()
        dest = str(tmp_path / "clip.mp4")
        last_request_at = {"videos.pexels.com": 1000.0}

        with patch("docu_studio.common.resilient_download.time.monotonic", return_value=1000.05):
            with patch("docu_studio.common.resilient_download.time.sleep") as mock_sleep:
                download_resilient(session, "https://cdn.pixabay.com/a.mp4", dest, last_request_at)

        mock_sleep.assert_not_called()

    def test_no_delay_on_first_request_to_a_host(self, tmp_path: Path) -> None:
        session = MagicMock()
        session.get.return_value = _ok_response()
        dest = str(tmp_path / "clip.mp4")
        last_request_at: dict[str, float] = {}

        download_resilient(session, "https://videos.pexels.com/a.mp4", dest, last_request_at)

        assert "videos.pexels.com" in last_request_at
