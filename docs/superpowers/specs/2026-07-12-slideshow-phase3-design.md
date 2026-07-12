# Slideshow Phase 3 — Transitions, Captions, Music (design spec)

Status: approved for planning.
Preceded by: Phase 1 (core assembly), Phase 2 (topic image fetch + LLM script gen).
This is the final polish phase for the Slideshow feature.

## Pre-work findings (done before this design)

**Thumbnail `file://` rendering for filenames with spaces** — investigated and
confirmed **not a real bug**. Repro'd against the actual QtWebEngine/Chromium
engine (offscreen-headless, since on-screen GUI automation crashes this sandboxed
dev environment — see below): assigning `img.src = 'file://' + path` where `path`
contains a literal space causes the browser to auto-normalize the URL to `%20`
before any load attempt (`document.getElementById('thumb').src` read back as
`file:///.../test%20image%20with%20spaces.jpg`). This is standard WHATWG
URL-parsing behavior on `.src` assignment, not something the app's code needs to
handle. No fix applied — `docu_studio/gui/web/app.js` line 241 is unchanged.

**Manual GUI click-through** — still blocked in this environment, and by a wider
margin than Phases 1–2's "synthetic input doesn't reach QtWebEngine" limitation.
Even a bare `pywebview.create_window()` + `webview.start()` against the real
`DISPLAY=:1` crashes the sandboxed bash process outright (no output, exit 144 —
consistent with an OOM-kill on the Chromium subprocess tree). Offscreen-headless
mode works intermittently for trivial test pages but isn't reliable enough to
verify the real app's UI. This still needs the user's own manual click-through;
not re-diagnosed further per standing guidance.

**`docu_studio/config/key_cache.py` genericity** — confirmed genuinely generic.
It's a flat list of API-key usernames (Anthropic, OpenAI, OpenRouter, Groq,
ElevenLabs, Deepgram, Pexels, Pixabay, Coverr, Serper, Jamendo) backed by one
keyring service (`docu_studio`), with no shorts-specific logic. It's only ever
imported by `docu_studio/gui/bridge.py`, and Slideshow's own Phase 2 code already
receives Pexels/Pixabay keys as plain strings via that same path. Reusing it for
Jamendo is consistent with the existing pattern — `slideshow_music.py` itself
never imports `key_cache`; `bridge.py` reads the key and passes it through as a
plain string, exactly as it already does for Pexels/Pixabay.

## Scope

