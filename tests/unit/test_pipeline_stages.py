"""Unit tests for all pipeline stage functions."""
from __future__ import annotations

import json
import queue
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docu_studio.pipeline.events import ErrorEvent, LogEvent, LogLevel, ProgressEvent
from docu_studio.pipeline.stages import (
    fcpxml_export,
    keyword_extract,
    scene_break,
    script_gen,
    tts_gen,
)
from docu_studio.pipeline.stages import topic_discovery
from docu_studio.pipeline.stages.scene_break import Scene


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _queue_list(q: queue.Queue) -> list:
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    return items


def _mock_llm(**kwargs) -> MagicMock:
    m = MagicMock()
    for k, v in kwargs.items():
        setattr(m, k, MagicMock(return_value=v))
    return m


def _make_scene(index: int = 1, *, audio_duration: float = 10.0) -> Scene:
    s = Scene(index=index, title=f"Scene {index}", narration="Narration text.")
    s.audio_path = f"/tmp/scene_{index:03d}.mp3"
    s.audio_duration = audio_duration
    s.video_path = f"/tmp/scene_{index:03d}.mp4"
    s.video_duration = audio_duration
    return s


# ---------------------------------------------------------------------------
# script_gen
# ---------------------------------------------------------------------------

class TestScriptGen:
    def test_returns_script_string(self, tmp_path: Path) -> None:
        llm = _mock_llm(generate_script="Documentary script here.")
        q: queue.Queue = queue.Queue()
        result = script_gen.run("Apollo 11", 5, llm, tmp_path, q)
        assert result == "Documentary script here."

    def test_writes_script_md(self, tmp_path: Path) -> None:
        llm = _mock_llm(generate_script="My script.")
        script_gen.run("Topic", 3, llm, tmp_path, queue.Queue())
        assert (tmp_path / "script.md").read_text() == "My script."

    def test_emits_progress_and_log_events(self, tmp_path: Path) -> None:
        llm = _mock_llm(generate_script="words " * 10)
        q: queue.Queue = queue.Queue()
        script_gen.run("Topic", 3, llm, tmp_path, q)
        events = _queue_list(q)
        assert any(isinstance(e, ProgressEvent) for e in events)
        assert any(isinstance(e, LogEvent) for e in events)

    def test_calls_llm_with_target_words(self, tmp_path: Path) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "script"
        script_gen.run("Topic", 10, llm, tmp_path, queue.Queue())
        llm.generate_script.assert_called_once()
        _, target_words = llm.generate_script.call_args[0]
        assert target_words == 10 * 150  # DEFAULT_WPM = 150

    def test_warns_when_actual_word_count_far_below_target(self, tmp_path: Path) -> None:
        # 30 min target = 4500 words; LLM only returns ~100 words (reproduces the bug report).
        llm = _mock_llm(generate_script="word " * 100)
        q: queue.Queue = queue.Queue()
        script_gen.run("Topic", 30, llm, tmp_path, q)
        events = _queue_list(q)
        warnings = [e for e in events if isinstance(e, LogEvent) and e.level == LogLevel.WARNING]
        assert warnings, "expected a WARNING LogEvent when actual word count misses target by >10%"
        assert any("word count" in e.message.lower() for e in warnings)
        assert any("4500" in e.message for e in warnings)

    def test_no_warning_when_word_count_within_tolerance(self, tmp_path: Path) -> None:
        llm = _mock_llm(generate_script="word " * 4500)
        q: queue.Queue = queue.Queue()
        script_gen.run("Topic", 30, llm, tmp_path, q)
        events = _queue_list(q)
        warnings = [e for e in events if isinstance(e, LogEvent) and e.level == LogLevel.WARNING]
        assert not warnings

    def test_emits_distinct_warning_when_generation_stopped_early_for_diminishing_returns(
        self, tmp_path: Path
    ) -> None:
        # Simulate an LLMProvider whose chunked generation gave up early because a
        # chunk's contribution plateaued (see base.py's on_diminishing_returns hook).
        def _fake_generate_script(topic, target_words, on_diminishing_returns=None):
            if on_diminishing_returns is not None:
                on_diminishing_returns(400)
            return "word " * 100

        llm = MagicMock()
        llm.generate_script.side_effect = _fake_generate_script
        q: queue.Queue = queue.Queue()
        script_gen.run("Topic", 30, llm, tmp_path, q)
        events = _queue_list(q)
        warnings = [e for e in events if isinstance(e, LogEvent) and e.level == LogLevel.WARNING]

        diminishing = [e for e in warnings if "diminishing returns" in e.message.lower()]
        assert diminishing, "expected a distinct diminishing-returns WARNING LogEvent"
        assert "400" in diminishing[0].message

        # The existing generic "missed target" warning should still fire too — the
        # two failure modes must be distinguishable, not merged into one message.
        generic = [e for e in warnings if "diminishing returns" not in e.message.lower()]
        assert generic, "expected the pre-existing word-count-target-missed warning as well"


