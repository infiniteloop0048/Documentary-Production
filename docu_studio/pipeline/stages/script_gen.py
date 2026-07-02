"""Stage 1: Generate documentary script via LLMProvider."""
from __future__ import annotations

import logging
import queue
from pathlib import Path

from docu_studio.adapters.llm.base import LLMProvider
from docu_studio.config.defaults import DEFAULT_WPM
from docu_studio.pipeline.events import LogEvent, LogLevel, ProgressEvent

_log = logging.getLogger(__name__)

# How far actual word count may deviate from target before we warn (not silently accept it).
_WORD_COUNT_WARN_TOLERANCE = 0.10


def run(
    topic: str,
    duration_minutes: int,
    llm: LLMProvider,
    project_folder: Path,
    event_queue: queue.Queue,
) -> str:
    target_words = duration_minutes * DEFAULT_WPM
    event_queue.put(ProgressEvent(stage="Script Generation", message=f"Generating script for '{topic}'…"))

    diminishing_returns_shortfall: list[int] = []
    script = llm.generate_script(
        topic, target_words, on_diminishing_returns=diminishing_returns_shortfall.append
    )
    if diminishing_returns_shortfall:
        event_queue.put(LogEvent(
            message=(
                "Script generation stopped early: diminishing returns, "
                f"{diminishing_returns_shortfall[0]} words short of target"
            ),
            level=LogLevel.WARNING,
        ))
    (project_folder / "script.md").write_text(script, encoding="utf-8")

    actual_words = len(script.split())
    event_queue.put(LogEvent(
        message=f"Script generated ({actual_words} words, target {target_words})",
        level=LogLevel.INFO,
    ))

    deviation = abs(actual_words - target_words) / target_words if target_words else 0.0
    if deviation > _WORD_COUNT_WARN_TOLERANCE:
        warning = (
            f"Script word count target missed: target={target_words} actual={actual_words} "
            f"({deviation:.0%} deviation) — final video runtime may not match the "
            f"requested {duration_minutes} min"
        )
        _log.warning(warning)
        event_queue.put(LogEvent(message=warning, level=LogLevel.WARNING))

    return script
