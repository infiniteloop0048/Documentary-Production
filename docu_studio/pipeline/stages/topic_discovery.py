"""Stage 0: Full Auto topic discovery — stub for Phase 4 (US2)."""
from __future__ import annotations

import queue
from dataclasses import dataclass

from docu_studio.adapters.llm.base import LLMProvider
from docu_studio.pipeline.events import LogEvent, LogLevel, ProgressEvent


@dataclass
class TopicResult:
    topic: str
    source: str  # "ai_suggested" | "web_search"


def run(llm: LLMProvider, event_queue: queue.Queue) -> TopicResult:
    """Discover a documentary topic via LLM suggestion (web search added in Phase 4)."""
    event_queue.put(ProgressEvent(stage="Topic Discovery", message="Generating topic suggestion…"))
    topic = llm.suggest_topic()
    event_queue.put(LogEvent(message=f"AI suggested topic: {topic}", level=LogLevel.INFO))
    return TopicResult(topic=topic, source="ai_suggested")
