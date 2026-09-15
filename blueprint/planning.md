# EDMG Studio Professional DAW Implementation Blueprint

## 1. Purpose

This document consolidates the Professional DAW work completed in EDMG Studio, the architecture and safety decisions made during that work, and the planned implementation sequence through Phase 13.

The Professional DAW roadmap is preserved here from the available records; the external master blueprint is an optional workstation audit reference and was absent during the 2026-09-15 audit. Its Professional DAW phases 0-13 are separate from the 14-item WinUI Native Experience roadmap. The Studio desktop UI under `studio/edmg-studio-winui/` remains the primary user surface; backend capabilities are not considered complete until users can drive them from the Studio UI where applicable.

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

The two external records are optional workstation audit references and were absent during the 2026-09-15 audit; they must never become build, test, launch, packaging, or runtime dependencies.

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
- Phase 5 acceptance closure is the commit containing this record; its exact pushed hash is recorded in the delivery ledger after publication.
- Native VST3 discovery and processing remain capability-gated as unavailable because no qualified native SDK host/scanner is present.

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
| `34bea29` | Fix audio transport discontinuities and failed worker handling | Phase 5 prerequisite transport correctness |
| `bddf9c9` | Add mixer routing and PDC planning foundation | Phase 5 mixer graph foundation |
| `2fe075f` | Add versioned mixer snapshots and audibility planning | Phase 5 control-state and mute/solo foundation |
| `418f5a4` | Add isolated VST3 discovery and quarantine | Phase 5 plugin discovery safety foundation |
| `a592ff1` | Add timeline mixer persistence and channel controls | Phase 5 persistence and synchronized Timeline UI slice |

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

**Status:** Accepted for the managed mixer, persistence, discovery-safety, and Studio UI scope. Native VST3 scanning/hosting and live Windows AudioGraph mixer execution remain explicitly unavailable rather than being reported as ready.

#### Acceptance closure — 2026-09-15

- A versioned, extension-preserving mixer document persists tracks, groups, FX returns, master, inserts, sends, plugin state, routing, colors, visibility, and control state. Legacy projects receive safe defaults; newly added audio tracks reconcile into an existing mixer without discarding saved channel state.
- `MixerProcessor` provides preallocated stereo gain/balance, bus and send summing, mute/solo audibility, cross-block PDC delay buffers, and peak/RMS snapshots behind the Core processing boundary.
- The Timeline mixer surface synchronizes track selection, exposes persisted gain, pan, mute, solo, record, monitor, and output controls, and displays all channels, insert/send metadata, PDC diagnostics, and honest runtime limitations.
- Windows AudioGraph playback receives a centered, direct-master compatibility projection so modeled pan and bus routes remain persisted without disabling legacy playback. It does not execute the Core bus/send/PDC processor or expose live meters.
- Scanner responses are strictly bounded and parsed; cache, fingerprint invalidation, timeout/crash isolation, and quarantine remain active. With no native scanner or VST3 SDK host installed, capability is `Unavailable`, and no native plugin processing is claimed.
- Raw Timeline JSON validates the mixer before publication, and malformed or unsupported mixer documents are surfaced as UI errors without replacing the active document.
- Acceptance evidence: complete Debug WinUI solution build passed with 0 errors; 40 focused mixer/runtime tests passed; complete Core suite passed with 429 tests after review fixes. Existing analyzer warnings and the intentionally unused live-meter event remain.

#### Prerequisite correctness work — 2026-09-15

The first implementation slice hardens the existing Phase 4 playback foundation before expanding mixer routing:

- Explicit transport updates seek active audio even when the requested change is below the ordinary 100 ms drift threshold.
- A shared Core playback cursor detects short loops and multiple loop crossings between worker updates.
- Worker failure closes the command channel before draining it; future transport and configuration requests fail promptly.
- Timeline stops playback and displays a restart instruction when the audio engine fails.
- Graph cleanup attempts every owned resource even if stopping or disposing another resource fails.
- Regression tests exercise cursor discontinuities and the actual Windows worker with an injected failure, without opening an audio device.

This is prerequisite work, not Phase 5 acceptance. Mixer routes, PDC, plugin scanning/quarantine, VST3 processing and their Studio controls remain open. Full device playback qualification remains separate from unit tests and shell launch checks.

