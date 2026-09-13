# EDMG Studio Professional DAW Implementation Blueprint

## 1. Purpose

This document consolidates the Professional DAW work completed in EDMG Studio, the architecture and safety decisions made during that work, and the planned implementation sequence through Phase 13.

The authoritative roadmap is `C:\Scripts\EDMG_Studio_Master_Blueprint_AI_DAW_Timeline.md`. Its Professional DAW phases 0-13 are separate from the 14-item WinUI Native Experience roadmap. The Studio desktop UI under `studio/edmg-studio-winui/` remains the primary user surface; backend capabilities are not considered complete until users can drive them from the Studio UI where applicable.

## 2. Delivery Rules

1. Work on phases in dependency order.
2. Preserve working behavior and compatibility unless an explicit migration replaces it.
3. Validate each phase before closing its gate.
4. Commit and push each phase to the default `codex/Unified` branch before beginning the next phase.
5. Do not mix unrelated local changes into a phase commit.
6. Keep project, timeline, mixer, and render logic out of page code-behind where practical.
7. Keep AI providers and renderers behind normalized interfaces.
8. Keep real-time audio processing isolated from UI, AI, network, filesystem, allocation-heavy, and blocking work.
9. Preserve extension data and support existing project documents through compatible readers or explicit migrations.
10. Never remove legacy renderer paths until the replacement passes its acceptance tests.
11. Do not claim hardware, plugin, model, or renderer readiness from installation alone; readiness must come from capability checks and runtime validation.
12. Do not claim native VST3 processing until a real host implementation passes scan, load, process, state, latency, and crash-isolation tests.

## 3. Required Regression Set

Architecture changes must retain the behavior documented in:

- `studio/edmg-studio-winui/ChatLog3.md`
- `studio/edmg-studio-winui/ChatLog4.md`
- `C:\Users\user\Downloads\ChatLog5.md`
- `C:\Scripts\EDMG_Studio_Master_Blueprint_AI_DAW_Timeline.md`

The two external records are workstation references and must not become build-time dependencies.

Every relevant phase must preserve and test:

- Director-to-Reactive Lab shared draft recovery
- reviewed camera and motion keyframe persistence
- render-profile compatibility
- backend schema importability and migrations
- WinUI XAML page compilation
- existing provider and local-renderer behavior
- safe project revision and undo/redo semantics

## 4. Repository and Branch State

- Repository: `DWCTEDMG/DWCTGenerativeSoundStudio`
- Default working branch: `codex/Unified`
- Current synchronized head when this plan was written: `ce1b52b`
- Local `HEAD`, `origin/codex/Unified`, and `origin/HEAD` matched at that revision.
- The worktree was clean when this plan was created.

Relevant pushed commits:

| Commit | Description | Phase relationship |
| --- | --- | --- |
| `a5ebae7` | Complete Phase 1 shared core contracts | Phase 1 gate |
| `5c46692` | Complete Phase 2 timeline core | Phase 2 gate |
| `936f3aa` | Complete provider, media, and audio foundations | Contains Phase 3 and Phase 4 foundations plus other concurrent work |
| `ce1b52b` | Complete provider refactor | Strong Phase 11 foundation; final phase acceptance still requires ordered audit |
| `63eee21` | Harden Hunyuan render completion | Phase 8 foundation |
| `0997efc` | Complete LTX renderer integration | Phase 9 foundation |
| `4e0bdca` | Complete Director Review workflow | Phase 10 foundation |

The user requested one commit and push per phase. Phase 3 and Phase 4 were combined in the already-pushed `936f3aa` commit by concurrent work. The shared default branch will not be rewritten to manufacture separate historical commits. Both phase gates must instead be recorded against that immutable commit and its validation evidence. Future phases must return to one phase per commit.

## 5. Current Architecture

### 5.1 Project and timeline core

- Canonical C# contracts represent projects, ordered tracks, timeline events, media assets, exact sample positions, markers, provenance, and extension metadata.
- Timeline persistence reads compatible media pools from metadata and timeline documents and writes the canonical timeline representation.
- Backend editor commands provide revision-aware edits, transaction boundaries, undo/redo, idempotency, and locked-object validation.
- WinUI timeline presentation is separated from core timeline operations, snapping, viewport state, and command/history models.
- Existing projection compatibility remains for older overlays, plans, and render workflows.

### 5.2 Media engine

