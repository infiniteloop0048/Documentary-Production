"""Retry decorator with exponential backoff for all external API calls."""
import time
import functools
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def retry(
    max_attempts: int = 3,
    backoff_factor: float = 2.0,
    base_delay: float = 1.0,
) -> Callable[[F], F]:
    """Decorator that retries *func* up to *max_attempts* times with exponential backoff.

    Re-raises the original exception unchanged after all attempts are exhausted.
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = base_delay
            last_exc: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt < max_attempts - 1:
                        time.sleep(delay)
                        delay *= backoff_factor
            raise last_exc  # type: ignore[misc]
        return wrapper  # type: ignore[return-value]
    return decorator
