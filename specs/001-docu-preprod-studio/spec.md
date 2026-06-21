# Feature Specification: Documentary Pre-Production Studio

**Feature Branch**: `001-docu-preprod-studio`

**Created**: 2026-06-22

**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Guided Mode End-to-End Run (Priority: P1)

A documentarian provides a topic (e.g., "The Apollo 11 mission") and a target duration of
35 minutes. The app generates a complete script, breaks it into scenes, creates per-scene
voice-over audio, finds and trims matching stock footage for each scene, assembles a synced
timeline, and exports an FCPXML project file ready to open in Filmora. The user watches
real-time progress throughout and receives a self-contained project folder with all
generated assets when the run completes.

**Why this priority**: This is the core product flow. Everything else builds on it.
A working Guided Mode run is the definition of MVP.

**Independent Test**: User enters a topic and duration, starts a run, and receives a
complete project folder containing script, scene breakdown, per-scene audio files,
per-scene video files, an FCPXML timeline, and a run log — with no manual intervention
required between stages.

**Acceptance Scenarios**:

1. **Given** the user has configured at least one LLM, TTS, and stock footage provider,
   **When** the user enters "The Apollo 11 mission" and 20 minutes and starts a run,
   **Then** the app generates a script, breaks it into scenes, produces per-scene audio,
   retrieves and trims matching footage, assembles a timeline, and saves an FCPXML file,
   all without user intervention.
2. **Given** a run is in progress, **When** any stage completes or fails,
   **Then** the GUI updates in real time to show the current stage, scene number, and any
   error — and the app does not crash or silently continue with bad data.
3. **Given** a completed run, **When** the user opens the project folder,
   **Then** it contains: full script text, scene breakdown data, one audio file per scene,
   one synced video file per scene, an FCPXML timeline file, and a run log.
4. **Given** a completed FCPXML export, **When** the file is imported into Filmora,
   **Then** Filmora loads all scenes in correct sequence with scene titles as markers,
   referencing the correct per-scene audio and video files.

---

### User Story 2 - Full Automation Mode (Priority: P2)

A user wants to create a documentary but has no topic in mind. They select Full Automation
Mode, enter only a target duration, and let the app discover a currently trending and
relevant documentary subject via live web search before proceeding through the same pipeline
as Guided Mode.

**Why this priority**: Automation Mode differentiates the product. It is buildable on
top of the Guided Mode pipeline once that core is solid.

**Independent Test**: User selects Full Automation Mode, enters a duration, starts a run.
The run log and final output clearly state the discovered topic and whether it came from
a web search or from AI suggestion (fallback). The pipeline then completes as in US1.

**Acceptance Scenarios**:

1. **Given** the user selects Full Automation Mode and web search is available,
   **When** the run starts, **Then** the app searches for a currently trending/relevant
   topic, displays the discovered topic to the user before proceeding, and uses that topic
   for the full pipeline.
2. **Given** the user selects Full Automation Mode and web search fails or returns no
   usable result, **When** the run starts, **Then** the app falls back to an AI-generated
   topic suggestion, clearly labels it "AI-suggested topic (search unavailable)" in both
   the GUI and the run log, and continues the pipeline without stopping.
3. **Given** a completed Full Automation run, **When** the user reviews the run log,
   **Then** the log states the topic, its source (web search or AI fallback), and any
   fallback triggers that occurred.

---

### User Story 3 - Per-Scene Footage Shortage Handling (Priority: P3)

During a run, stock footage for a given scene is insufficient to cover the scene's audio
duration — no additional clips can be found. The app flags the shortage clearly in the GUI
and run log without silently looping, creating a gap, or crashing, and proceeds with
remaining scenes.

**Why this priority**: Partial failures are expected in production use and must degrade
gracefully rather than silently corrupt output. This is a mandatory failure mode, not an
edge case, but it is dependent on the core pipeline (US1).