Validation for this slice: 389 Core tests passed; complete Debug WinUI solution build passed (existing analyzer and unused-meter-event warnings remain). Direct unpackaged launch with backend spawning disabled displayed "This application could not be started"; invoking the DLL through dotnet also exited unsuccessfully. No responsive Studio shell or real-device playback is claimed.

#### Initial mixer graph slice — 2026-09-15

- Immutable channel, insert, pre/post-fader send, route-delay and channel-latency contracts live in `Core/Audio/MixerGraph.cs`.
- The graph builder validates IDs, destinations, values, terminal master routing and feedback cycles before producing a deterministic topological processing order.
- The PDC planner aligns parallel incoming routes in samples, including nested buses and FX sends. Bypassed inserts retain their reported latency; disabled inserts contribute none.
- Current audio routes adapt to the graph without changing project persistence. The existing Windows engine still rejects unsupported pan and bus processing.
- Timeline exposes a collapsible routing/latency inspector that explicitly identifies the result as a plan, with native plugin processing and compensation buffers inactive.
- Remaining: channel-strip editing and persistence, mute/solo propagation through buses, actual bus/send DSP and delay buffers, meters, scanner/cache/quarantine, native plugin host, selection synchronization and live acceptance.

#### Mixer snapshot and audibility slice — 2026-09-15

- `MixerService` atomically publishes validated, immutable, monotonically versioned graph snapshots from the control thread.
- Mixer channels now carry validated gain, pan, mute, solo, record-arm and input-monitor state without changing persisted project contracts.
- Graph planning precomputes bus-aware audible channel IDs: muted buses suppress upstream sources, soloed buses retain their input path, and soloed tracks retain downstream bus, send and master paths.
- Legacy audio routes transfer track gain, pan, mute and solo state into the mixer plan; the Timeline routing inspector labels each route audible or inaudible.
- This remains control-thread planning. Actual bus/send mixing, compensation delay buffers, meters, mixer editing/persistence and native plugin processing remain open.

#### VST3 discovery safety slice — 2026-09-15

- Core defines explicit `Unavailable`, `ScannerReady`, `HostReady` and `ProcessingReady` capability states; the Studio reports only scanner readiness until native hosting and processing are implemented.
- Module metadata is keyed by path, size, write time and SHA-256 fingerprint, so changed modules cannot reuse stale cache or quarantine entries.
- Catalog and quarantine state persist atomically outside project files. Failed, timed-out and malformed scans quarantine the exact module fingerprint; missing scanner installation does not blame or quarantine a module.
- The scanner client invokes one module per external process with redirected structured output, cancellation and a hard timeout. Unknown plugin code is never loaded into the Studio UI process for discovery.
- Settings displays the actual scanner capability, cache and quarantine counts, and provides an explicit quarantine-clear action with confirmation.
- The external native scanner executable and VST3 host/processing implementation remain open; this slice does not claim active plugin support.

#### Mixer persistence and Timeline channel strip slice — 2026-09-15

- `TimelineMixerProjection` provides one extension-safe persisted contract for track gain, pan, mute, solo, record arm, input monitoring and output routing; legacy projects receive unity gain, centered pan, disabled control flags and master output defaults.
- Mixer updates clone the timeline, validate finite control values and supported output routing before publication, and preserve unrelated timeline, track, routing and clip fields.
- The Timeline Mixer inspector edits supported audio-track controls through the existing revision-checked autosave and undo/redo path. Selecting a clip selects its track, selecting a track header opens its channel strip, and selected-track view state survives reload when the track still exists.
- Playback graph construction consumes the same mixer projection as the UI, preventing default and normalization drift between persisted state and audio configuration.
- Modeled pan and bus routing remain visible and persisted while the Windows AudioGraph compatibility path plays centered tracks directly to master. Core bus/send/PDC/meter processing exists behind a deterministic processor boundary but is not connected to live AudioGraph playback.

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

### Phase 6 - Automation and Advanced Editing

**Status:** Accepted for the versioned editing contract, revision-safe backend operations, native Timeline controls, immutable off-thread automation snapshots, and mandatory Windows Release x64 CI scope. Live Windows audio callback consumption remains explicitly unavailable until a safe atomic engine hook and device qualification exist. This phase is complete when the acceptance commit containing this ledger is pushed to `origin/codex/Unified`.

