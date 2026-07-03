# CLAUDE.md
Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.
**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding
**Don't assume. Don't hide confusion. Surface tradeoffs.**
Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First
**Minimum code that solves the problem. Nothing speculative.**
- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.
Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes
**Touch only what you must. Clean up only your own mess.**
When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.
When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.
The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution
**Define success criteria. Loop until verified.**
Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"
For multi-step tasks, state a brief plan:

[Step] → verify: [check]
[Step] → verify: [check]
[Step] → verify: [check]

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---
**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
---

## Project: Documentary Pre-Production Studio

Source package: `docu_studio/` — entry point `docu_studio/__main__.py` →
`docu_studio/gui/webview_app.py`.

```
docu_studio/
├── __main__.py          entry point
├── platform_layer.py
├── licensing.py
├── retry.py
├── adapters/
│   ├── llm/             anthropic, openai, openrouter, groq (+ base, factory)
│   ├── tts/             gtts (default), elevenlabs, deepgram (+ base, factory)
│   ├── footage/         pexels, pixabay, coverr (+ base, factory)
│   └── topic_discovery/
├── config/              settings.py, defaults.py, key_cache.py
├── gui/
│   ├── webview_app.py   active pywebview entry point
│   ├── bridge.py
│   └── app.py, screens/, widgets/, theme.py, tokens.py   (dead CustomTkinter code)
├── history/             run_history.py
├── media/               ffmpeg_wrapper.py, fcpxml_generator.py
├── output/              project_folder.py
└── pipeline/
    ├── runner.py, events.py
    └── stages/          topic_discovery, script_gen, scene_break, keyword_extract,
                          tts_gen, footage_assembly, final_merge, fcpxml_export
```

Stack: Python 3.11+, pywebview (Qt5/QtWebEngine backend), PyInstaller,
Anthropic/OpenAI/OpenRouter/Groq SDKs, gTTS (default TTS)/ElevenLabs/
Deepgram, Pexels/Pixabay/Coverr APIs, imageio-ffmpeg, keyring, requests.
Tests: `tests/unit/` (no network) + `tests/integration/` (HTTP-mocked).
Run command: `DISPLAY=:1 .venv/bin/python -m docu_studio`
Correct venv: `.venv/` — never `venv/`.
Do not touch `pipeline/`, `runner/`, `adapters/` (except adding new ones),
`history/`, `licensing.py`, or test files unless specifically fixing a bug
in them.
The old CustomTkinter GUI files (`gui/app.py`, `gui/screens/`,
`gui/widgets/`, `gui/theme.py`, `gui/tokens.py`) are dead code — do not
modify or reference them.