- Project media is managed under project-relative `assets/media/` paths.
- Generated waveform, thumbnail, and proxy derivatives use project-local `cache/media/` paths.
- Imports are streamed with a configured size limit and SHA-256 hashing.
- Assets have stable IDs, safe display names, typed media kinds, content type, source hash, probe metadata, and derivative metadata.
- Metadata probing uses FFprobe.
- Waveforms decode deterministic mono signed 16-bit PCM and persist compact peak data.
- Thumbnail and proxy cache identities derive from source hash, derivative type, options, and implementation version.
- Relinking preserves the asset ID, replaces the managed source, and invalidates stale derivatives.
- Project health associates missing files and relink suggestions with media asset IDs.
- The Workspace page exposes import, refresh, relink, waveform, thumbnail, and proxy controls.

### 5.3 Transport and audio foundation

- `TransportService` owns project-scoped sample position, play, record, pause, stop, seek, and loop state using a monotonic clock.
- `AudioRenderGraphBuilder` creates immutable audio track routes from canonical project data.
- Audio route contracts include clips, gain, pan, mute, solo, output bus, sample rate, and buffer size.
- `WindowsAudioEngine` enumerates Windows render devices and prepares WASAPI shared `AudioGraph` playback away from the UI thread.
- UI transport changes are forwarded to the audio engine through application services.
- Project media is materialized before audio graph creation; media I/O is not performed in the render callback.
- The current Windows implementation intentionally rejects unsupported pan and non-master bus routing rather than silently producing incorrect audio.
- Meter contracts exist, but production meter capture and a complete routing/mixer graph remain Phase 5 work.

### 5.4 Director, renderer, review, and provider foundations

- Shared Director contracts, SceneSpec, StoryBible, workflow recovery, and Reactive Lab handoff foundations exist.
- Hunyuan internal rendering has hardened completion behavior and existing model/runtime integration.
- LTX 2.5 has hardware guidance, runtime registration, optional installation flow, and render request integration.
- Director Review has persisted review reports, frame/clip review services, UI, and test coverage.
- Provider work includes normalized definitions, capability surfaces, normalized generation flow, queue integration, and UI exposure.
- These foundations must be audited against the exact acceptance criteria of Phases 7-11 after the dependency phases are complete. Existing code or a prior milestone name is not by itself proof that every roadmap criterion is satisfied.

## 6. Completed Phase Record

### Phase 0 - Audit and Safety

**Status:** Foundation complete; maintain continuously.

Completed work includes architecture inventory, renderer/provider/timeline/media/audio surveys, regression references, and preservation rules. The inventory is maintained in `docs/PROFESSIONAL_DAW_ARCHITECTURE_INVENTORY.md`.

Ongoing requirement: update the inventory when ownership, runtime boundaries, persisted schemas, or replacement status changes.

### Phase 1 - Shared Core Contracts

**Status:** Complete and pushed in `a5ebae7`.

Delivered:

- versioned project, track, timeline event, and media asset contracts
- exact sample-based time model
- command and undo transaction contracts
- hardware profiles
- provider and renderer capability contracts
- Director, SceneSpec, and StoryBible contracts
- compatibility adapters and regression tests

### Phase 2 - Timeline Core

**Status:** Complete and pushed in `5c46692`.

Delivered:

- canonical timeline store and persistence
- ordered tracks and events
- selection state
- exact sample split, trim, move, and source-range arithmetic
- rational snapping
- zoom and scroll state
- markers
- revision-aware command history and undo/redo
- backend editor commands
- WinUI timeline controls
- compatibility behavior for overlays, ripple edits, cross-track moves, and existing plans

Validation at the phase gate included 369 passing WinUI Core tests.

### Phase 3 - Media Engine

**Status:** Complete and pushed as part of `936f3aa`.

Delivered:

- generic audio, video, and image import
- safe managed project media paths
- metadata probe
- content hashing and deduplication
- persistent project media pool
- deterministic waveform cache
- deterministic thumbnail cache
- proxy generation
- path-based and managed-upload relinking
- derivative invalidation after source replacement
- project health and relink integration
- typed WinUI API models and source-generated JSON support
- visible Workspace media-pool controls
- focused backend and WinUI client tests

Latest validation:

- backend media, project-health, and router tests: 16 passed
- Ruff on Phase 3 Python files: passed
- WinUI solution build: passed with 0 errors
- WinUI Core tests: 382 passed

### Phase 4 - Transport and Audio Engine

