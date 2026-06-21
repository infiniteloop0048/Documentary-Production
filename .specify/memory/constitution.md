<!--
SYNC IMPACT REPORT
==================
Version change: (template/unversioned) → 1.0.0
Bump rationale: Initial ratification. First concrete constitution replacing the
  placeholder template. MAJOR baseline established.

Principles defined (8):
  I.    Provider-Agnostic Design
  II.   Configuration-First
  III.  Graceful Degradation
  IV.   Local-First, Secret-Safe
  V.    Deterministic Sync Contract
  VI.   Cross-Platform Parity
  VII.  Observable Pipeline
  VIII. Incremental Phases (Licensing Out of Scope for v1)

Added sections:
  - Core Principles (8 principles)
  - Additional Constraints (architecture boundaries)
  - Development Workflow & Quality Gates
  - Governance (with mandatory pre-implementation compliance check)

Removed sections: none (template placeholders fully replaced)

Templates reviewed for consistency:
  ✅ .specify/templates/plan-template.md  — "Constitution Check" gate derives
       gates from this file; no hardcoded principle list, stays aligned.
  ✅ .specify/templates/spec-template.md  — generic; no constitution-specific
       sections required changes.
  ✅ .specify/templates/tasks-template.md — generic; principle-driven task
       categories (observability, error-handling, config) already expressible.
  ✅ .specify/templates/checklist-template.md — generic; no change required.

Follow-up TODOs: none. RATIFICATION_DATE set to initial adoption (2026-06-22).
-->

# Documentary Pre-Production Studio Constitution

An AI-assisted documentary pre-production desktop application. This constitution
defines the non-negotiable principles every feature MUST satisfy.

## Core Principles

### I. Provider-Agnostic Design

Every external service — LLM, text-to-speech, stock footage, web search, and any
future category — MUST sit behind a swappable interface/adapter.

- Provider-specific code (SDKs, request shapes, auth quirks, response parsing)
  MUST NOT leak outside its adapter module.
- Pipeline orchestration logic MUST depend only on the abstract interface, never
  on a concrete provider.
- Adding a new provider MUST require only a new adapter implementing the existing
  interface; it MUST NOT require touching orchestration code.

**Rationale**: Providers change pricing, quality, and availability. Isolating them
keeps the core stable and makes substitution a localized, low-risk change.

### II. Configuration-First

Nothing about providers, durations, voices, output paths, or any tunable value
MAY be hardcoded.

- Every configurable value MUST live in a Settings layer with sensible defaults.
- The application MUST be fully usable by a non-technical user through the GUI
  alone — no file editing, no command line required for normal operation.

**Rationale**: Hardcoded values force code changes for routine adjustments and
exclude the target non-technical user. Defaults make the app work out of the box.

### III. Graceful Degradation

The pipeline MUST never silently produce a broken or incomplete output file.

- Every external API call MUST have an explicit fallback OR surface a clear,
  human-readable error in the GUI.
- Partial failures MUST be visible to the user, not hidden.
- A run MUST NOT report success when any stage produced incomplete output.

**Rationale**: Silent failures waste the user's time and erode trust. Visible
failure with a clear message is always preferable to a corrupt deliverable.

### IV. Local-First, Secret-Safe

API keys and credentials MUST be stored using OS-native secure credential storage
(Windows Credential Manager / macOS Keychain).

- Secrets MUST NEVER be written to plaintext config files.
- Secrets MUST NEVER be written to logs.
- Secrets MUST NEVER be transmitted anywhere except to their respective provider's
  API over its required transport.

**Rationale**: Plaintext keys are the most common credential-leak vector. OS
keystores provide encryption-at-rest and access control the app cannot match.

### V. Deterministic Sync Contract

For any input combination, the final exported timeline MUST have video duration
exactly equal to audio duration, scene by scene.

- No silent gaps, no overruns, no unexplained mismatches.
- This is a hard invariant verified at export, not a best-effort goal.
- If the invariant cannot be met, export MUST fail with a clear explanation
  (see Principle III) rather than emit a mismatched timeline.

