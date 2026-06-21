<!-- SPECKIT START -->
Active feature: **Documentary Pre-Production Studio** (`001-docu-preprod-studio`)

Key files:
- Plan: `specs/001-docu-preprod-studio/plan.md`
- Spec: `specs/001-docu-preprod-studio/spec.md`
- Research: `specs/001-docu-preprod-studio/research.md`
- Data model: `specs/001-docu-preprod-studio/data-model.md`
- Provider contracts: `specs/001-docu-preprod-studio/contracts/provider-interfaces.md`
- Dev setup: `specs/001-docu-preprod-studio/quickstart.md`

Stack: Python 3.11+, CustomTkinter, PyInstaller, Anthropic SDK, edge-tts, ElevenLabs,
Pexels API, Pixabay API, imageio-ffmpeg, keyring, requests.

Source package: `docu_studio/` (see plan.md for full directory tree).
Tests: `tests/unit/` (no network) + `tests/integration/` (HTTP-mocked).
<!-- SPECKIT END -->