# ---------------------------------------------------------------------------
# scene_break
# ---------------------------------------------------------------------------

class TestSceneBreak:
    def test_returns_list_of_scenes(self, tmp_path: Path) -> None:
        llm = _mock_llm(break_into_scenes=[
            {"title": "Opening", "narration": "Start text."},
            {"title": "Middle", "narration": "Middle text."},
        ])
        scenes = scene_break.run("script text", llm, tmp_path, queue.Queue())
        assert len(scenes) == 2
        assert all(isinstance(s, Scene) for s in scenes)

    def test_scene_indices_start_at_one(self, tmp_path: Path) -> None:
        llm = _mock_llm(break_into_scenes=[
            {"title": "S1", "narration": "N1"},
            {"title": "S2", "narration": "N2"},
        ])
        scenes = scene_break.run("script", llm, tmp_path, queue.Queue())
        assert [s.index for s in scenes] == [1, 2]

    def test_writes_scenes_json(self, tmp_path: Path) -> None:
        llm = _mock_llm(break_into_scenes=[{"title": "T", "narration": "N"}])
        scene_break.run("script", llm, tmp_path, queue.Queue())
        data = json.loads((tmp_path / "scenes.json").read_text())
        assert isinstance(data, list)
        assert data[0]["title"] == "T"

    def test_emits_events(self, tmp_path: Path) -> None:
        llm = _mock_llm(break_into_scenes=[{"title": "T", "narration": "N"}])
        q: queue.Queue = queue.Queue()
        scene_break.run("script", llm, tmp_path, q)
        events = _queue_list(q)
        assert any(isinstance(e, ProgressEvent) for e in events)
        assert any(isinstance(e, LogEvent) for e in events)


# ---------------------------------------------------------------------------
# tts_gen
# ---------------------------------------------------------------------------

class TestTtsGen:
    def test_sets_audio_path_and_duration(self, tmp_path: Path) -> None:
        tts = MagicMock()
        tts.synthesize.return_value = 12.5
        scenes = [Scene(index=1, title="T", narration="N")]
        (tmp_path / "audio").mkdir()
        tts_gen.run(scenes, tts, tmp_path, queue.Queue())
        assert scenes[0].audio_duration == 12.5
        assert scenes[0].audio_path is not None

    def test_calls_synthesize_once_per_scene(self, tmp_path: Path) -> None:
        tts = MagicMock()
        tts.synthesize.return_value = 5.0
        scenes = [Scene(index=i, title="T", narration="N") for i in range(1, 4)]
        (tmp_path / "audio").mkdir()
        tts_gen.run(scenes, tts, tmp_path, queue.Queue())
        assert tts.synthesize.call_count == 3

    def test_emits_events_per_scene(self, tmp_path: Path) -> None:
        tts = MagicMock()
        tts.synthesize.return_value = 3.0
        scenes = [Scene(index=1, title="T", narration="N"),
                  Scene(index=2, title="T2", narration="N2")]
        (tmp_path / "audio").mkdir()
        q: queue.Queue = queue.Queue()
        tts_gen.run(scenes, tts, tmp_path, q)
        events = _queue_list(q)
        progress_events = [e for e in events if isinstance(e, ProgressEvent)]
        assert len(progress_events) == 2


