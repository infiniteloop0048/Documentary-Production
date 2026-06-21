# Developer Quickstart: Documentary Pre-Production Studio

**Date**: 2026-06-22 | **Plan**: [plan.md](plan.md)

---

## Prerequisites

- Python 3.11+
- Git
- (macOS only) Xcode Command Line Tools: `xcode-select --install`
- (Windows only) Microsoft C++ Build Tools (for any packages with C extensions)

---

## Setup

```bash
# Clone and enter repo
git clone <repo-url>
cd <repo-dir>

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
.venv\Scripts\Activate.ps1       # Windows PowerShell

# Install runtime dependencies
pip install -r requirements.txt

# Install dev dependencies
pip install -r requirements-dev.txt

# Install the package in editable mode
pip install -e .
```

---

## Running the App

```bash
python -m docu_studio
```

On first launch, the Settings screen opens automatically when no API keys are configured.

---

## Configuring API Keys (Dev)

Open Settings in the GUI, or use Python directly for headless dev:

```python
import keyring
keyring.set_password("docu_studio", "anthropic",  "sk-ant-...")
keyring.set_password("docu_studio", "serper",     "your-serper-key")
keyring.set_password("docu_studio", "pexels",     "your-pexels-key")
keyring.set_password("docu_studio", "pixabay",    "your-pixabay-key")
# ElevenLabs is optional
keyring.set_password("docu_studio", "elevenlabs", "your-elevenlabs-key")
```

---

## Running Tests

```bash
# All tests
pytest

# Unit tests only (no network; fast)
pytest tests/unit/

# Integration tests (HTTP-mocked; still no real network)
pytest tests/integration/

# With coverage report
pytest --cov=docu_studio --cov-report=term-missing

# Run a specific test file
pytest tests/unit/test_fcpxml_generator.py -v
```

**Coverage requirement**: 80%+ (enforced in CI).

---

## Project Structure (Quick Reference)

```text
docu_studio/
├── __main__.py              # Entry point
├── licensing.py             # check_license() stub
├── platform_layer.py        # config_dir(), ffmpeg_exe(), ffprobe_exe()
├── retry.py                 # @retry decorator
├── config/                  # Settings dataclass + defaults
├── adapters/
│   ├── llm/                 # LLMProvider ABC + AnthropicAdapter
│   ├── topic_discovery/     # TopicDiscoveryProvider ABC + SerperAdapter
│   ├── tts/                 # TTSProvider ABC + EdgeTTSAdapter + ElevenLabsAdapter
│   └── footage/             # FootageProvider ABC + PexelsAdapter + PixabayAdapter
├── pipeline/
│   ├── events.py            # ProgressEvent, LogEvent, ErrorEvent
│   ├── runner.py            # PipelineRunner(Thread)
│   └── stages/              # One module per pipeline stage
├── media/
│   ├── ffmpeg_wrapper.py    # FFmpegWrapper (subprocess + imageio-ffmpeg)
│   └── fcpxml_generator.py  # Pure FCPXML generation + sync gate
├── history/                 # RunRecord, load_history(), save_run()
├── output/                  # create_project_folder()
└── gui/
    ├── app.py               # DocsStudioApp(CTk) + queue poll
    └── screens/             # main, run_config, progress, settings

tests/
├── unit/                    # No network; subprocess mocked
└── integration/             # HTTP-mocked via `responses` library
```

---

## Building Distributable Executables

**IMPORTANT**: Build on each target OS natively. No cross-compilation.

### Windows (.exe)

Run on a Windows machine:

```powershell
pip install pyinstaller
pyinstaller build/windows/docu_studio.spec
# Output: dist/DocsStudio.exe
```

### macOS (.app / .dmg)

Run on a macOS machine:

```bash
pip install pyinstaller
pyinstaller build/macos/docu_studio.spec
# Output: dist/DocsStudio.app
# For DMG (optional):
hdiutil create -volname DocsStudio -srcfolder dist/DocsStudio.app -ov -format UDZO dist/DocsStudio.dmg
```

### What's included in the bundle

- All `docu_studio` package code
- `imageio-ffmpeg` bundled FFmpeg binary (correct binary per OS, added via PyInstaller `datas`)
- All runtime dependencies from `requirements.txt`

---

## Adding a New Provider

### New FootageProvider (example: Storyblocks)

1. Create `docu_studio/adapters/footage/storyblocks_adapter.py`
2. Implement `FootageProvider` ABC — `search(keywords, min_duration) -> List[FootageClip]`
3. Add `"storyblocks"` to the provider registry in `config/defaults.py`
4. Add the new keyring key name to `Settings`
5. Add a toggle checkbox to `gui/screens/settings_screen.py`
6. Write integration test in `tests/integration/test_storyblocks_adapter.py`
7. Zero changes to `pipeline/`, `media/`, or other adapters

### New TTSProvider

Follow same pattern: implement `TTSProvider` ABC, register in `config/defaults.py`,
add radio option to Settings screen.

---

## Common Dev Tasks

```bash
# Check types (if mypy configured)
mypy docu_studio/

# Lint
ruff check docu_studio/ tests/

# Format
ruff format docu_studio/ tests/

# Check that FFmpeg binary is found
python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"

# Verify keyring is working
python -c "import keyring; keyring.set_password('test', 'test', 'ok'); print(keyring.get_password('test', 'test'))"
```

---

## Key Design Rules (reminder)

- Pipeline code (`pipeline/`) imports only ABCs from `adapters/*/base.py`
- OS branches live only in `platform_layer.py`
- API keys never reach log strings — sanitize before passing to `LogEvent.message`
- `validate_sync()` runs before `generate_fcpxml()` — never skip this
- `check_license()` in `licensing.py` always returns `True` — Phase 2 insertion point