**Status:** Foundation complete and pushed as part of `936f3aa`; accepted as the Phase 4 gate based on current scope and green validation.

Delivered:

- shared sample-based transport service
- play, pause, stop, seek, record state, and loop behavior
- audio device abstraction and Windows device enumeration
- canonical audio track route graph
- track mute/solo/gain and output-route contracts
- WASAPI shared playback implementation
- background graph preparation and operation queue
- media materialization outside playback processing
- explicit rejection of unsupported routing rather than degraded success
- timeline transport and engine status UI
- deterministic transport and audio graph tests

Remaining advanced audio work belongs to Phase 5 and later phases: complete bus graph processing, production metering, native plugin DSP, ASIO/exclusive modes, automation, recording workflows, and low-latency monitoring.

## 7. Active Phase

### Phase 5 - Mixer / VST3

**Status:** In progress. No Phase 5 implementation commit has been created yet.

#### Goals

- mixer service
- synchronized channel strips
- insert graph
- sends
- buses, groups, FX returns, and master
- out-of-process plugin scanner
- VST3 host boundary
- crash quarantine and metadata cache
- project-wide plugin delay compensation (PDC)

#### Planned architecture

1. Add immutable mixer contracts in `EdmgStudio.Core.Audio`:
   - channel identity, type, name, color, visibility, and selection
   - input/pre-gain, phase, inserts, channel gain, pan, mute, solo, record enable, and monitor state
   - pre/post-fader sends
   - track, group, FX return, and master buses
   - explicit output routes
   - plugin instance state, bypass, enabled state, preset/snapshot data, and reported latency
2. Add a validated mixer graph builder:
   - reject duplicate IDs, missing destinations, illegal feedback cycles, and invalid values
   - preserve deterministic processing order
   - calculate audible paths before callback consumption
   - precompute graph changes off the real-time path
3. Add a PDC planner:
   - calculate insert, channel, bus, route, and master latency
   - determine per-path compensation delay
   - retain sample-coherent alignment across parallel routes
   - expose total and per-channel latency for UI diagnostics
4. Add a mixer service:
   - own immutable snapshots
   - publish bounded commands or graph replacements to the audio engine
   - synchronize mixer and timeline track selection
   - preserve mixer state in extension-safe project metadata
5. Add plugin discovery contracts and cache:
   - stable plugin ID
   - module path and class information
   - vendor, category, version, I/O layout, editor support, preset support, and latency
   - scan timestamp, fingerprint, status, and diagnostics
6. Add a scanner subprocess boundary:
   - scan one module in a child process
   - impose a timeout
   - use structured request/response data
   - treat nonzero exit, malformed output, timeout, and crash as explicit failures
   - never load an unknown third-party module into the Studio UI process during discovery
7. Add quarantine management:
   - persist module fingerprint, failure reason, crash/timeout count, and timestamp
   - skip unchanged quarantined modules on normal scans
   - allow an explicit user-requested rescan or quarantine clear
8. Add a VST3 host interface and capability states:
   - `Unavailable`, `ScannerReady`, `HostReady`, and `ProcessingReady`
   - do not report processing readiness until the native host can instantiate, negotiate buses, process audio, restore state, and report latency
   - isolate plugin processing from the UI and preferably from the primary process
9. Extend the audio configuration with the validated mixer graph while retaining compatibility with current track routes.
10. Add a visible Studio mixer surface, preferably a dedicated Mixer page or synchronized Timeline mixer panel:
    - channel strips with name/color/meter/fader/pan/mute/solo/record/monitor
    - insert slots and bypass controls
    - sends and output routing
    - bus, FX return, and master strips
    - plugin scan status and quarantine controls
    - PDC status and latency display

#### Phase 5 acceptance criteria

- Invalid or cyclic mixer routes fail before reaching the audio callback.
- Mixer snapshots are immutable and deterministic.
- Mute/solo behavior works across tracks and buses.
- Send tap position and gain are represented unambiguously.
- PDC calculations align parallel paths in samples.
- Scanner crashes, hangs, and malformed responses cannot crash the Studio process.
- Quarantine survives restart and can be explicitly cleared.
- Plugin metadata cache invalidates when the module fingerprint changes.
- UI displays actual capability state and never labels scanner-only support as active VST3 processing.
- Timeline and mixer selection stay synchronized.
- Existing projects without mixer metadata load with safe master-routing defaults.
- WinUI XAML compiles and all existing regressions remain green.

