"""Unit tests for footage_assembly multi-clip accumulation logic."""
from __future__ import annotations

import queue
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from docu_studio.adapters.footage.base import FootageClip
from docu_studio.pipeline.events import ErrorEvent, LogEvent, PipelineEvent


def _provider(name: str, clips: list[FootageClip]) -> object:
    """Build a fake provider instance whose class name drives _provider_name()."""
    cls = type(name, (), {"search": lambda self, keywords, min_duration, page=1: clips})
    return cls()


@dataclass
class _Scene:
    index: int
    title: str
    narration: str
    visual_keywords: list[str]
    audio_path: str
    audio_duration: float
    video_path: str | None = None
    video_duration: float | None = None
    footage_shortage: bool = False


def _make_clips(durations: list[float]) -> list[FootageClip]:
    return [
        FootageClip(url=f"https://cdn/clip{i}.mp4", duration=d, width=1920, height=1080)
        for i, d in enumerate(durations)
    ]


class TestFootageAssembly:
    def _run_assemble(
        self,
        scene: _Scene,
        clip_lists: list[list[FootageClip]],
        project_folder: Path,
    ) -> tuple[_Scene, list[PipelineEvent]]:
        from docu_studio.pipeline.stages.footage_assembly import assemble_footage_for_scene

        evt_queue: queue.Queue = queue.Queue()
        provider_mocks = []
        for clips in clip_lists:
            m = MagicMock()
            m.search.return_value = clips
            provider_mocks.append(m)

        ffmpeg_mock = MagicMock()
        ffmpeg_mock.get_duration.side_effect = lambda p: {
            f"dl_0_{i}": d
            for i, d in enumerate([c.duration for p_clips in clip_lists for c in p_clips])
        }.get(Path(p).stem, 5.0)

        with patch(
            "docu_studio.pipeline.stages.footage_assembly.download_clip",
            side_effect=lambda url, dest: dest,
        ):
            assemble_footage_for_scene(
                scene=scene,
                providers=provider_mocks,
                ffmpeg=ffmpeg_mock,
                project_folder=project_folder,
                event_queue=evt_queue,
            )

        events = []
        while not evt_queue.empty():
            events.append(evt_queue.get_nowait())
        return scene, events

    def test_clips_accumulate_until_covering_audio_duration(self, tmp_path: Path) -> None:
        scene = _Scene(
            index=1, title="S1", narration="n", visual_keywords=["sky"],
            audio_path=str(tmp_path / "audio.mp3"), audio_duration=12.0,
        )
        clips = _make_clips([5.0, 5.0, 5.0])
        ffmpeg_mock = MagicMock()
        ffmpeg_mock.get_duration.side_effect = lambda p: 5.0
        evt_queue: queue.Queue = queue.Queue()
        provider = MagicMock()
        provider.search.return_value = clips

        with patch(
            "docu_studio.pipeline.stages.footage_assembly.download_clip",
            side_effect=lambda url, dest: dest,
        ):
            from docu_studio.pipeline.stages.footage_assembly import assemble_footage_for_scene
            assemble_footage_for_scene(
                scene=scene,
                providers=[provider],
                ffmpeg=ffmpeg_mock,
                project_folder=tmp_path,
                event_queue=evt_queue,
            )

        # mux called once per scene
        assert ffmpeg_mock.mux_audio_video.call_count == 1

    def test_footage_shortage_flagged_when_providers_exhausted(self, tmp_path: Path) -> None:
        scene = _Scene(
            index=1, title="S1", narration="n", visual_keywords=["ocean"],
            audio_path=str(tmp_path / "audio.mp3"), audio_duration=30.0,
        )
        clips = _make_clips([3.0])  # only 3 s, need 30 s
        provider = MagicMock()
        provider.search.return_value = clips
        ffmpeg_mock = MagicMock()
        ffmpeg_mock.get_duration.return_value = 3.0
        evt_queue: queue.Queue = queue.Queue()

        with patch(
            "docu_studio.pipeline.stages.footage_assembly.download_clip",
            side_effect=lambda url, dest: dest,
        ):
            from docu_studio.pipeline.stages.footage_assembly import assemble_footage_for_scene
            assemble_footage_for_scene(
                scene=scene,
                providers=[provider],
                ffmpeg=ffmpeg_mock,
                project_folder=tmp_path,
                event_queue=evt_queue,
            )

        assert scene.footage_shortage is True
        events = []
        while not evt_queue.empty():
            events.append(evt_queue.get_nowait())
        error_events = [e for e in events if isinstance(e, ErrorEvent)]
        assert any(not e.fatal and e.shortage for e in error_events)

    def test_mux_audio_video_called_exactly_once_per_scene(self, tmp_path: Path) -> None:
        scene = _Scene(
            index=1, title="S1", narration="n", visual_keywords=["forest"],
            audio_path=str(tmp_path / "audio.mp3"), audio_duration=8.0,
        )
        clips = _make_clips([10.0])
        provider = MagicMock()
        provider.search.return_value = clips
        ffmpeg_mock = MagicMock()
        ffmpeg_mock.get_duration.return_value = 10.0
        evt_queue: queue.Queue = queue.Queue()

        with patch(
            "docu_studio.pipeline.stages.footage_assembly.download_clip",
            side_effect=lambda url, dest: dest,
        ):
            from docu_studio.pipeline.stages.footage_assembly import assemble_footage_for_scene
            assemble_footage_for_scene(
                scene=scene,
                providers=[provider],
                ffmpeg=ffmpeg_mock,
                project_folder=tmp_path,
                event_queue=evt_queue,
            )

        assert ffmpeg_mock.mux_audio_video.call_count == 1

    def test_logs_whether_source_clip_had_audio_and_that_tts_was_used(self, tmp_path: Path) -> None:
        scene = _Scene(
            index=1, title="S1", narration="n", visual_keywords=["forest"],
            audio_path=str(tmp_path / "audio.mp3"), audio_duration=8.0,
        )
        clips = _make_clips([10.0])
        provider = MagicMock()
        provider.search.return_value = clips
        ffmpeg_mock = MagicMock()
        ffmpeg_mock.get_duration.return_value = 10.0
        ffmpeg_mock.has_audio_stream.return_value = True
        evt_queue: queue.Queue = queue.Queue()

        with patch(
            "docu_studio.pipeline.stages.footage_assembly.download_clip",
            side_effect=lambda url, dest: dest,
        ):
            from docu_studio.pipeline.stages.footage_assembly import assemble_footage_for_scene
            assemble_footage_for_scene(
                scene=scene,
                providers=[provider],
                ffmpeg=ffmpeg_mock,
                project_folder=tmp_path,
                event_queue=evt_queue,
            )

        assert ffmpeg_mock.has_audio_stream.called
        events = []
        while not evt_queue.empty():
            events.append(evt_queue.get_nowait())
        log_events = [e for e in events if isinstance(e, LogEvent)]
        audio_logs = [e for e in log_events if "source clip had audio" in e.message.lower()]
        assert len(audio_logs) == 1
        assert "yes" in audio_logs[0].message.lower()
        assert "audio track used: tts" in audio_logs[0].message.lower()

    def test_logs_no_source_audio_when_clip_is_silent(self, tmp_path: Path) -> None:
        scene = _Scene(
            index=2, title="S2", narration="n", visual_keywords=["forest"],
            audio_path=str(tmp_path / "audio.mp3"), audio_duration=8.0,
        )
        clips = _make_clips([10.0])
        provider = MagicMock()
        provider.search.return_value = clips
        ffmpeg_mock = MagicMock()
        ffmpeg_mock.get_duration.return_value = 10.0
        ffmpeg_mock.has_audio_stream.return_value = False
        evt_queue: queue.Queue = queue.Queue()

        with patch(
            "docu_studio.pipeline.stages.footage_assembly.download_clip",
            side_effect=lambda url, dest: dest,
        ):
            from docu_studio.pipeline.stages.footage_assembly import assemble_footage_for_scene
            assemble_footage_for_scene(
                scene=scene,
                providers=[provider],
                ffmpeg=ffmpeg_mock,
                project_folder=tmp_path,
                event_queue=evt_queue,
            )

        events = []
        while not evt_queue.empty():
            events.append(evt_queue.get_nowait())
        log_events = [e for e in events if isinstance(e, LogEvent)]
        audio_logs = [e for e in log_events if "source clip had audio" in e.message.lower()]
        assert len(audio_logs) == 1
        assert "no" in audio_logs[0].message.lower()

    def test_logs_which_video_source_was_used_for_single_provider(self, tmp_path: Path) -> None:
        scene = _Scene(
            index=1, title="S1", narration="n", visual_keywords=["forest"],
            audio_path=str(tmp_path / "audio.mp3"), audio_duration=8.0,
        )
        provider = _provider("PexelsAdapter", _make_clips([10.0]))
        ffmpeg_mock = MagicMock()
        ffmpeg_mock.get_duration.return_value = 10.0
        ffmpeg_mock.has_audio_stream.return_value = False
        evt_queue: queue.Queue = queue.Queue()

        with patch(
            "docu_studio.pipeline.stages.footage_assembly.download_clip",
            side_effect=lambda url, dest: dest,
        ):
            from docu_studio.pipeline.stages.footage_assembly import assemble_footage_for_scene
            assemble_footage_for_scene(
                scene=scene,
                providers=[provider],
                ffmpeg=ffmpeg_mock,
                project_folder=tmp_path,
                event_queue=evt_queue,
            )

        events = []
        while not evt_queue.empty():
            events.append(evt_queue.get_nowait())
        log_events = [e for e in events if isinstance(e, LogEvent)]
        source_logs = [e for e in log_events if "video source" in e.message.lower()]
        assert len(source_logs) == 1
        assert "pexels" in source_logs[0].message.lower()

    def test_logs_multiple_video_sources_when_scene_uses_more_than_one_provider(
        self, tmp_path: Path
    ) -> None:
        scene = _Scene(
            index=2, title="S2", narration="n", visual_keywords=["ocean"],
            audio_path=str(tmp_path / "audio.mp3"), audio_duration=8.0,
        )
        empty_provider = _provider("PexelsAdapter", [])
        filled_provider = _provider("PixabayAdapter", _make_clips([10.0]))
        ffmpeg_mock = MagicMock()
        ffmpeg_mock.get_duration.return_value = 10.0
        ffmpeg_mock.has_audio_stream.return_value = False
        evt_queue: queue.Queue = queue.Queue()

        with patch(
            "docu_studio.pipeline.stages.footage_assembly.download_clip",
            side_effect=lambda url, dest: dest,
        ):
            from docu_studio.pipeline.stages.footage_assembly import assemble_footage_for_scene
            assemble_footage_for_scene(
                scene=scene,
                providers=[empty_provider, filled_provider],
                ffmpeg=ffmpeg_mock,
                project_folder=tmp_path,
                event_queue=evt_queue,
            )

        events = []
        while not evt_queue.empty():
            events.append(evt_queue.get_nowait())
        log_events = [e for e in events if isinstance(e, LogEvent)]
        source_logs = [e for e in log_events if "video source" in e.message.lower()]
        assert len(source_logs) == 1
        assert "pixabay" in source_logs[0].message.lower()
        assert "pexels" not in source_logs[0].message.lower()