**Rationale**: Audio/video drift is the defining defect of automated video tools.
A guaranteed per-scene equality contract is the product's core promise.

### VI. Cross-Platform Parity

The application MUST present an identical feature set and behavior on Windows and
macOS.

- OS-specific code — filesystem paths, credential storage, ffmpeg binary
  resolution — MUST be isolated behind a single platform layer.
- OS-specific branching MUST NOT be scattered through business logic.

**Rationale**: A single platform abstraction prevents divergent behavior and makes
the supported-OS matrix testable in one place.

### VII. Observable Pipeline

Every stage — script generation, scene breakdown, voice-over, footage search,
sync, export — MUST report progress, timing, and errors.

- Reporting MUST go to BOTH a persistent log file AND the GUI in real time.
- Logs MUST exclude secrets (see Principle IV).

**Rationale**: Long-running multi-stage pipelines are opaque without observability.
Real-time feedback plus persistent logs make progress legible and failures
diagnosable after the fact.

### VIII. Incremental Phases (Licensing Out of Scope for v1)

Licensing/activation is explicitly OUT OF SCOPE for v1.

- v1 MUST be a fully working local tool with no license gate.
- A single stub function `check_license() -> bool` MUST exist and MUST always
  return `True` in v1, marking the exact insertion point for Phase 2 enforcement.
- The architecture MUST be structured so Phase 2 license enforcement can be added
  at that stub without reworking the pipeline or GUI.

**Rationale**: Deferring licensing avoids over-engineering v1 while reserving a
clean, pre-agreed seam so the later phase is an insertion, not a rewrite.

## Additional Constraints

These architectural boundaries make the principles enforceable:

- **Adapter boundary**: Each external-service category exposes exactly one
  interface; concrete providers live in dedicated adapter modules and are the
  only code permitted to import provider SDKs.
- **Settings boundary**: A single Settings layer is the only source of
  configurable values; business logic reads configuration through it, never from
  literals or scattered environment access.
- **Platform boundary**: A single platform layer owns all OS-conditional logic
  (paths, keystore access, ffmpeg resolution).
- **Export gate**: The deterministic sync contract (Principle V) is enforced by a
  validation step that runs before any file is written.

## Development Workflow & Quality Gates

- **Pre-implementation compliance check (MANDATORY)**: Before implementation of
  any feature begins, the proposing plan MUST be checked against all eight Core
  Principles. Each principle is either satisfied or carries a documented,
  justified exception. Work MUST NOT start until this check passes.
- **Plan gate**: The `Constitution Check` section of every implementation plan
  MUST enumerate how the feature complies with each principle it touches.
- **Review gate**: Code review MUST verify that no provider code leaked past an
  adapter, no configurable value was hardcoded, no secret reached logs or
  plaintext, and no OS-specific code escaped the platform layer.
- **Export verification**: Any change affecting timeline assembly MUST demonstrate
  the per-scene duration equality invariant still holds.

## Governance

This constitution supersedes other development practices for this project. Where a
practice conflicts with a principle here, this document wins.

- **Pre-implementation requirement**: All future features MUST be checked against
  these principles before implementation begins. A feature that violates a
  principle MUST be redesigned to comply, or the violation MUST be explicitly
  justified and recorded in the plan's Complexity Tracking section before any code
  is written. Unjustified violations block the work.
- **Amendments**: Changes to this constitution MUST be documented with a rationale,
  a version bump per the policy below, and propagation to dependent templates and
  guidance docs.
- **Versioning policy** (semantic):
  - **MAJOR**: Backward-incompatible governance changes or principle
    removals/redefinitions.
  - **MINOR**: A new principle/section added, or material expansion of guidance.
  - **PATCH**: Clarifications, wording, and non-semantic refinements.
- **Compliance review**: Plan review and code review are the enforcement points.
  Reviewers MUST confirm principle compliance before approval.

**Version**: 1.0.0 | **Ratified**: 2026-06-22 | **Last Amended**: 2026-06-22