#### Phase 5 commit gate

- Build the complete WinUI solution.
- Run all WinUI Core tests, including mixer graph, PDC, scanner protocol, cache, quarantine, and persistence tests.
- Run any native host/scanner tests that can execute without third-party plugins.
- Review the staged diff for unrelated files.
- Commit as a Phase 5-only change with the required Copilot co-author trailer.
- Push to `origin/codex/Unified` and confirm local and remote hashes match before Phase 6 begins.

## 8. Planned Remaining Phases

### Phase 6 - Automation and Advanced Editing

Implement:

- automation lanes for volume, pan, mute, sends, plugin parameters, and selected render parameters
- Read, Write, and Touch modes
- efficient point and curve storage
- fades and crossfades
- track lanes and take versions
- comping and active-version selection
- non-destructive time stretch and playback-rate descriptors
- nudge, ripple, slip, slide, and advanced range operations
- logical action engine using the existing command/undo transaction architecture

Plan:

1. Extend canonical contracts with versioned automation, lane, fade, and process descriptors.
2. Add backward-compatible migration and extension-preserving persistence.
3. Implement operations in Core and backend command handlers, not page code-behind.
4. Add timeline lane rendering and automation editing controls.
5. Route audio automation to precomputed engine data without UI-thread access in processing.
6. Add exact-time, undo/redo, overlap, comp, and migration tests.
7. Commit and push Phase 6 before Director acceptance work.

### Phase 7 - Director

Existing Director infrastructure is substantial, so this phase is an acceptance-gap closure rather than a rewrite.

Audit and complete:

- Qwen3-VL-8B runtime readiness and capability reporting
- StoryBible persistence and revision linkage
- SceneSpec planning
- provider/model-specific prompt compilers
- timeline awareness for selected ranges, neighboring scenes, markers, lyrics, analysis, and active takes
- shared Workspace, AI Planner, Director, and Reactive Lab draft behavior

Acceptance must prove draft recovery, reviewed keyframe persistence, timeline-context prompts, version compatibility, and graceful operation when the preferred model is unavailable.

### Phase 8 - Hunyuan Renderer

Existing Hunyuan work will be audited and completed for:

- standard internal renderer path
- low-VRAM mode
- T2V and I2V
- deterministic chunking and assembly
- canonical render queue state transitions
- artifact registration in the media pool
- explicit user-approved timeline insertion
- cancellation, restart recovery, diagnostics, and capability gating

No installation or model manifest alone counts as runtime readiness.

### Phase 9 - LTX Renderer

Existing LTX 2.5 integration will be audited and completed for:

- high-tier rendering path
- hardware qualification
- model manager integration
- optional installation and uninstall safety
- LTX-specific prompt compiler
- render queue and artifact normalization
- media-pool registration and timeline insertion
- clear fallback behavior that does not conceal failures

### Phase 10 - Director Review

Existing Director Review work will be audited and completed for:

- generated frame sampling
- optional clip-understanding path
- versioned persisted `ReviewReport`
- continuity scoring
- correction instructions for subsequent scenes
- bounded retry policy with explicit stop conditions
- retention of reviewed camera and motion keyframes
- visible review state, evidence, and retry history in WinUI

### Phase 11 - Provider Refactor

Commit `ce1b52b` provides a strong implementation foundation. The ordered phase audit will verify:

- all current providers are represented by definitions and capabilities
- provider requests and outputs use normalized contracts
- queue status and failures map consistently
- credentials stay in secure settings and out of projects
- costs are retained when reported
- provider outputs become normal media/artifacts
- cloud failure does not break local rendering
- existing provider behavior remains available

Any acceptance gaps will be corrected in a dedicated Phase 11 commit and push. If no code changes are necessary, the validation evidence and exact accepted commit will be recorded without creating an empty commit.

### Phase 12 - Remote Control / Quick Controls

Implement:

- centralized command registry with stable command IDs
- user-editable keybindings and conflict detection
- MIDI input discovery and learn/mapping
- eight context-aware Quick Controls
- transport bindings
- mixer bindings
- persistence and import/export of mappings
- WinUI settings and control surfaces

Remote inputs must dispatch the same commands used by the UI and must not mutate project state through an alternate path.

### Phase 13 - Professional Post Features

Implement incrementally:

- waveform/common-audio, timecode, clap, and transient alignment
- ADR cueing, takes, recording metadata, and review
- reconform from changed picture/editorial references
- practical interchange formats with explicit compatibility reports
- surround buses and channel layouts
- object audio only where platform, renderer, and export support justify it

Each subfeature must use canonical timeline, media, command, mixer, and provenance contracts. Unsupported interchange fields or audio layouts must be reported rather than silently discarded.

## 9. Validation Strategy

### WinUI

From the repository root:

```powershell
dotnet build studio\edmg-studio-winui\EdmgStudio.WinUI.slnx --no-restore --nologo
dotnet test studio\edmg-studio-winui\tests\EdmgStudio.Core.Tests\EdmgStudio.Core.Tests.csproj --no-build --no-restore --nologo
```

The complete solution build is mandatory because Core tests do not compile all WinUI XAML pages.

### Backend

Use the pinned Python 3.12 and `uv` environment:

```powershell
uv lock --project studio\edmg-studio\python_backend --check
uv sync --project studio\edmg-studio\python_backend --frozen --extra cpu --extra core --extra audio --group test --group lint
uv run --project studio\edmg-studio\python_backend --frozen --extra cpu --extra core --extra audio --group test python -m pytest
```

Run the smallest focused tests while developing, then the applicable full regression scope before the phase commit. Run Ruff on changed Python files.

### Cross-scope regression

```powershell
uv run --project studio\edmg-studio\python_backend --frozen --extra cpu --extra core --extra audio --group test python scripts\run_pytest_scopes.py
```

Validation must use exit status and assertions as authoritative. Known, documented stderr noise is not a failure when the test runner exits successfully.

## 10. Commit and Push Procedure

For every remaining phase:

1. Confirm the branch is `codex/Unified` and inspect the worktree.
2. Re-read files shared with concurrent work before editing or staging.
3. Stage only the phase files or exact phase hunks.
4. Review `git diff --cached --stat` and `git diff --cached`.
5. Run `git diff --cached --check`.
6. Run the targeted and regression validation commands.
7. Commit with a phase-specific subject and this trailer:

   ```text
   Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
   ```

8. Push to `origin/codex/Unified`.
9. Verify `git rev-parse HEAD` equals `git rev-parse origin/codex/Unified`.
10. Record the accepted commit and validation result before starting the next phase.

## 11. Known Risks and Controls

| Risk | Control |
| --- | --- |
| Concurrent changes mix phases | Use hunk-level staging, inspect shared files again before commit, and never revert unrelated user work. |
| XAML regressions hidden by Core tests | Build the complete WinUI solution at every UI phase gate. |
| Real-time audio thread contamination | Prepare immutable graphs off-thread and communicate through bounded queues/snapshots. |
| Third-party plugin crash or hang | Scan and, where feasible, host out of process with timeout, explicit failure, and quarantine. |
| False plugin readiness | Separate discovered, scanner-ready, host-ready, and processing-ready capability states. |
| PDC drift | Calculate route latency in samples and test parallel track/bus/master paths. |
| Project schema breakage | Preserve extension data, add migrations, and test old project fixtures. |
| Missing media or stale derivatives | Use stable asset IDs, source hashes, project-relative paths, health checks, and deterministic invalidation. |
| Provider or renderer fallback hides failure | Surface explicit status and diagnostics; never return success-shaped fallback results. |
| Renderer output bypasses project model | Register output as a normal artifact/media asset before timeline insertion. |
| Director re-analysis destroys reviewed work | Preserve shared drafts and reviewed keyframes unless the user explicitly replaces them. |
| Hardware-dependent tests are unavailable | Test contracts and deterministic fakes locally; capability-gate real hardware integration and record untested hardware paths honestly. |

## 12. Definition of Program Completion

The Professional DAW roadmap is complete only when:

- all phases 0-13 have an accepted commit or an explicit audit proving an existing commit satisfies the phase
- every phase gate is pushed to `origin/codex/Unified`
- the current project schema has migrations and compatibility tests
- the Studio UI exposes all user-facing capabilities
- timeline, mixer, transport, media, Director, provider, renderer, review, remote-control, and post workflows use shared contracts rather than isolated state
- real-time audio and third-party plugin failures cannot take down UI or corrupt project state
- the complete WinUI solution builds
- applicable WinUI, backend, and cross-scope tests pass
- required regression behavior remains intact
- documentation describes actual capability and does not overstate hardware, plugin, model, or renderer readiness