#### Implementation and acceptance ledger

Delivered in the working tree:

- versioned, extension-preserving automation, fades/crossfades, takes, comp ranges, and non-destructive process descriptors with exact int64 sample strings
- revision-aware backend operations for automation and advanced editing through the existing command/undo transaction boundary
- matching Core operations and a structured native Timeline surface for automation modes and points, fades/crossfades, takes/comping, and nudge/ripple/slip/slide/range actions
- immutable automation lookup snapshots prepared away from the real-time path
- a mandatory Windows Release x64 CI job that restores and builds the complete WinUI solution (including XAML) and runs `EdmgStudio.Core.Tests` with `--no-build`

Capability boundary:

- Live Windows audio callback consumption of automation is **unavailable**, not merely unverified. It requires a bounded, allocation-safe atomic snapshot handoff plus seek, loop, graph-swap, underrun, device-loss, and real-device tests before readiness can be claimed.
- C# and Python tests exercise equivalent Phase 6 contract behavior, but there is no authoritative shared cross-language golden fixture in the current tree. This documentation/CI-only closure cannot create one without changing source/test files, so CI must not claim that coverage.
- Frontend API schema generation currently covers Project Health only; it is not proof of generated contracts for Timeline, editing, automation, render, or provider APIs.
- Raw JSON remains diagnostic material; normal Timeline use must communicate operation status, affected ranges, resulting revision, and undo availability through structured UI.
- Final local acceptance on 2026-09-15 passed the frozen lock check, Ruff, all 88 focused backend editor tests, all 161 backend tests with 4 expected live-smoke skips, the complete WinUI Release x64 solution/XAML build, all 441 Core tests, and `git diff --check`. The aggregate runner passed 161 repository-scope tests with 4 skips and reported 888 backend-scope passes, 4 skips, and exactly 16 known `test_workspace_reactive_integration.py` failures caused by absent uploaded-audio fixtures returning HTTP 404; no additional failures occurred. The final narrow read-only review found no high-confidence defect.

#### Whole-project audit recommendations

These recommendations are consolidated here as Phase 6 closure context or explicitly deferred modernization work; they do not collapse Professional DAW Phases 0-13 into the separate post-13 track.

1. **Native UX/design system backlog (post-13):** create shared `StatusCard`, `ModelPicker`, `ReadinessPanel`, `EmptyState`, `JobProgressCard`, and `PropertySection` controls; support Compact/Comfortable density, accessible focus/high-contrast behavior, and consistent spacing; add sticky Render commands, model/readiness cards and structured preflight, timeline interaction polish, and Direct3D preview comparison plus resolution/GPU diagnostics.
2. **Direct3D qualification (post-13):** qualify the launched packaged and unpackaged app—not compilation alone—through navigation, per-monitor DPI/scaling, resize, fit/fill/fullscreen and exit, frame stepping/comparison, device loss and recreation, repeated page entry, and long-duration preview/render soak tests.
3. **Architecture qualification:** only x64 is qualified. Do not build, publish, or claim x86 or ARM64 support until the native preview, backend payload, installer, launch, upgrade, and soak gates pass on that architecture.
4. **Terminology:** call envelope/parameter playback **DAW parameter automation**. Reserve **AI workflow automation** for orchestration, agents, planning, queue, or render workflows so product UI, contracts, and documentation cannot confuse the two.
5. **Electron hardening (post-13):** move production windows from `sandbox: false` to a qualified sandboxed design, disable production DevTools, retain context isolation and disabled Node integration, minimize/validate filesystem IPC with explicit path and capability allowlists, and regression-test the preload boundary before retiring compatibility behavior.
6. **CI and release supply chain (post-13):** pin every GitHub Action to a reviewed full commit SHA; set explicit artifact retention; generate and retain attestations, SBOM/license output, checksums, signed-package provenance, test logs, and release evidence. Existing action tags are not yet full-SHA pinned and are intentionally not repinned as part of this narrow Phase 6 change.
7. **Platform wording:** describe macOS only as unqualified or aspirational unless a macOS build, package, launch, rendering, and support matrix is actually maintained. Current Windows x64 and Linux claims must remain scoped to their tested surfaces.
8. **Dependency and client governance (post-13):** consolidate root Python dependency authority around the pinned backend `pyproject.toml`/`uv.lock`; document and freeze compatibility-only root, legacy desktop, and Electron entrypoints except for security/parity work; retire an entrypoint only after project-open, render, migration, packaging, and rollback parity.
9. **Generated-state hygiene:** `.test-master-editor-*` directories are generated backend test state and must be ignored or cleaned by the owning test fixture, never treated as source or release evidence. Cleanup implementation is outside this two-file ownership scope.
10. **Python test authority:** `scripts\run_pytest_scopes.py`, executed through the frozen backend `uv` project, is the authoritative aggregate Python runner; focused suites are development evidence, not a substitute for the aggregate gate.
11. **Configuration hygiene:** machine-specific root paths/configuration belong in ignored local overrides, environment variables, or checked-in templates with portable defaults; workstation paths must never become schema, build, test, or runtime requirements.
12. **Contract authority:** expand mechanical schema/golden-fixture validation beyond Project Health. Until a shared C#/Python/TypeScript fixture exists, equivalent per-language tests are useful but are not cross-language fixture CI.

