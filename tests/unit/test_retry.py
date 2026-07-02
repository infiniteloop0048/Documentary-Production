"""Unit tests for retry decorator."""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from docu_studio.retry import retry


class TestRetryDecorator:
    def test_succeeds_on_first_attempt(self) -> None:
        mock_fn = MagicMock(return_value="ok")

        @retry(max_attempts=3)
        def fn():
            return mock_fn()

        assert fn() == "ok"
        assert mock_fn.call_count == 1

    def test_retries_on_exception_and_succeeds(self) -> None:
        mock_fn = MagicMock(side_effect=[ValueError("fail"), ValueError("fail"), "ok"])

        @retry(max_attempts=3, base_delay=0.0)
        def fn():
            return mock_fn()

        with patch("time.sleep"):
            result = fn()
        assert result == "ok"
        assert mock_fn.call_count == 3

    def test_raises_after_all_attempts_exhausted(self) -> None:
        mock_fn = MagicMock(side_effect=RuntimeError("always fails"))

        @retry(max_attempts=3, base_delay=0.0)
        def fn():
            return mock_fn()

        with patch("time.sleep"):
            with pytest.raises(RuntimeError, match="always fails"):
                fn()
        assert mock_fn.call_count == 3

    def test_sleep_called_with_exponential_backoff(self) -> None:
        mock_fn = MagicMock(side_effect=[ValueError(), ValueError(), "done"])

        @retry(max_attempts=3, base_delay=1.0, backoff_factor=2.0)
        def fn():
            return mock_fn()

        with patch("time.sleep") as mock_sleep:
            fn()

        assert mock_sleep.call_count == 2
        sleep_args = [c[0][0] for c in mock_sleep.call_args_list]
        assert sleep_args[0] == pytest.approx(1.0)
        assert sleep_args[1] == pytest.approx(2.0)

    def test_original_exception_type_preserved(self) -> None:
        @retry(max_attempts=2, base_delay=0.0)
        def fn():
            raise KeyError("missing")

        with patch("time.sleep"):
            with pytest.raises(KeyError):
                fn()