**Independent Test**: Simulate a scene where search returns only clips shorter than the
audio duration and no additional clips can be sourced. Verify the GUI shows a footage-
shortage warning for that scene, the run log records the shortage, and all other scenes
complete normally.

**Acceptance Scenarios**:

1. **Given** a scene whose audio duration cannot be covered by available footage,
   **When** the app exhausts search options for that scene, **Then** it flags the scene
   in the GUI with a human-readable shortage message and records the shortage in the log.
2. **Given** a footage shortage flag on a scene, **When** the run completes,
   **Then** remaining scenes are unaffected and still complete normally.
3. **Given** the exported project after a partial run, **When** the user reviews the run
   log, **Then** it lists every scene that had a footage shortage so the user knows which
   scenes require manual footage substitution in Filmora.

---

### User Story 4 - Settings Configuration (Priority: P4)

A non-technical user opens the Settings screen and configures API keys, selects providers,
changes the output folder, and adjusts the narration pace — all without touching any file
or command line.

**Why this priority**: Settings are a prerequisite for any run but are a distinct surface.
They can be built and verified independently before the pipeline is complete.

**Independent Test**: Open Settings screen, enter API keys for all supported providers,
switch TTS provider, toggle a stock footage provider off, change output folder, save.
Restart the app and verify all settings persist.

**Acceptance Scenarios**:

1. **Given** the user opens the Settings screen, **When** they enter and save an API key,
   **Then** the key is stored securely (never written to a plaintext file) and the field
   is masked on screen.
2. **Given** the Settings screen, **When** the user selects a different TTS provider
   from a list of at least two options, **Then** subsequent runs use that provider.
3. **Given** the Settings screen, **When** the user toggles a stock footage provider
   off, **Then** that provider is not queried in subsequent runs.
4. **Given** the user changes the output folder, **When** the next run completes,
   **Then** the project folder is created inside the newly configured location.
5. **Given** the user changes the narration pace (words per minute), **When** the next
   run generates a script, **Then** script length is estimated using the updated pace.

---

### Edge Cases

- What happens when the LLM returns a script that is significantly shorter or longer than
  the word-count estimate for the target duration?
- What happens when a TTS API call fails mid-run (e.g., after 3 of 8 scenes are done)?
- What happens when a stock footage search returns zero results for a scene?
- What happens when the user cancels a run that is already in progress? *(Resolved: see Clarifications)*
- What happens when the output folder does not exist or is not writable?
- What happens when the FCPXML export fails after all media files have been generated?
- What happens when web search for trending topics returns results in a language other
  than the user's expected output language?

## Requirements *(mandatory)*

### Functional Requirements

**Mode Selection**

- **FR-001**: Users MUST be able to select between Guided Mode and Full Automation Mode
  before starting a run.
- **FR-002**: In Guided Mode, users MUST be able to enter a free-text topic and a target
  duration in minutes.
- **FR-003**: In Full Automation Mode, users MUST only need to enter a target duration in
  minutes; the app discovers the topic autonomously.

**Topic Discovery (Full Automation Mode)**

- **FR-004**: The app MUST perform a live web search to find a currently trending and
  relevant documentary topic when Full Automation Mode is selected.
- **FR-005**: If web search fails or returns no usable result, the app MUST fall back to
  an AI-generated topic suggestion without stopping the run.
- **FR-006**: The app MUST clearly label in both the GUI and run log whether the topic
  was search-derived or AI-suggested (fallback).

**Pipeline — Script Generation**

- **FR-007**: The app MUST generate a full documentary script estimated to match the target
  duration using a configurable words-per-minute narration pace.

**Pipeline — Scene Breakdown**

- **FR-008**: The app MUST break the script into discrete scenes, each with a short title
  and the narration text belonging to that scene.

**Pipeline — Voice-Over Generation**

- **FR-009**: The app MUST generate voice-over audio for each scene individually, producing
  one audio file per scene with a measurable duration.

**Pipeline — Visual Keyword Extraction**

- **FR-010**: For each scene, the app MUST extract visual search keywords describing what
  should appear on screen during that scene's narration.