# ---------------------------------------------------------------------------
# keyword_extract
# ---------------------------------------------------------------------------

class TestKeywordExtract:
    def test_sets_visual_keywords_on_scenes(self) -> None:
        llm = MagicMock()
        llm.extract_visual_keywords.return_value = ["space", "rocket"]
        scenes = [Scene(index=1, title="Moon", narration="Astronauts landed.")]
        keyword_extract.run(scenes, llm, queue.Queue())
        assert scenes[0].visual_keywords == ["space", "rocket"]

    def test_calls_extract_once_per_scene(self) -> None:
        llm = MagicMock()
        llm.extract_visual_keywords.return_value = ["kw"]
        scenes = [Scene(index=i, title="T", narration="N") for i in range(1, 5)]
        keyword_extract.run(scenes, llm, queue.Queue())
        assert llm.extract_visual_keywords.call_count == 4

    def test_emits_progress_and_log_events(self) -> None:
        llm = MagicMock()
        llm.extract_visual_keywords.return_value = ["kw"]
        scenes = [Scene(index=1, title="T", narration="N")]
        q: queue.Queue = queue.Queue()
        keyword_extract.run(scenes, llm, q)
        events = _queue_list(q)
        assert any(isinstance(e, ProgressEvent) for e in events)
        assert any(isinstance(e, LogEvent) for e in events)


# ---------------------------------------------------------------------------
# fcpxml_export
# ---------------------------------------------------------------------------

class TestFcpxmlExport:
    def test_writes_timeline_fcpxml(self, tmp_path: Path) -> None:
        scene = _make_scene(1, audio_duration=10.0)
        q: queue.Queue = queue.Queue()
        fcpxml_export.run([scene], "Test Topic", tmp_path, q)
        assert (tmp_path / "timeline.fcpxml").exists()

    def test_emits_log_event_on_success(self, tmp_path: Path) -> None:
        scene = _make_scene(1, audio_duration=10.0)
        q: queue.Queue = queue.Queue()
        fcpxml_export.run([scene], "Topic", tmp_path, q)
        events = _queue_list(q)
        assert any(isinstance(e, LogEvent) for e in events)

    def test_skips_scenes_with_shortage(self, tmp_path: Path) -> None:
        scene = _make_scene(1, audio_duration=10.0)
        scene.footage_shortage = True
        q: queue.Queue = queue.Queue()
        fcpxml_export.run([scene], "Topic", tmp_path, q)
        events = _queue_list(q)
        # No complete scenes → ErrorEvent emitted, no file written
        assert any(isinstance(e, ErrorEvent) for e in events)
        assert not (tmp_path / "timeline.fcpxml").exists()

    def test_emits_error_when_no_complete_scenes(self, tmp_path: Path) -> None:
        q: queue.Queue = queue.Queue()
        fcpxml_export.run([], "Topic", tmp_path, q)
        events = _queue_list(q)
        error_events = [e for e in events if isinstance(e, ErrorEvent)]
        assert error_events
        assert error_events[0].fatal is False


# ---------------------------------------------------------------------------
# topic_discovery
# ---------------------------------------------------------------------------

class TestTopicDiscovery:
    def test_returns_topic_result(self) -> None:
        llm = MagicMock()
        llm.suggest_topic.return_value = "The Fall of Rome"
        result = topic_discovery.run(llm, queue.Queue())
        assert result.topic == "The Fall of Rome"
        assert result.source == "ai_suggested"

    def test_emits_progress_and_log_events(self) -> None:
        llm = MagicMock()
        llm.suggest_topic.return_value = "Topic"
        q: queue.Queue = queue.Queue()
        topic_discovery.run(llm, q)
        events = _queue_list(q)
        assert any(isinstance(e, ProgressEvent) for e in events)
        assert any(isinstance(e, LogEvent) for e in events)