Audit context: `studio\edmg-studio-winui\ChatLog3.md` and `ChatLog4.md` were available and reviewed. `C:\Users\user\Downloads\ChatLog5.md` and `C:\Scripts\EDMG_Studio_Master_Blueprint_AI_DAW_Timeline.md` were absent on this workstation. Their absence is context only and must never fail a build, test, launch, packaging, or runtime path.

#### Phase 6 acceptance gate

1. Build `studio\edmg-studio-winui\EdmgStudio.WinUI.slnx` in Release x64 and run the complete Core test project against that build.
2. Run focused backend editor coverage, then the authoritative aggregate Python runner in the frozen environment.
3. Verify schema migration/reload, extension preservation, stale revisions, locks, exact sample values, transaction atomicity, undo/redo, and native Timeline operation feedback.
4. Keep live automation unavailable until the safe atomic engine hook and required runtime/device qualification are complete; acceptance may record that capability gate honestly rather than implying callback consumption.
5. Review the complete diff and CI results, record exact evidence, commit only Phase 6 files, push, and confirm local/remote hashes before Phase 7 begins.

## 8. Planned Remaining Phases

### Phase 7 - Director

**Status:** Accepted for versioned Director workflow and Reactive handoff contracts, exact selected-range context, durable review recovery, revision-safe review/apply, model-readiness remediation, and native/React Studio parity. Generation registration is serialized with worker publication through a job-first SQLite transaction so concurrent retries cannot orphan, cancel, or attach the wrong job. This phase is complete when the acceptance commit containing this ledger is pushed to `origin/codex/Unified`.

Existing Director infrastructure is substantial, so this phase is an acceptance-gap closure rather than a rewrite.

Audit and complete:

- Qwen3-VL-8B runtime readiness and capability reporting
- StoryBible persistence and revision linkage
- SceneSpec planning
- provider/model-specific prompt compilers
- timeline awareness for selected ranges, neighboring scenes, markers, lyrics, analysis, and active takes
- shared Workspace, AI Planner, Director, and Reactive Lab draft behavior

Acceptance must prove draft recovery, reviewed keyframe persistence, timeline-context prompts, version compatibility, and graceful operation when the preferred model is unavailable.

#### Implementation and acceptance ledger

Delivered in the working tree:

- version 2 Director workflow and version 1 Reactive handoff contracts, with legacy migration, extension preservation, and explicit rejection of unsupported future versions
- exact decimal-string sample ranges and bounded timeline context covering neighboring scenes, markers, lyrics/transcripts, clips, active takes, and analysis, with persisted context digest and revision linkage
- project-owned Director job, review, and apply metadata that survives restart; queue reconciliation is read-only and reviewed application requires the matching persisted job identity
- shared React and native WinUI generation, review, recovery, and non-destructive Reactive apply behavior, including recovery that requires the exact draft to be displayed by Review before Apply is re-enabled
- structured preferred-model unavailability responses that preserve user instructions and provide actionable remediation
- cross-instance atomic idempotent job creation, job-first registration/publication locking, creator-owned compensation, duplicate-winner reconciliation, and best-effort compatibility mirrors that retries can repair

Capability and validation boundary:

- Qwen runtime readiness is capability-derived; model installation alone is not reported as usable generation readiness.
- Final local acceptance on 2026-09-15 passed the frozen lock check, changed-file Ruff, all 37 Director/workflow/job-store lifecycle tests, all 180 React tests plus lint and typecheck, the complete WinUI Release x64 solution/XAML build with 2 warnings and 0 errors, all 450 Core tests, and `git diff --check`.
- The authoritative aggregate runner passed 161 repository-scope tests with 4 skips and reported 898 backend-scope passes with 4 skips. Its only failures were the same 16 `test_workspace_reactive_integration.py` cases whose absent uploaded-audio fixtures return HTTP 404 `Uploaded audio file is missing`; no Phase 7 or additional failure class occurred.
- `app.py` retains its unchanged 64-diagnostic Ruff baseline; Phase 7 changed files introduce no new Ruff diagnostics. The final narrow read-only concurrency and lifecycle review found no significant issue.

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

Phase 8 accepted implementation (2026-09-15):

- The native Render Studio exposes HunyuanVideo-1.5 selection, T2V/I2V/auto modes, source assets, low-VRAM mode, generation chunk size and overlap, model readiness, queue progress, cancellation, and completed-result insertion without requiring API-only operation.
- The isolated Linux/WSL worker uses the official HunyuanVideo-1.5 pipeline with explicit companion-model and repository paths, CUDA-device isolation, exact frame-count validation, deterministic per-chunk seeds, previous-frame anchoring, overlap blending, progress callbacks, and cancellation between chunks.
- Low-VRAM mode applies bounded 768x432 resolution, eight-frame scene and generation chunks, one-frame decode chunks, float16, CPU offload, and bounded overlap. Explicit I2V fails closed without a resolvable project source asset.
- Hunyuan request validation is consistent across WinUI and FastAPI: overlap must be smaller than the generation chunk size. Other engines retain their independent settings and compatibility behavior.
- Every claimed background job now maintains its attempt-scoped SQLite lease throughout execution. Long Hunyuan GPU jobs cannot be reclaimed concurrently after the five-minute base lease, while an actually interrupted worker remains recoverable after its renewed lease expires. Existing attempt fencing prevents an obsolete execution from publishing over a retry.
- Successful internal-video publication writes an artifact manifest, records the output in project video history, and returns normalized artifact provenance in the durable job result. Timeline insertion remains a separate user-approved, revision-checked and idempotent command that resolves only succeeded `internal_video` artifacts.
- Runtime readiness remains capability-derived and fails closed when the worker mode, official upstream layout, companion models, CUDA environment, or explicit runner configuration is unavailable.

Acceptance evidence:

- Focused backend renderer, request, artifact-insertion, job-store, worker-lease, cancellation, and recovery tests pass in the pinned Python 3.12 uv environment; changed backend files pass Ruff and `git diff --check`.
- Native Core request-builder and render-result insertion tests pass, and the complete WinUI Release x64 solution/XAML build succeeds.

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

## 8.1 Whole-Project Upgrade Roadmap

The 2026-09-15 whole-project audit reviewed the WinUI client, Core contracts, Python backend, maintained React/Electron client, legacy compatibility shell, persistence, rendering, providers, audio boundaries, security, CI, packaging, and tests. Upgrades are assigned to existing phases where they are required for acceptance; cross-cutting modernization follows Phase 13 so it cannot destabilize the ordered DAW gates.

### Phase-mapped upgrades

