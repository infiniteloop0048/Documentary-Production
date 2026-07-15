"""ShortsRunner — background thread that orchestrates the Shorts/Reels pipeline.

Mirrors docu_studio.pipeline.runner.PipelineRunner's public shape (event_queue,
cancel_event, _final_video_path, _project_folder, run()) so the existing
Bridge._translate_events() works unmodified for both run types. Does not import
from pipeline.runner — ShortsTeeQueue (shorts_log.py) is a parallel
implementation of pipeline.runner._TeeQueue used here for per-run
shorts_log.txt teeing; project folder + history integration are reused.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path

from docu_studio.adapters.footage.base import FootageProvider
from docu_studio.adapters.llm.base import LLMProvider
from docu_studio.adapters.tts.base import TTSProvider
from docu_studio.history.run_history import RunRecord, save_run
from docu_studio.output.project_folder import create_project_folder
from docu_studio.pipeline.events import ErrorEvent, LogEvent, LogLevel, ProgressEvent
from docu_studio.shorts.capability_resolvers import get_word_timestamps
from docu_studio.shorts.shorts_assembly import assemble_short
from docu_studio.shorts.shorts_config import ShortsConfig
from docu_studio.shorts.shorts_ffmpeg import ShortsFFmpeg
from docu_studio.shorts.shorts_log import QueueLoggingHandler, ShortsTeeQueue
from docu_studio.shorts.shorts_script_gen import generate_shorts_script
from docu_studio.shorts.shorts_tts_join import SilenceTrimParams
from docu_studio.shorts.shorts_tts_synthesis import (
    synthesize_sentences_concurrent,
    synthesize_sentences_sequential,
)
from docu_studio.common.tts_calibration import record_measurement

# gTTS-calibrated silence-trim parameters (Task 2, verified via real-audio
# silencedetect), reused here to join per-sentence gTTS clips back together
# — each sentence file IS gTTS output at this join layer, so the same
# real-audio-measured values apply.
_GTTS_JOIN_PARAMS = SilenceTrimParams(
    threshold_db="-45dB", pad_seconds=0.08, min_nonsilent_seconds=0.02, window_seconds=0.02,
)

# PLACEHOLDER — NOT yet calibrated against real ElevenLabs audio. Reusing
# gTTS's measured values as a structurally-reasonable starting point only; a
# real silencedetect calibration pass (same methodology as Task 2) against
# ElevenLabs' own real output is required before these can be trusted, and
# is blocked pending a real ElevenLabs API key.
_ELEVENLABS_JOIN_PARAMS = SilenceTrimParams(
    threshold_db="-45dB", pad_seconds=0.08, min_nonsilent_seconds=0.02, window_seconds=0.02,
)

# Deepgram-calibrated (Task 4 Phase 2 checkpoint, real silencedetect against
# 5 real Deepgram TTS outputs of varying length and ending phoneme, incl. a
# soft-consonant/fricative ending — "...need constant warmth."). -45dB
# (gTTS's value) does NOT transfer: unlike gTTS's clean digital silence,
# Deepgram's raw output carries residual decay/noise energy above -45dB near
# clip tails on longer sentences, which made silencedetect fail to find the
# true trailing-silence run at all on 2 of 5 samples (aura-asteria-en voice).
# -40dB reliably found genuine leading/trailing silence on all 5. Measured
# natural silence at -40dB ranged ~0.02s-0.22s across samples; 0.08s pad
# sits inside that range and was verified not to clip the soft-consonant
# sample's decay tail (RMS envelope fades gradually into the trim point,
# no abrupt cut).
_DEEPGRAM_JOIN_PARAMS = SilenceTrimParams(
    threshold_db="-40dB", pad_seconds=0.08, min_nonsilent_seconds=0.02, window_seconds=0.02,
)

# ElevenLabs: cap-1 (sequential) — its free tier's own concurrency ceiling is
# exactly 2, so running our own pool at cap-2 would leave zero margin; the
# @retry decorator exists for occasional failures, not routine ones (Task 4
# decision). Deepgram: cap-2 — confirmed against Deepgram's current docs at
# 15 concurrent on Pay-as-you-go/Growth tiers, wide margin.
_ELEVENLABS_MAX_CONCURRENCY = 1
_DEEPGRAM_MAX_CONCURRENCY = 2


class ShortsRunStatus(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ShortsRunner(threading.Thread):
    def __init__(
        self,
        topic: str,
        duration_seconds: int,
        llm: LLMProvider,
        tts: TTSProvider,
        footage_providers: list[FootageProvider],
        output_base: Path,
        captions_enabled: bool = True,
        music_enabled: bool = True,
        sensitive_keys: list[str] | None = None,
        seed: int | None = None,
        tts_provider: str = "",
        tts_voice: str = "",
        music_provider: str = "local",
        jamendo_client_id: str = "",
        beat_sync_enabled: bool = True,
        speed_ramp_enabled: bool = True,
        punch_enabled: bool = True,
        loop_revisit_enabled: bool = True,
        aspect_ratio: str = "9:16",
    ) -> None:
        super().__init__(daemon=True, name="ShortsRunner")
        self.config = ShortsConfig(
            topic=topic,
            aspect_ratio=aspect_ratio,
            duration_seconds=duration_seconds,
            captions_enabled=captions_enabled,
            music_enabled=music_enabled,
            beat_sync_enabled=beat_sync_enabled,
            speed_ramp_enabled=speed_ramp_enabled,
            punch_enabled=punch_enabled,
            loop_revisit_enabled=loop_revisit_enabled,
        )
        self.llm = llm
        self.tts = tts
        self.footage_providers = footage_providers
        self.output_base = output_base
        self._tts_provider = tts_provider
        self._tts_voice = tts_voice
        self._music_provider = music_provider
        self._jamendo_client_id = jamendo_client_id
        self._sensitive_keys: list[str] = sensitive_keys or []
        self._seed = seed if seed is not None else int(datetime.now().timestamp())

        self.event_queue: ShortsTeeQueue = ShortsTeeQueue()
        self.cancel_event = threading.Event()

        self._status = ShortsRunStatus.FAILED
        self._project_folder: Path | None = None
        self._final_video_path: Path | None = None
        self._started_at = datetime.now()

    def run(self) -> None:
        shorts_logger = logging.getLogger("docu_studio.shorts")
        handler = QueueLoggingHandler(self.event_queue)
        prev_level = shorts_logger.level
        shorts_logger.addHandler(handler)
        shorts_logger.setLevel(logging.INFO)
        try:
            self._execute()
        except Exception as exc:
            self.event_queue.put(ErrorEvent(message=str(exc), fatal=True))
            self._status = ShortsRunStatus.FAILED
        finally:
            shorts_logger.removeHandler(handler)
            shorts_logger.setLevel(prev_level)
            self._save_history()
            self.event_queue.close_log()  # flush log before sentinel
            self.event_queue.put(None)

    def _execute(self) -> None:
        if self._cancelled():
            return
        self._project_folder = create_project_folder(
            self.config.topic, self._started_at, self.output_base
        )
        self.event_queue.open_log(
            self._project_folder / "shorts_log.txt", self._sensitive_keys
        )
        ffmpeg = ShortsFFmpeg()

        self.event_queue.put(ProgressEvent(
            stage="Short Script", message=f"Writing short script for '{self.config.topic}'…",
        ))
        script = generate_shorts_script(
            self.config.topic, self.config.duration_seconds, self.llm,
            tts_provider=self._tts_provider, tts_voice=self._tts_voice,
        )
        (self._project_folder / "script.md").write_text(script.text, encoding="utf-8")
        self.event_queue.put(LogEvent(
            message=f"Short script generated ({len(script.text.split())} words, "
                    f"{len(script.sentences)} sentences)",
            level=LogLevel.INFO,
        ))
        if self._cancelled():
            return

        self.event_queue.put(ProgressEvent(
            stage="Short TTS",
            message=f"Synthesizing voiceover ({len(script.sentences)} sentences)…",
        ))
        audio_path = str(self._project_folder / "audio" / "short.mp3")
        self._synthesize_voiceover(script.sentences, audio_path)
        audio_duration = ffmpeg.get_duration(audio_path)
        self.event_queue.put(LogEvent(message=f"Voiceover: {audio_duration:.2f}s", level=LogLevel.INFO))
        measured_wpm = record_measurement(
            self._tts_provider, self._tts_voice,
            len(script.text.split()), audio_duration,
        )
        if measured_wpm:
            self.event_queue.put(LogEvent(
                message=f"Measured TTS pace: {measured_wpm:.1f} WPM (provider={self._tts_provider or '?'} "
                        f"voice={self._tts_voice or '?'})",
                level=LogLevel.INFO,
            ))
        if self._cancelled():
            return

        self.event_queue.put(ProgressEvent(
            stage="Short Alignment", message="Resolving word-level timing…",
        ))
        timestamps, tier_used = get_word_timestamps(audio_path, script.text, self.tts)
        self.event_queue.put(LogEvent(message=f"Word timing resolver: {tier_used}", level=LogLevel.INFO))
        if self._cancelled():
            return

        output_path = self._project_folder / "short_final.mp4"
        assemble_short(
            script=script,
            audio_path=audio_path,
            audio_duration=audio_duration,
            timestamps=timestamps,
            tier_used=tier_used,
            providers=self.footage_providers,
            ffmpeg=ffmpeg,
            project_folder=self._project_folder,
            output_path=output_path,
            seed=self._seed,
            event_queue=self.event_queue,
            captions_enabled=self.config.captions_enabled,
            music_enabled=self.config.music_enabled,
            music_provider=self._music_provider,
            jamendo_client_id=self._jamendo_client_id,
            beat_sync_enabled=self.config.beat_sync_enabled,
            speed_ramp_enabled=self.config.speed_ramp_enabled,
            punch_enabled=self.config.punch_enabled,
            loop_revisit_enabled=self.config.loop_revisit_enabled,
            output_dimensions=self.config.output_dimensions,
        )
        if self._cancelled():
            return

        self._final_video_path = output_path
        self._status = ShortsRunStatus.COMPLETED
        actual_duration = ffmpeg.get_duration(str(output_path))
        self.event_queue.put(ProgressEvent(
            stage="Done",
            message=(
                f"Short completed: {actual_duration:.1f}s actual vs "
                f"{self.config.duration_seconds}s requested."
            ),
        ))

    def _synthesize_voiceover(self, sentences: list[str], audio_path: str) -> None:
        """Dispatch to the per-provider synthesis strategy: gTTS stays fully
        sequential (concurrent load is a plausible way to worsen its own
        documented flakiness, not help it — Task 4 Section 1); ElevenLabs
        uses cap-1 bounded concurrency (functionally sequential, but through
        the same mechanism Deepgram uses, so a future tier-adaptive cap
        wouldn't need a new code path); Deepgram uses cap-2 (confirmed
        margin against its documented rate limits)."""
        work_dir = self._project_folder / "audio"
        provider = (self._tts_provider or "").lower()
        if provider == "elevenlabs":
            synthesize_sentences_concurrent(
                self.tts, sentences, work_dir, audio_path,
                _ELEVENLABS_JOIN_PARAMS, max_concurrency=_ELEVENLABS_MAX_CONCURRENCY,
            )
        elif provider == "deepgram":
            synthesize_sentences_concurrent(
                self.tts, sentences, work_dir, audio_path,
                _DEEPGRAM_JOIN_PARAMS, max_concurrency=_DEEPGRAM_MAX_CONCURRENCY,
            )
        else:
            synthesize_sentences_sequential(self.tts, sentences, work_dir, audio_path, _GTTS_JOIN_PARAMS)

    def _cancelled(self) -> bool:
        if self.cancel_event.is_set():
            self._status = ShortsRunStatus.CANCELLED
            self.event_queue.put(ProgressEvent(stage="Cancelled", message="Run cancelled by user."))
            return True
        return False

    def _save_history(self) -> None:
        try:
            record = RunRecord(
                topic=self.config.topic,
                mode="shorts",
                status=self._status.value,
                started_at=self._started_at,
                project_folder=self._project_folder or self.output_base,
                topic_source="user_supplied",
                fallback_triggered=False,
            )
            save_run(record)
        except Exception:
            pass  # history failure must never crash the runner