1. Crossfade transitions (alternative to today's hard cut).
2. Optional vignette + film grain overlays.
3. Optional burned-in captions, synced via a freshly-built word-timing estimate
   (Phase 1/2 assembly has no word/sentence timing at all — confirmed by reading
   `slideshow_assembly.py`'s own docstring, which explicitly scopes that out).
4. Optional background music (Jamendo + local-folder providers) with ducking
   under narration.

All four are additive and default off/hard-cut. A run with everything off must
be provably identical in behavior to today's Phase 1/2 output.

## Non-goals (explicitly deferred)

- Pan/rotate/light-leak/color-grade overlays — vignette + grain only, per the
  "keep it subtle, default off" instruction.
- Whisper-based forced alignment for captions — character-weighted duration
  estimate only (Shorts' Tier 3 technique), decided in brainstorming: no new
  runtime dependency or model download for a first pass at slideshow captions.
- A bundled default music folder — local-folder provider requires the user to
  browse to their own folder at run time; no bundled assets, no licensing
  question to resolve.
- Any shared-code extraction with `docu_studio/shorts/` — deferred again, same
  as Phases 1 and 2. Every new module below is self-contained.

## Architecture

Four new modules under `docu_studio/slideshow/`, each mirroring a corresponding
Shorts module's *technique* without importing it:

| New/changed file | Mirrors (technique only) | Purpose |
|---|---|---|
| `slideshow_ffmpeg.py` (+methods) | `shorts_ffmpeg.py` | `concat_segments_with_xfade`, `apply_overlays`, `burn_captions`, `mix_music_bed` |
| `slideshow_captions.py` (new) | `shorts_captions.py` | `WordTiming`, timing estimate, ASS pop-caption generation |
| `slideshow_music.py` (new) | `shorts/music_providers.py` | `LocalFolderMusicProvider`, `JamendoMusicProvider`, fallback resolver |
| `slideshow_audio_mix.py` (new) | `shorts_audio_mix.py` | pure ducking filtergraph string builder |
| `slideshow_config.py` (+fields) | — | new optional config fields, all default to today's behavior |
| `slideshow_assembly.py` (+pipeline steps) | — | wires the above into the existing assemble_slideshow() flow |

### Pipeline order

```
Ken Burns segments (unchanged)
  -> concat: hard cut (unchanged) OR crossfade (new)
  -> overlays: vignette / grain (new, optional)
  -> captions burn-in (new, optional)
  -> mux narration (unchanged) [+ music mixed in first if enabled (new, optional)]
```

Every new ffmpeg output that re-encodes video ends in the same
`_finalize_filter` (`setsar=1,format=yuv420p`) suffix `apply_ken_burns_image`
already uses, so the SAR concat-crash class of bug documented from the Shorts
pipeline cannot slip back in through any of these new paths.

## 1. Transitions

`SlideshowConfig.transition: str = "cut"` (`"cut"` | `"crossfade"`).

`SlideshowFFmpeg.concat_segments_with_xfade(input_paths, durations, transition_duration, output_path)`:
chains ffmpeg's `xfade` filter pairwise across all segments. To keep total output
duration equal to `audio_duration` despite the overlap, interior segment
durations are lengthened by `transition_duration` seconds each (segment N and
N+1 overlap by exactly that amount at the crossfade point) — this changes how
`split_duration_evenly` durations are computed when `transition == "crossfade"`,
not the Ken Burns rendering itself. `transition_duration` default: 0.5s, not
user-configurable in this phase. The chained `xfade` filter output is finalized
through `_finalize_filter` before being handed to the next pipeline stage.

Hard cut path (`concat_segments_video_only`) is untouched.

## 2. Overlays

`SlideshowConfig.vignette: bool = False`, `SlideshowConfig.grain: bool = False`.

`SlideshowFFmpeg.apply_overlays(input_path, output_path, vignette, grain)`: one
combined ffmpeg pass over the concatenated video (post hard-cut or post-crossfade,
whichever ran), applying `vignette` (default angle/strength) and/or
`noise=alls=8:allf=t` (subtle grain) as `-vf` filters, finalized through
`_finalize_filter`. Skipped entirely (no-op, no extra encode) if both are False.

## 3. Captions

`SlideshowConfig.captions: bool = False`.

`slideshow_captions.py`:
- `WordTiming(word: str, start: float, end: float)` — own dataclass, not
  imported from `shorts.capability_resolvers`.
- `estimate_word_timestamps(script_text: str, duration: float) -> list[WordTiming]`
  — character-length-weighted distribution across `duration`, same algorithm as
  `capability_resolvers.estimate_word_timestamps` (Shorts Tier 3), reimplemented
  locally.
- `group_words()` / `generate_ass()` / `write_ass_file()` — ported from
  `shorts_captions.py`'s pop-caption technique (2-4 word chunks, bold+scale on
  the active word, gapless events), but parameterized on Slideshow's actual
  `out_width`/`out_height` (varies by aspect ratio: 1080×1920, 1920×1080, or
  1080×1080) instead of hardcoded Shorts dimensions. Safe-area bottom margin:
  same 22%-of-height convention.

`SlideshowFFmpeg.burn_captions(input_path, ass_path, output_path)`: same
`subtitles=` filter technique as `ShortsFFmpeg.burn_captions`, including the
cwd-relative-filename workaround for the ffmpeg filtergraph parser's `:` handling
(real bug class in the original, worth preserving verbatim).

Applied after overlays, before mux, using `audio_duration` from the TTS step as
the total duration `estimate_word_timestamps` distributes across.

## 4. Music

`SlideshowConfig.music_enabled: bool = False`, `SlideshowConfig.music_provider: str = "jamendo"` (`"jamendo"` | `"local_folder"`), `SlideshowConfig.music_folder: str | None = None`.

`slideshow_music.py`:
- `TrackCandidate` — own dataclass (title, duration, download_url, source, local_path).
- `LocalFolderMusicProvider(folder_path)` — picks a random audio file from a
  user-browsed folder (new GUI "Browse folder…" button, same pattern as
  `browseSlideshowImages()`). `search()` returns `[]` (never raises) when the
  folder doesn't exist, is empty, or contains no files with a recognized audio
  extension (`.mp3`/`.wav`/`.m4a`/`.ogg`) — this flows through
  `resolve_music_track()`'s existing "no candidates -> log and return None"
  branch exactly like Jamendo returning zero results does, so an empty or
  invalid folder skips the music bed gracefully rather than crashing the run,
  whether local-folder is the primary provider or the Jamendo fallback.
- `JamendoMusicProvider(client_id)` — self-contained reimplementation of
  `shorts/music_providers.py`'s search+cache+fetch technique against
  `api.jamendo.com/v3.0/tracks`, own cache dir (`slideshow_music_cache`, kept
  separate from Shorts' `shorts_music_cache`).
- `resolve_music_track(provider_name, mood, max_duration, jamendo_client_id, ...)`
  — walks the configured provider, falls back to local-folder if Jamendo yields
  nothing, then gives up (`None`) without raising — music is always optional.

`slideshow_audio_mix.py`: `build_ducking_filtergraph(video_duration)` — mirrors
`shorts_audio_mix.py`'s sidechaincompress technique verbatim (loop/trim music to
video duration, fade in/out, duck under narration via sidechaincompress keyed on
the voice track, mix with `amix normalize=0` so voice stays dominant). Own
module-level constants, not imported from shorts.

`SlideshowFFmpeg.mix_music_bed(voice_path, music_path, video_duration, output_path)`
uses this filtergraph, same invocation shape as `ShortsFFmpeg.mix_music_bed`.
When music is enabled, this mixed track replaces the raw narration track as the
input to the existing `mux_audio_video` step — that step itself is unchanged.

## GUI

New controls added directly below the existing `slideshow-aspect-row` block in
`index.html`, same Tailwind input/select styling as the aspect-ratio control:

- Transition `<select>`: Hard cut / Crossfade.
- Vignette checkbox, Grain checkbox.
- Captions checkbox.
- Music checkbox + provider `<select>` (Jamendo / Local folder) + a
  "Browse folder…" button shown only when Local folder is selected. The
  provider `<select>` is pre-set by `bridge.py` at screen-render time: Jamendo
  if `key_cache.get("docu_studio_jamendo")` is non-empty, else Local folder —
  the `SlideshowConfig.music_provider` dataclass default of `"jamendo"` is just
  the field's fallback value, not the GUI's presentation logic.

All default to off/hard-cut — a user who touches nothing new gets exactly
today's Phase 1/2 output. `bridge.py`'s slideshow-start handler reads these
fields and threads them into `SlideshowConfig` / `assemble_slideshow()`.

## Testing

Unit tests per new module, same rigor as existing Slideshow tests (HTTP/ffmpeg
mocked or avoided entirely, no network):

- Crossfade segment-duration math and `xfade` filtergraph string construction.
- Overlay filter-string construction (vignette-only, grain-only, both, neither).
- `estimate_word_timestamps` distribution, `group_words` chunking edge cases
  (0/1/n words), ASS document structure.
- Ducking filtergraph string construction.
- Music provider fallback chain (Jamendo empty → local folder → None), local
  folder empty-directory handling.

## Real end-to-end verification (required before sign-off)

- All-on run: crossfade + vignette + grain + captions + music, through the real
  pipeline (real gTTS or real LLM narration, real ffmpeg) to a finished video.
  Extract and personally view frames/segments confirming clean crossfades (no
  SAR artifacts), correctly-timed caption burn-in, audible ducking.
- All-off run: hard cut, no overlays, no captions, no music — confirms Phase 1/2
  behavior is unchanged.

## Baseline

512 passed / 24 failed / 1 error, reconfirmed at the start of this phase
(2026-07-12) — same pre-existing dead-code (CustomTkinter theme/tokens tests)
and missing-module (`edge_tts_adapter`) failures as at the end of Phase 2, all
unrelated to Slideshow.
