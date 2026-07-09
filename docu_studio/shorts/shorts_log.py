"""Per-run log-file teeing for Shorts runs, mirroring pipeline.runner._TeeQueue.

Kept as a separate module (not importing from pipeline.runner) per the Shorts
package's existing boundary of not depending on pipeline.runner internals — this
is a parallel implementation, not a reuse of the private _TeeQueue class.
"""
from __future__ import annotations

import logging
import queue
from datetime import datetime
from pathlib import Path
from typing import IO

from docu_studio.pipeline.events import (
    ErrorEvent,
    LogEvent,
    LogLevel,
    ProgressEvent,
    sanitize_log_message,
)


class ShortsTeeQueue(queue.Queue):
    """queue.Queue that mirrors every put() to an optional shorts_log.txt file.

    The log file is opened by open_log() once the project folder exists and
    closed by close_log() in the runner's finally block. Log writes are
    best-effort — an OSError never propagates to the caller.
    """

    def __init__(self) -> None:
        super().__init__()
        self._log_file: IO[str] | None = None
        self._sensitive_keys: list[str] = []

    def open_log(self, path: Path, sensitive_keys: list[str]) -> None:
        self._sensitive_keys = sensitive_keys
        self._log_file = path.open("w", encoding="utf-8")

    def close_log(self) -> None:
        if self._log_file is not None:
            try:
                self._log_file.flush()
                self._log_file.close()
            finally:
                self._log_file = None

    def put(self, item: object, block: bool = True, timeout: float | None = None) -> None:  # type: ignore[override]
        if self._log_file is not None and item is not None:
            self._tee(item)
        super().put(item, block, timeout)

    def _tee(self, event: object) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        if isinstance(event, LogEvent):
            msg = sanitize_log_message(event.message, self._sensitive_keys)
            line = f"[{ts}] {event.level.value.upper()}: {msg}"
        elif isinstance(event, ProgressEvent):
            line = f"[{ts}] PROGRESS: {event.stage}: {event.message}"
        elif isinstance(event, ErrorEvent):
            msg = sanitize_log_message(event.message, self._sensitive_keys)
            line = f"[{ts}] ERROR: {msg}"
        else:
            return
        try:
            self._log_file.write(line + "\n")  # type: ignore[union-attr]
            self._log_file.flush()
        except OSError:
            pass


class QueueLoggingHandler(logging.Handler):
    """Forwards stdlib `logging` records into a ShortsTeeQueue as LogEvents.

    Attached to the "docu_studio.shorts" logger for a run's lifetime so every
    module-level `_log.info()`/`_log.warning()` call made anywhere under
    docu_studio.shorts (capability_resolvers, shorts_alignment, shorts_ffmpeg,
    shorts_assembly, music_library, ...) lands in shorts_log.txt and the GUI
    log panel automatically, without editing any of those call sites.
    """

    _LEVEL_MAP = {
        logging.DEBUG: LogLevel.INFO,
        logging.INFO: LogLevel.INFO,
        logging.WARNING: LogLevel.WARNING,
        logging.ERROR: LogLevel.ERROR,
        logging.CRITICAL: LogLevel.ERROR,
    }

    def __init__(self, target_queue: "queue.Queue[object]") -> None:
        super().__init__()
        self._queue = target_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = self._LEVEL_MAP.get(record.levelno, LogLevel.INFO)
            self._queue.put(LogEvent(message=record.getMessage(), level=level))
        except Exception:
            pass  # logging must never crash the run
