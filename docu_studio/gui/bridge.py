"""
Python API class exposed to the pywebview frontend.
All public methods (no underscore) are callable from JS as:
  await window.pywebview.api.method_name(arg)
"""
from __future__ import annotations
import os
import platform
import queue
import subprocess
import threading
from pathlib import Path

import webview

from docu_studio.config import key_cache
from docu_studio.config.settings import Settings


def duration_to_minutes(minutes: int, seconds: int) -> float:
    """Convert a (minutes, seconds) target duration into precise fractional minutes."""
    total = minutes + seconds / 60.0
    if total <= 0:
        raise ValueError("Target duration must be greater than 0 seconds.")
    return total


class Bridge:
    _STAGE_MAP = {
        "script":   0, "scene":    1, "audio":    2,
        "keyword":  3, "footage":  4, "sync":     5,
        "timeline": 6, "fcpxml":   6, "export":   6,
        "merge":    7, "done":     7, "complete": 7,
    }
    _SHORTS_STAGE_MAP = {
        "script": 0, "tts": 1, "alignment": 2, "footage": 3,
        "assembly": 4, "caption": 5, "music": 5,
        "mux": 6, "done": 6, "complete": 6,
    }
    _SLIDESHOW_STAGE_MAP = {
        "tts": 0, "assembly": 1, "mux": 2, "done": 2, "complete": 2,
    }
    _CLIPSTORY_STAGE_MAP = {
        "assembly": 0, "done": 0, "complete": 0,
    }
    _FINAL_STAGE_INDEX_BY_MODE = {"doc": 7, "shorts": 6, "slideshow": 2, "clipstory": 0}

    def __init__(self):
        self._window: webview.Window | None = None
        self._event_q: queue.Queue = queue.Queue()
        self._runner = None
        self._run_thread = None
        self._settings = Settings.load()
        self._active_mode = "doc"

    def set_window(self, w: webview.Window):
        self._window = w

    # ── Settings ──────────────────────────────────────────────────────────

    def get_settings(self) -> dict:
        s = self._settings
        tts_provider = getattr(s, "tts_provider", "") or "gtts"
        if tts_provider in ("edge", "edgetts"):
            tts_provider = "gtts"
        if tts_provider == "deepgram" and not key_cache.get("docu_studio_deepgram_key"):
            tts_provider = "gtts"
        elif tts_provider == "elevenlabs" and not key_cache.get("docu_studio_elevenlabs"):
            tts_provider = "gtts"
        return {
            "llm_provider":     getattr(s, "llm_provider",     "Anthropic"),
            "llm_model":        getattr(s, "llm_model",        "claude-sonnet-4-5"),
            "llm_custom_model": getattr(s, "llm_custom_model", ""),
            "tts_provider":    tts_provider,
            "deepgram_voice":  getattr(s, "deepgram_voice",  "aura-asteria-en"),
            "output_folder":   str(getattr(s, "output_folder", Path.home() / "DocuStudio")),
            "wpm":             int(getattr(s, "narration_wpm", 150)),
            "footage_primary":            getattr(s, "footage_primary",            "pexels"),
            "footage_fallback":           getattr(s, "footage_fallback",           "pixabay"),
            "footage_fallback2":          getattr(s, "footage_fallback2",          "none"),
            "footage_shortage_strategy":  getattr(s, "footage_shortage_strategy",  "loop"),
            "music_provider":  getattr(s, "music_provider", "local"),
            "anthropic_key":   key_cache.get("docu_studio_anthropic"),
            "openai_key":      key_cache.get("docu_studio_openai"),
            "openrouter_key":  key_cache.get("docu_studio_openrouter"),
            "groq_key":        key_cache.get("docu_studio_groq"),
            "elevenlabs_key":  key_cache.get("docu_studio_elevenlabs"),
            "deepgram_key":    key_cache.get("docu_studio_deepgram_key"),
            "pexels_key":      key_cache.get("docu_studio_pexels"),
            "pixabay_key":     key_cache.get("docu_studio_pixabay"),
            "coverr_key":      key_cache.get("docu_studio_coverr"),
            "serper_key":      key_cache.get("docu_studio_serper"),
            "jamendo_key":     key_cache.get("docu_studio_jamendo"),
        }

    def save_settings(self, data: dict) -> dict:
        try:
            s = self._settings
            s.llm_provider     = data.get("llm_provider",     "Anthropic")
            s.llm_model        = data.get("llm_model",        "claude-sonnet-4-5")
            s.llm_custom_model = data.get("llm_custom_model", "")
            s.tts_provider    = data.get("tts_provider",    "elevenlabs")
            s.deepgram_voice  = data.get("deepgram_voice",  "aura-asteria-en")
            s.narration_wpm   = int(data.get("wpm", 150))
            s.footage_primary            = data.get("footage_primary",            "pexels")
            s.footage_fallback           = data.get("footage_fallback",           "pixabay")
            s.footage_fallback2          = data.get("footage_fallback2",          "none")
            s.footage_shortage_strategy  = data.get("footage_shortage_strategy",  "loop")
            s.music_provider  = data.get("music_provider",  "local")
            folder = data.get("output_folder", "")
            if folder:
                s.output_folder = folder
            s.save()
            def _keys():
                for svc, val in {
                    "docu_studio_anthropic":    data.get("anthropic_key",  ""),
                    "docu_studio_openai":       data.get("openai_key",     ""),
                    "docu_studio_openrouter":   data.get("openrouter_key", ""),
                    "docu_studio_groq":         data.get("groq_key",       ""),
                    "docu_studio_elevenlabs":   data.get("elevenlabs_key", ""),
                    "docu_studio_deepgram_key": data.get("deepgram_key",   ""),
                    "docu_studio_pexels":       data.get("pexels_key",     ""),
                    "docu_studio_pixabay":      data.get("pixabay_key",    ""),
                    "docu_studio_coverr":       data.get("coverr_key",     ""),
                    "docu_studio_serper":       data.get("serper_key",     ""),
                    "docu_studio_jamendo":      data.get("jamendo_key",    ""),
                }.items():
                    if val is not None:
                        key_cache.set_key(svc, val)
            threading.Thread(target=_keys, daemon=True).start()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ── Run lifecycle ──────────────────────────────────────────────────────

    def start_run(self, config: dict) -> dict:
        if self._run_thread and self._run_thread.is_alive():
            return {"ok": False, "error": "A run is already in progress"}
        try:
            self._active_mode = "doc"
            from docu_studio.adapters.footage.factory import build_footage_providers
            from docu_studio.adapters.llm.factory import build_llm
            from docu_studio.adapters.tts.factory import build_tts
            from docu_studio.pipeline.runner import PipelineRunner, RunMode

            s = self._settings
            provider = getattr(s, "llm_provider", "Anthropic")
            model    = getattr(s, "llm_model",    "claude-sonnet-4-5")
            key_map  = {
                "Anthropic":  key_cache.get("docu_studio_anthropic"),
                "OpenAI":     key_cache.get("docu_studio_openai"),
                "OpenRouter": key_cache.get("docu_studio_openrouter"),
                "Groq":       key_cache.get("docu_studio_groq"),
            }
            llm_key     = key_map.get(provider, "") or ""
            tts_prov    = getattr(s, "tts_provider", "elevenlabs")
            tts_key     = (
                key_cache.get("docu_studio_elevenlabs")
                if tts_prov == "elevenlabs"
                else key_cache.get("docu_studio_deepgram_key")
            )
            pexels_key  = key_cache.get("docu_studio_pexels")
            pixabay_key = key_cache.get("docu_studio_pixabay")
            coverr_key  = key_cache.get("docu_studio_coverr")

            llm = build_llm(provider, llm_key, model)
            tts = build_tts(
                tts_prov, tts_key or "",
                getattr(s, "deepgram_voice", "aura-asteria-en"),
            )
            footage_list = build_footage_providers(
                getattr(s, "footage_primary",   "pexels"),
                getattr(s, "footage_fallback",  "pixabay"),
                pexels_key  or "",
                pixabay_key or "",
                coverr_key  or "",
                fallback2=getattr(s, "footage_fallback2", "none"),
            )

            while not self._event_q.empty():
                try:
                    self._event_q.get_nowait()
                except queue.Empty:
                    break

            output_base = (
                Path(s.output_folder)
                if getattr(s, "output_folder", None)
                else Path.home() / "DocuStudio"
            )
            mode_str = config.get("mode", "guided")
            duration_minutes = duration_to_minutes(
                int(config.get("duration_minutes", 5)),
                int(config.get("duration_seconds", 0)),
            )
            self._runner = PipelineRunner(
                topic=config.get("topic", ""),
                duration_minutes=duration_minutes,
                mode=RunMode(mode_str),
                llm=llm,
                tts=tts,
                footage_providers=footage_list,
                output_base=output_base,
                topic_source="user_supplied" if mode_str == "guided" else "ai_suggested",
                sensitive_keys=[
                    v for v in [llm_key, tts_key, pexels_key, pixabay_key, coverr_key] if v
                ],
            )

            def _run() -> None:
                try:
                    self._runner.run()
                except Exception as exc:
                    import traceback
                    self._event_q.put({
                        "type": "error",
                        "message": str(exc) + "\n" + traceback.format_exc(),
                    })

            self._run_thread = threading.Thread(target=_run, daemon=True)
            self._run_thread.start()
            threading.Thread(target=self._translate_events, daemon=True).start()
            return {"ok": True}

        except Exception as exc:
            import traceback
            return {"ok": False, "error": str(exc) + "\n" + traceback.format_exc()}

    def start_shorts_run(self, config: dict) -> dict:
        if self._run_thread and self._run_thread.is_alive():
            return {"ok": False, "error": "A run is already in progress"}
        try:
            self._active_mode = "shorts"
            from docu_studio.adapters.footage.factory import build_footage_providers
            from docu_studio.adapters.llm.factory import build_llm
            from docu_studio.adapters.tts.factory import build_tts
            from docu_studio.shorts.shorts_runner import ShortsRunner

            s = self._settings
            provider = getattr(s, "llm_provider", "Anthropic")
            model    = getattr(s, "llm_model",    "claude-sonnet-4-5")
            key_map  = {
                "Anthropic":  key_cache.get("docu_studio_anthropic"),
                "OpenAI":     key_cache.get("docu_studio_openai"),
                "OpenRouter": key_cache.get("docu_studio_openrouter"),
                "Groq":       key_cache.get("docu_studio_groq"),
            }
            llm_key     = key_map.get(provider, "") or ""
            tts_prov    = getattr(s, "tts_provider", "elevenlabs")
            tts_key     = (
                key_cache.get("docu_studio_elevenlabs")
                if tts_prov == "elevenlabs"
                else key_cache.get("docu_studio_deepgram_key")
            )
            pexels_key  = key_cache.get("docu_studio_pexels")
            pixabay_key = key_cache.get("docu_studio_pixabay")
            coverr_key  = key_cache.get("docu_studio_coverr")

            llm = build_llm(provider, llm_key, model)
            tts_voice = getattr(s, "deepgram_voice", "aura-asteria-en")
            tts = build_tts(tts_prov, tts_key or "", tts_voice)
            footage_list = build_footage_providers(
                getattr(s, "footage_primary",   "pexels"),
                getattr(s, "footage_fallback",  "pixabay"),
                pexels_key  or "",
                pixabay_key or "",
                coverr_key  or "",
                fallback2=getattr(s, "footage_fallback2", "none"),
            )

            while not self._event_q.empty():
                try:
                    self._event_q.get_nowait()
                except queue.Empty:
                    break

            output_base = (
                Path(s.output_folder)
                if getattr(s, "output_folder", None)
                else Path.home() / "DocuStudio"
            )
            duration_seconds = int(config.get("duration_seconds", 30))
            captions_enabled = bool(config.get("captions_enabled", True))
            music_enabled = bool(config.get("music_enabled", True))
            beat_sync_enabled = bool(config.get("beat_sync_enabled", True))
            speed_ramp_enabled = bool(config.get("speed_ramp_enabled", True))
            punch_enabled = bool(config.get("punch_enabled", True))
            loop_revisit_enabled = bool(config.get("loop_revisit_enabled", True))
            music_provider = getattr(s, "music_provider", "local")
            jamendo_client_id = key_cache.get("docu_studio_jamendo") or ""

            self._runner = ShortsRunner(
                topic=config.get("topic", ""),
                duration_seconds=duration_seconds,
                llm=llm,
                tts=tts,
                footage_providers=footage_list,
                output_base=output_base,
                captions_enabled=captions_enabled,
                music_enabled=music_enabled,
                sensitive_keys=[
                    v for v in [llm_key, tts_key, pexels_key, pixabay_key, coverr_key,
                                jamendo_client_id] if v
                ],
                tts_provider=tts_prov,
                tts_voice=tts_voice,
                music_provider=music_provider,
                jamendo_client_id=jamendo_client_id,
                beat_sync_enabled=beat_sync_enabled,
                speed_ramp_enabled=speed_ramp_enabled,
                punch_enabled=punch_enabled,
                loop_revisit_enabled=loop_revisit_enabled,
            )

            def _run() -> None:
                try:
                    self._runner.run()
                except Exception as exc:
                    import traceback
                    self._event_q.put({
                        "type": "error",
                        "message": str(exc) + "\n" + traceback.format_exc(),
                    })

            self._run_thread = threading.Thread(target=_run, daemon=True)
            self._run_thread.start()
            threading.Thread(target=self._translate_events, daemon=True).start()
            return {"ok": True}

        except Exception as exc:
            import traceback
            return {"ok": False, "error": str(exc) + "\n" + traceback.format_exc()}

    def start_slideshow_run(self, config: dict) -> dict:
        if self._run_thread and self._run_thread.is_alive():
            return {"ok": False, "error": "A run is already in progress"}
        try:
            self._active_mode = "slideshow"
            from docu_studio.adapters.tts.factory import build_tts
            from docu_studio.slideshow.slideshow_runner import SlideshowRunner

            s = self._settings
            tts_prov = getattr(s, "tts_provider", "elevenlabs")
            tts_key = (
                key_cache.get("docu_studio_elevenlabs")
                if tts_prov == "elevenlabs"
                else key_cache.get("docu_studio_deepgram_key")
            )
            tts_voice = getattr(s, "deepgram_voice", "aura-asteria-en")
            tts = build_tts(tts_prov, tts_key or "", tts_voice)

            while not self._event_q.empty():
                try:
                    self._event_q.get_nowait()
                except queue.Empty:
                    break

            output_base = (
                Path(s.output_folder)
                if getattr(s, "output_folder", None)
                else Path.home() / "DocuStudio"
            )
            jamendo_client_id = key_cache.get("docu_studio_jamendo") or ""

            self._runner = SlideshowRunner(
                script_text=config.get("script_text", ""),
                image_paths=list(config.get("image_paths", [])),
                tts=tts,
                output_base=output_base,
                aspect_ratio=config.get("aspect_ratio", "9:16"),
                transition=config.get("transition", "cut"),
                vignette=bool(config.get("vignette", False)),
                grain=bool(config.get("grain", False)),
                captions=bool(config.get("captions", False)),
                music_enabled=bool(config.get("music_enabled", False)),
                music_provider=config.get("music_provider", "jamendo"),
                music_folder=config.get("music_folder", ""),
                jamendo_client_id=jamendo_client_id,
            )

            def _run() -> None:
                try:
                    self._runner.run()
                except Exception as exc:
                    import traceback
                    self._event_q.put({
                        "type": "error",
                        "message": str(exc) + "\n" + traceback.format_exc(),
                    })

            self._run_thread = threading.Thread(target=_run, daemon=True)
            self._run_thread.start()
            threading.Thread(target=self._translate_events, daemon=True).start()
            return {"ok": True}

        except Exception as exc:
            import traceback
            return {"ok": False, "error": str(exc) + "\n" + traceback.format_exc()}

    def start_clipstory_run(self, config: dict) -> dict:
        if self._run_thread and self._run_thread.is_alive():
            return {"ok": False, "error": "A run is already in progress"}
        try:
            self._active_mode = "clipstory"
            from docu_studio.adapters.tts.factory import build_tts
            from docu_studio.clipstory.clipstory_config import ClipSpec, ClipStoryConfig
            from docu_studio.clipstory.clipstory_runner import ClipStoryRunner

            s = self._settings
            tts_prov = getattr(s, "tts_provider", "elevenlabs")
            tts_key = (
                key_cache.get("docu_studio_elevenlabs")
                if tts_prov == "elevenlabs"
                else key_cache.get("docu_studio_deepgram_key")
            )
            tts_voice = getattr(s, "deepgram_voice", "aura-asteria-en")
            tts = build_tts(tts_prov, tts_key or "", tts_voice)

            while not self._event_q.empty():
                try:
                    self._event_q.get_nowait()
                except queue.Empty:
                    break

            output_base = (
                Path(s.output_folder)
                if getattr(s, "output_folder", None)
                else Path.home() / "DocuStudio"
            )

            clip_specs = [
                ClipSpec(
                    path=c["path"],
                    trim_in=float(c["trim_in"]),
                    trim_out=float(c["trim_out"]),
                    script_text=c.get("script_text", ""),
                    use_llm_generation=bool(c.get("use_llm_generation", False)),
                )
                for c in config.get("clips", [])
            ]
            clipstory_config = ClipStoryConfig(
                topic=config.get("topic", ""),
                clips=clip_specs,
                output_resolution=config.get("output_resolution", "16:9"),
                tts_provider=tts_prov,
                tts_voice=tts_voice,
            )

            self._runner = ClipStoryRunner(config=clipstory_config, tts=tts, output_base=output_base)

            def _run() -> None:
                try:
                    self._runner.run()
                except Exception as exc:
                    import traceback
                    self._event_q.put({
                        "type": "error",
                        "message": str(exc) + "\n" + traceback.format_exc(),
                    })

            self._run_thread = threading.Thread(target=_run, daemon=True)
            self._run_thread.start()
            threading.Thread(target=self._translate_events, daemon=True).start()
            return {"ok": True}

        except Exception as exc:
            import traceback
            return {"ok": False, "error": str(exc) + "\n" + traceback.format_exc()}

    def fetch_slideshow_images(self, topic: str, count: int) -> dict:
        try:
            import tempfile

            from docu_studio.adapters.photos.factory import build_photo_providers
            from docu_studio.slideshow.slideshow_photo_download import fetch_topic_images

            pexels_key = key_cache.get("docu_studio_pexels") or ""
            pixabay_key = key_cache.get("docu_studio_pixabay") or ""
            providers = build_photo_providers(pexels_key, pixabay_key)

            dest_dir = Path(tempfile.mkdtemp(prefix="docu_studio_slideshow_fetch_"))
            paths = fetch_topic_images(topic, int(count), providers, dest_dir)
            message = (
                f"Fetched {len(paths)} of {count} requested images."
                if len(paths) < int(count)
                else f"Fetched {len(paths)} images."
            )
            return {"ok": True, "paths": paths, "message": message}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def generate_slideshow_script(self, topic: str, image_count: int) -> dict:
        try:
            from docu_studio.adapters.llm.factory import build_llm
            from docu_studio.slideshow.slideshow_script_gen import (
                generate_slideshow_script as _generate_slideshow_script,
            )

            s = self._settings
            provider = getattr(s, "llm_provider", "Anthropic")
            model = getattr(s, "llm_model", "claude-sonnet-4-5")
            key_map = {
                "Anthropic": key_cache.get("docu_studio_anthropic"),
                "OpenAI": key_cache.get("docu_studio_openai"),
                "OpenRouter": key_cache.get("docu_studio_openrouter"),
                "Groq": key_cache.get("docu_studio_groq"),
            }
            llm_key = key_map.get(provider, "") or ""
            llm = build_llm(provider, llm_key, model)

            script_text = _generate_slideshow_script(topic, int(image_count), llm)
            return {"ok": True, "script_text": script_text}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def generate_clipstory_narration(self, topic: str, clips: list[dict]) -> dict:
        try:
            from docu_studio.adapters.llm.factory import build_llm
            from docu_studio.clipstory.clipstory_config import ClipSpec
            from docu_studio.clipstory.clipstory_script_gen import (
                CLIPSTORY_DEFAULT_WPM,
                prepare_narration_review,
            )
            from docu_studio.common.tts_calibration import get_wpm

            s = self._settings
            provider = getattr(s, "llm_provider", "Anthropic")
            model = getattr(s, "llm_model", "claude-sonnet-4-5")
            key_map = {
                "Anthropic": key_cache.get("docu_studio_anthropic"),
                "OpenAI": key_cache.get("docu_studio_openai"),
                "OpenRouter": key_cache.get("docu_studio_openrouter"),
                "Groq": key_cache.get("docu_studio_groq"),
            }
            llm_key = key_map.get(provider, "") or ""
            llm = build_llm(provider, llm_key, model)

            tts_prov = getattr(s, "tts_provider", "elevenlabs")
            tts_voice = getattr(s, "deepgram_voice", "aura-asteria-en")
            wpm = get_wpm(tts_prov, tts_voice, default=CLIPSTORY_DEFAULT_WPM)

            clip_specs = [
                ClipSpec(
                    path=c["path"],
                    trim_in=float(c["trim_in"]),
                    trim_out=float(c["trim_out"]),
                    script_text=c.get("script_text", ""),
                    use_llm_generation=bool(c.get("use_llm_generation", False)),
                )
                for c in clips
            ]
            review = prepare_narration_review(topic, clip_specs, llm, wpm)
            return {"ok": True, "review": review}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def cancel_run(self) -> dict:
        if self._runner:
            try:
                self._runner.cancel_event.set()
            except Exception:
                pass
        return {"ok": True}

    def get_events(self) -> list:
        """JS polls this every 300 ms. Returns and clears pending events."""
        events = []
        try:
            while True:
                events.append(self._event_q.get_nowait())
        except queue.Empty:
            pass
        return events

    def get_history(self) -> list:
        try:
            from docu_studio.history.run_history import load_history
            runs = load_history()
            return [
                {
                    "topic":            r.topic,
                    "created_at":       r.started_at.strftime("%Y-%m-%d %H:%M"),
                    "duration_minutes": "?",
                    "status":           r.status,
                    "output_path":      str(r.project_folder),
                }
                for r in reversed(runs[-10:])
            ]
        except Exception:
            return []

    # ── Event translation ──────────────────────────────────────────────────

    def _translate_events(self) -> None:
        runner_q = self._runner.event_queue
        output_path = ""
        had_error = False

        while True:
            try:
                event = runner_q.get(timeout=0.5)
            except queue.Empty:
                if self._run_thread and not self._run_thread.is_alive():
                    break
                continue

            if event is None:
                if not had_error:
                    final_vid = getattr(self._runner, "_final_video_path", None)
                    if final_vid and Path(str(final_vid)).exists():
                        path = str(final_vid)
                    else:
                        path = str(self._runner._project_folder or output_path)
                    self._event_q.put({"type": "complete", "output_path": path})
                break

            js = self._to_js_event(event)
            if js:
                if js.get("type") == "error":
                    had_error = True
                self._event_q.put(js)

            msg = getattr(event, "message", "") or ""
            for part in msg.split():
                if part.startswith("/") or "DocuStudio" in part:
                    output_path = part.strip()

    def _to_js_event(self, event: object) -> dict | None:
        stage_map = (
            self._SHORTS_STAGE_MAP if self._active_mode == "shorts"
            else self._SLIDESHOW_STAGE_MAP if self._active_mode == "slideshow"
            else self._CLIPSTORY_STAGE_MAP if self._active_mode == "clipstory"
            else self._STAGE_MAP
        )
        final_idx = self._FINAL_STAGE_INDEX_BY_MODE.get(self._active_mode, 7)
        cname = type(event).__name__.lower()

        if "log" in cname:
            msg = getattr(event, "message", str(event))
            lower = msg.lower()
            level = "info"
            if any(w in lower for w in ("error", "fail", "exception")):
                level = "error"
            elif "warn" in lower:
                level = "warning"
            elif any(w in lower for w in ("success", "complete", "done", "finished")):
                level = "success"
            for kw, idx in stage_map.items():
                if kw in lower:
                    self._event_q.put({"type": "stage", "index": idx, "state": "active"})
                    break
            return {"type": "log", "message": msg, "level": level}

        elif "progress" in cname:
            stage = (getattr(event, "stage", "") or "").lower()
            if stage == "done":
                return {"type": "stage", "index": final_idx, "state": "complete"}
            if stage == "cancelled":
                return {"type": "error", "message": "Run cancelled by user."}
            state = getattr(event, "state", "active")
            for kw, idx in stage_map.items():
                if kw in stage:
                    return {"type": "stage", "index": idx, "state": state}
            return None

        elif "error" in cname:
            return {"type": "error", "message": getattr(event, "message", str(event))}

        return {"type": "log", "message": str(event), "level": "info"}

    # ── Filesystem ────────────────────────────────────────────────────────

    def browse_folder(self) -> str | None:
        if not self._window:
            return None
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        return result[0] if result else None

    def browse_images(self) -> list[str]:
        if not self._window:
            return []
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=("Image Files (*.jpg;*.jpeg;*.png;*.webp;*.bmp)", "All files (*.*)"),
        )
        return list(result) if result else []

    def browse_videos(self) -> list[str]:
        if not self._window:
            return []
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=("Video Files (*.mp4;*.mov;*.mkv;*.webm;*.avi)", "All files (*.*)"),
        )
        return list(result) if result else []

    def get_clip_metadata(self, paths: list[str]) -> dict:
        try:
            import tempfile

            from docu_studio.clipstory.clipstory_ffmpeg import ClipStoryFFmpeg

            ffmpeg = ClipStoryFFmpeg()
            clips = []
            for path in paths:
                duration = ffmpeg.get_duration(path)
                poster_path = str(Path(tempfile.mkdtemp(prefix="docu_studio_clipstory_poster_")) / "poster.jpg")
                ffmpeg.extract_poster_frame(path, min(1.0, duration / 2), poster_path)
                clips.append({"path": path, "duration": duration, "poster_path": poster_path})
            return {"ok": True, "clips": clips}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_output_folder(self, path: str) -> dict:
        try:
            p = Path(path)
            if p.is_file():
                p = p.parent
            if not p.exists():
                return {"ok": False, "error": "Folder not found"}
            sys_ = platform.system()
            if sys_ == "Windows":
                os.startfile(str(p))
            elif sys_ == "Darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