**Pipeline — Stock Footage Search**

- **FR-011**: For each scene, the app MUST search stock footage using the extracted keywords.
- **FR-012**: If a found clip is longer than the scene audio, the app MUST trim it to
  match the audio duration exactly.
- **FR-013**: If a found clip is shorter than the scene audio, the app MUST fetch
  additional clips with the same or related keywords and concatenate them until the combined
  video duration equals the audio duration, trimming the final clip exactly to land on the
  audio end point.
- **FR-014**: If no further footage can be found to cover a scene's audio duration, the
  app MUST flag this clearly to the user in the GUI and run log rather than silently loop,
  create a gap, or crash.

**Pipeline — Timeline & Export**

- **FR-015**: The app MUST generate a timeline with accurate timestamps for every scene in
  correct sequence.
- **FR-016**: The app MUST export an FCPXML project file referencing the per-scene synced
  video and audio files, with scene titles as markers, importable into Filmora.

**Output Project Folder**

- **FR-017**: Each completed run MUST produce a self-contained project folder containing:
  the full script, scene breakdown data, every per-scene audio file, every per-scene synced
  video file, the FCPXML timeline file, and a run log.
- **FR-018**: The run log MUST record what happened during generation, including any
  fallbacks triggered (topic-search fallback, footage-shortage flags, API errors).

**Settings**

- **FR-019**: Users MUST be able to configure API keys for every external service through
  a Settings screen, without touching any code or configuration file.
- **FR-020**: API keys MUST be stored using OS-native secure credential storage; they MUST
  NOT be written to plaintext files or logs.
- **FR-021**: Users MUST be able to select which TTS provider to use from at least two
  available options.
- **FR-022**: Users MUST be able to select and toggle which stock footage provider(s) to
  use from multiple available options.
- **FR-023**: Users MUST be able to set the default output folder through the Settings screen.
- **FR-024**: Users MUST be able to set the default narration pace (words per minute) through
  the Settings screen.

**Progress & Error Visibility**

- **FR-025**: The app MUST display real-time progress during a run, showing at minimum the
  current stage name and current scene being processed.
- **FR-031**: Scenes MUST be processed sequentially: each scene's full pipeline (TTS,
  footage search, sync) MUST complete before the next scene begins. Parallel scene
  processing is explicitly out of scope for v1.
- **FR-032**: The app's main screen MUST display a list of past runs, showing at minimum
  the topic, run date/time, status (completed / cancelled / failed), and a link or button
  to open the corresponding project folder in the OS file browser. Run history MUST
  persist across application restarts.
- **FR-033**: When a run fails (all retries exhausted on any stage), all per-scene files
  already written to the project folder MUST be retained. The run log MUST record the
  failure point. Run resume is explicitly out of scope for v1; users start a new run
  to retry.
- **FR-026**: The app MUST display a clear, human-readable error message in the GUI if any
  stage fails after all retries are exhausted (see FR-030), without crashing or silently
  continuing with bad data.
- **FR-030**: For every external API call, the app MUST automatically retry up to 3 times
  using exponential backoff before treating the call as failed. Only after all 3 retries
  fail MUST the error be surfaced to the GUI and recorded in the run log.

**Platform**

- **FR-027**: The application MUST run as a native desktop app on both Windows and macOS
  with identical features and behavior.

**Run Cancellation**

- **FR-029**: The app MUST provide a Cancel button visible during an active run.
  When the user cancels, the run MUST stop immediately; all per-scene files already
  written to the project folder MUST be retained as-is. The project folder MUST NOT
  be deleted on cancellation. The run log MUST record the cancellation point.

**Out of Scope**

- **FR-028**: Licensing, activation, trial limits, login, and hardware-locking are
  explicitly excluded from this feature. A stub placeholder for future license enforcement
  MUST exist but always return "licensed" in v1.

### Key Entities