| Priority | Upgrade | Delivery phase | Acceptance boundary |
| --- | --- | --- | --- |
| Critical | Complete automation and advanced editing vertically across schema, backend, Core, WinUI, persistence, undo/redo, and qualified audio consumption | Phase 6 | Full WinUI build, Core suite, backend editor suite, migration fixtures, exact-time reload/undo tests, and explicit live-audio capability status |
| Critical | Add mandatory WinUI build, Core tests, and XAML compilation to CI | Phase 6 | Changes under `studio/edmg-studio-winui/` trigger a required Windows validation job; cross-language fixture CI remains open |
| Critical | Establish authoritative versioned schemas or mechanically validated golden fixtures across C#, Python, and TypeScript | Phases 6-7 | Exact sample strings, enum values, bounds, and extension preservation agree in all maintained runtimes; current API generation covers Project Health only |
| High | Add monotonic, atomic, backup-aware project and SQLite migration ledgers | Phases 6-7 | Every supported prior schema migrates repeatably; future or unsupported versions fail non-destructively |
| High | Persist Director/Reactive Lab handoff revisions and protect reviewed camera/motion keyframes from re-analysis | Phases 7 and 10 | Restart, stale-revision, unavailable-model, merge, and explicit replacement tests pass |
| High | Add request, project, job, provider, renderer, attempt, and artifact correlation with redacted structured diagnostics | Phases 7-11 | Support bundles and UI diagnostics contain useful correlation without credentials or private media |
| High | Promote render presets to versioned project render profiles with immutable job snapshots | Phases 8-9 | Shared and renderer-specific options round-trip and unavailable settings fail visibly |
| High | Run one provider/renderer conformance suite for capability probes, queue transitions, cancellation, retries, costs, artifacts, and explicit insertion | Phases 8-11 | Hunyuan, LTX, cloud providers, and local providers satisfy the same normalized lifecycle contract |
| High | Persist read, reviewed, approved, rejected, evidence, and retry state instead of using shell-only badge state | Phase 10 | Review state survives restart and opening the page does not mark unseen work reviewed |
| High | Require OS-protected credential storage for production and migrate the base64 file fallback behind explicit development-only consent | Phase 11 | Secret redaction, migration, remote binding, authentication, and CORS tests pass |
| High | Use one stable command registry for UI, keyboard, MIDI, Quick Controls, and accessibility actions | Phase 12 | No remote or shortcut path mutates project state outside the revision-safe command envelope |
| High | Add compatibility reports and golden fixtures for reconform, interchange, surround, and alignment | Phase 13 | Unsupported fields and layouts are reported rather than silently discarded |

### Post-Phase-13 WinUI Native Experience and modernization track

1. Replace synchronous application construction with an asynchronous, cancelable bootstrap that paints a lightweight accessible shell before credentials and backend initialization.
2. Extract `TimelinePage`, `WorkspacePage`, `RenderPage`, `ReviewPage`, and `StudioApiClient` workflow logic into testable coordinators and application services while preserving XAML names, routes, and compatibility façades.
3. Consolidate shell/page polling into one lifecycle-aware observable activity service with bounded cancellation, backoff, immutable snapshots, and no duplicate endpoint polling.
4. Add packaged and unpackaged WinUI UI automation covering launch, navigation, keyboard-only use, screen readers, high contrast, 200% scaling, focus restoration, offline startup, Director-to-Reactive handoff, timeline recovery, render preflight, and review decisions.
5. Establish deterministic signed MSIX production packaging, clean-install, upgrade, repair, rollback, uninstall, backend payload integrity, and supported-architecture qualification. Do not publish x86 or ARM64 artifacts until native preview and backend payloads pass the same gates as x64.
6. Decompose the Python composition root and large clients one bounded area at a time behind characterization-tested façades; do not perform a big-bang rewrite.
7. Consolidate supported product entrypoints and machine-specific configuration. Freeze compatibility-only shells except for security fixes, and retire them only after project-open, render, upgrade, and rollback parity tests pass.
8. Add local, opt-in OpenTelemetry-compatible tracing, support bundles, long-duration audio/render soak tests, failure injection, dependency governance, SBOM/license reporting, and release provenance.

### Audit controls

- Existing working paths remain until replacements pass equivalent source, packaged, migration, and rollback tests.
- Native VST3, realtime mixer automation, model, renderer, architecture, and installer readiness remain independently capability-gated.
- Machine-specific paths move to templates or runtime configuration and never become schema or build dependencies.
- The maintained WinUI client is the primary Windows surface; the maintained React/Electron client remains the Linux and compatibility surface until an explicit parity decision is validated.

## 9. Validation Strategy

### WinUI

From the repository root:

```powershell
dotnet build studio\edmg-studio-winui\EdmgStudio.WinUI.slnx --no-restore --configuration Release -p:PlatformTarget=x64 --nologo
dotnet test studio\edmg-studio-winui\tests\EdmgStudio.Core.Tests\EdmgStudio.Core.Tests.csproj --no-build --no-restore --configuration Release -p:PlatformTarget=x64 --nologo
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
