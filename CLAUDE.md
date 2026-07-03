Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---
**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
---

## Project: Documentary Pre-Production Studio

Source package: `docu_studio/` — entry point `docu_studio/__main__.py` →
`docu_studio/gui/webview_app.py`.
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