- **Run**: A single execution of the pipeline. Has a mode (Guided/Full Automation), a
  topic (user-supplied or discovered), a target duration, an output folder, a status
  (completed / cancelled / failed), and a date/time. Runs persist across app restarts
  and are displayed in the main screen history list.
- **Scene**: A discrete segment of a documentary. Has a title, narration text, audio
  duration (measured from generated TTS output), visual keywords, and an assembly of
  footage clips that together match the audio duration.
- **Project Folder**: The self-contained output of a completed run. Contains all per-scene
  media files, the script, the scene breakdown, the FCPXML export, and the run log.
- **Run Log**: A record of all pipeline stages, timings, fallback triggers, footage
  shortages, and errors for a single run.
- **Settings**: Persistent user preferences: provider selections, API keys (stored
  securely), output folder, narration pace.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can complete a full Guided Mode run from topic entry to project folder
  delivery without any manual step between stages.
- **SC-002**: For any run, every scene's video duration equals that scene's audio duration
  to within 50 milliseconds; no scene in the exported FCPXML has a silent gap or video
  overrun.
- **SC-003**: If a run encounters an API failure in any stage, the failure is displayed in
  the GUI within 5 seconds of occurrence and the app remains responsive.
- **SC-004**: All user-configurable values (API keys, provider selection, output folder,
  narration pace) persist correctly across application restarts.
- **SC-005**: The exported FCPXML file opens in Filmora with all scenes in correct sequence,
  scene titles visible as markers, and media files correctly referenced.
- **SC-006**: In Full Automation Mode, the run log unambiguously states whether the topic
  was search-derived or AI-suggested, for every run.
- **SC-007**: A footage shortage (no further clips available for a scene) is reported to
  the user in the GUI and recorded in the run log; the shortage never silently produces a
  gap or looped clip in the output.
- **SC-008**: No API key or credential is ever written to a plaintext file, log file, or
  displayed unmasked in the GUI after initial entry.

## Assumptions

- Users have internet access during runs (required for LLM, TTS, web search, and stock
  footage API calls).
- Users have accounts and API keys for at least one supported LLM provider, one TTS
  provider, and one stock footage provider before starting their first run.
- The app does not perform video editing — it only prepares materials and a pre-built
  timeline. Filmora (already owned by the user) is the final editing environment.
- Filmora supports FCPXML import; the app targets the FCPXML dialect compatible with
  Filmora's importer.
- Per-scene audio duration is the ground truth for scene length; the script word count
  is only an initial estimate for total run time, not a hard constraint on individual scenes.
- "Identical behavior on Windows and macOS" means feature parity and behavioral parity;
  native look-and-feel differences introduced by the OS UI toolkit are acceptable.
- A "usable" web search result for topic discovery means a topic that is clearly a real
  subject suitable for a documentary (not a disambiguation page, an ad, or a malformed
  result).
- Concurrent runs are out of scope for v1; the app supports one active run at a time.
- Run resume (continuing from the last completed scene after failure or cancellation) is
  out of scope for v1; users start a new run to retry. Partial project folder files are
  always retained for manual use in Filmora.

## Clarifications

### Session 2026-06-22

- Q: When the user cancels an active run, what happens to partially generated files? → A: Stop immediately; keep all per-scene files already written to the project folder (partial but usable); do not delete the project folder; record cancellation point in run log.
- Q: When an external API call fails, does the app retry or surface the error immediately? → A: Auto-retry up to 3 times with exponential backoff; surface error to GUI and log only after all 3 retries fail.
- Q: Are scenes processed sequentially or in parallel? → A: Sequential — each scene's full pipeline (TTS, footage, sync) completes before the next begins; parallel processing is out of scope for v1.
- Q: Does the app track and display previous runs, or is it stateless after a run completes? → A: App shows a list of past runs on the main screen (topic, date/time, status, link to project folder); run history persists across restarts.
- Q: Can a failed or cancelled run be resumed from the last completed scene? → A: No resume in v1; user starts a new run; partial project folder files are retained and accessible.
