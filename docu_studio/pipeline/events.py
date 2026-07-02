"""Pipeline event types pushed from background thread to GUI queue."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Union


class LogLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    scene_index: int | None = None
    scene_total: int | None = None
    message: str = ""


@dataclass(frozen=True)
class LogEvent:
    message: str
    level: LogLevel = LogLevel.INFO


@dataclass(frozen=True)
class ErrorEvent:
    message: str
    fatal: bool = True
    shortage: bool = False


PipelineEvent = Union[ProgressEvent, LogEvent, ErrorEvent]


def sanitize_log_message(msg: str, keys: list[str]) -> str:
    """Replace every key substring in *msg* with '***REDACTED***'.

    All adapters MUST call this before constructing any LogEvent.message
    (Constitution Principle IV).
    """
    for key in keys:
        if key:
            msg = msg.replace(key, "***REDACTED***")
    return msg
