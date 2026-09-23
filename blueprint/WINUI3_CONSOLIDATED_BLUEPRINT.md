# EDMG Studio WinUI 3 Consolidated Blueprint

**Status:** Current forward plan and truth ledger for the native Windows Studio.
**Scope:** WinUI 3 is the product surface. Shared Python services, packaging, and runtime work are in scope only when they support WinUI.
**Authority:** This document consolidates the current `blueprint/planning.md`, the WinUI regression records, renderer/runtime instructions, release documentation, and the current worktree. It does not supersede source code, tests, or an accepted phase gate.

## 1. Operating rules

1. Preserve user projects, unknown extension fields, Director/Reactive Lab drafts, reviewed camera and motion keyframes, render profiles, artifact lineage, and revision/undo semantics.
2. Treat the WinUI desktop app as the only active product UI. Electron, React, Gradio, legacy shells, and external tools are compatibility or reference surfaces and do not receive new product scope here.
3. Keep backend, model, renderer, and packaging capabilities reachable through WinUI controls. API-only capability is incomplete.
4. Never turn a mocked, cached, still, hosted, or proxy result into a claim of genuine internal temporal rendering.
5. Installation, imports, health checks, compilation, or deterministic simulation do not establish runtime or hardware readiness. Readiness requires the appropriate smoke test and receipt.
6. Do not remove or replace a working path until an equivalent WinUI, migration, packaged, and rollback path passes.
7. Keep the current x64-first release boundary. Do not publish other architectures until their native preview, backend payload, package, launch, upgrade, and soak gates pass.
8. Do not build, launch, or package from stale generated output. Release artifacts must be freshly produced from the reviewed candidate and frozen dependency inputs.

## 2. Canonical WinUI product flow

`Workspace / All tools → Create/Open → Import → Analyze or reuse → Provider/BYOM plan → Optional managed Qwen Director → Review storyboard/workflow → Apply → Timeline/Reactive Lab → Render preflight → Queue → Review → Outputs → Save/Reopen/Recover → Export`

Workspace is the guided default, while AI Planner, Director, Storyboard, Reactive Lab, Timeline,
Render, Models, and Settings remain dedicated specialist surfaces. Managed Qwen strengthens a
baseline plan only when its runtime is ready; its absence or failure must leave the baseline and user
edits usable. BYOM selection is configuration, not endpoint or inference qualification.

The backend remains authoritative for project identity, revisions, persistence, jobs, media authorization, renderer selection, model readiness, and artifact publication. WinUI owns native navigation, editing, controls, diagnostics, and user approval.

### Required behavior

- Audio analysis creates one shared draft consumed by Director, Planner, Reactive Lab, Timeline, and Render.
- Reanalysis is exceptional and must not silently erase saved or reviewed work.
- Generated schedules remain drafts until explicit approval and application.
- Planner-owned timeline content can be regenerated while user-authored and locked content remains intact.
- Stale writes and stale schedule applications fail with an actionable reload/reapply path.
- Long jobs expose durable progress, cancellation, retry/recovery where supported, diagnostics, and output ownership.

## 3. Current implementation state

The latest repository history records completion of Professional DAW Phases 5 through 13, including managed mixer, automation/editing, Director, Hunyuan, LTX, Director Review, provider normalization, remote controls, Quick Controls, and professional post contracts. The newer hardening, qualification, documentation, and render-idempotency work is committed in `388faaf`, `358fa49`, and `0c9c6d1`.

The unified Workspace was delivered in `aaca973`, `5d8d7de`, `de6bdae`, and `361ff13`; final
regression evidence was recorded in `92c3ee5`. That evidence includes a Release x64 build, 520 Core
tests, and 87 focused backend tests with one real-audio test skipped because `STUDIO_TEST_AUDIO` was
unset. It does not qualify interactive GUI behavior, device audio, real Qwen/Whisper inference, a
long render, signing, Store submission, or a clean-machine release.

### Phase and evidence reconciliation

| Area | Current reading | Forward treatment |
|---|---|---|
| Professional DAW Phases 5–11 | Accepted in repository history and reflected in `blueprint/planning.md` | Preserve; use acceptance records as regression requirements. |
| Phase 12 Quick Controls and command/input work | Implemented with focused tests and x64 build evidence in `planning.md` | Preserve; keep hardware/MIDI qualification separate. |
| Phase 13 professional post contracts | Implemented with focused tests and x64 build evidence in `planning.md` | Preserve; finish running-app qualification and real media/device checks. |
| Unified Workspace | Combined All-tools surface, guided analysis/planning/Qwen review, specialist preservation, fallback, and evidence-aware readiness are implemented through `92c3ee5` | Preserve revisions and specialist routes; finish interactive and real-runtime qualification separately. |
| Current candidate hardening and qualification files | Committed in the current candidate (`388faaf`, `358fa49`, `0c9c6d1`, `20df73e`, `e4426ea`) | Review, test, and accept individually; compilation alone is not completion. |
| Workflow fixture and review-contract tests | Focused renderer/workflow coverage preserves explicit media fixtures, source-hash invalidation, reviewed-before-apply behavior, and temporary-store publication boundaries | Preserve these contracts; broader release and native UI gates remain separate. |
| Aggregate Python qualification | The canonical isolated runner passes: repository scope 164 passed/4 skipped and backend-package scope 987 passed/4 skipped | Keep `scripts/run_pytest_scopes.py` as the required frozen-environment regression gate. |
| Hunyuan/LTX runtime availability | Integration and fail-closed controls are documented; real runtime evidence remains environment-dependent | Keep unavailable until matching Level-5 smoke receipts exist. |
| Native audio, VST3, ADR, waveform, and multichannel output | Separate x64 VST3 scanner and host executables plus the AudioGraph-to-Core mixer bridge are implemented and qualified with Steinberg AGain; ADR/device playback and multichannel output remain unavailable or unqualified | Preserve the dual-binary VST3 evidence while advancing the remaining Gates C and D items; never infer audible or realtime capability from process-block tests. |
| Microsoft Store and signed release | Packaging/signing path is documented and code-signing is available; Store identity/certification is external | Complete Gate F with fresh x64 artifacts and Partner Center evidence. |

Accepted phase history is evidence of completed increments, not permission to erase current limitations. The current worktree and this blueprint are the starting point for the next acceptance review.

`blueprint/planning.md` retains a historical `Active Phase` heading for the ordered roadmap. Its
Phase 5 entry is accepted for the managed mixer scope while advanced native audio work remains
open; the heading must not be read as evidence that earlier accepted phases were undone.

### Implemented or documented foundations to preserve

- Versioned project/timeline contracts, exact sample positions, migration, extension preservation, revision-safe commands, undo/redo, autosave, and recovery.
- Media import, probing, project media pool, waveform/thumbnail/proxy derivatives, containment, signed media, and artifact provenance.
- Native unified Workspace with All-tools guidance, provider/BYOM baseline planning, managed-Qwen review/fallback, and explicit render handoff, plus preserved Director, Planner, Storyboard, Reactive Lab, Timeline, Render, Queue, Review, Outputs, Models, Settings, and Setup specialist surfaces.
- Shared Director/Reactive Lab draft identity and reviewed camera/motion keyframe persistence.
- HunyuanVideo-1.5 through WSL2/external Linux and LTX-2.5 through isolated runtimes, both fail-closed until real qualification.
- Durable provider envelopes, local/hosted provider lifecycle, idempotency, cancellation fencing, and WinUI provider controls.
- Stable command registry, keyboard/MIDI mappings, eight Quick Controls, atomic import/export, and native Settings/Timeline controls.
- Post-production contracts for timecode, alignment, ADR, reconform, interchange reports, channel layouts, and preserved object-audio metadata.
- WinUI crash logging, guarded bootstrap, package lifecycle harnesses, UI automation capability manifests, signed-release hooks, SBOM/checksum evidence, and x64 packaging controls.

### Explicit capability boundaries

- Windows playback uses WASAPI shared AudioGraph and now routes exact negotiated per-track float32 quanta through Core mixer/PDC/VST3 processing; audible device playback, timing continuity, and underrun resistance remain separate gates.
- The dedicated scanner reports supported, unsupported, failed, timed-out, malformed, and quarantined outcomes without exposing worker mode. The separate host performs qualification and persistent processing but rejects scan mode.
- Native VST3 scanning, instantiate/audio-and-event-bus negotiation, float32 processing, MIDI note input, parameter metadata/editing, state round-trip, latency reporting, compatible-worker recreation, sticky crash/timeout isolation, and exact dual-binary MSIX identity passed with Steinberg AGain. This proves the supported effect path, not arbitrary third-party compatibility or hard-realtime safety.
- Automation editing and immutable callback snapshots do not prove live callback consumption.
- Native ADR recording is unavailable unless a real capture device and qualification receipt pass; deterministic capture is test support only.
- Native bounded WAVE extraction and clap/transient/waveform alignment are implemented in Timeline Post with authorized project media, matching sample rates, cancellation, and explicit preview/apply. Running-app media qualification remains open; timecode alignment and imported canonical post data remain supported.
- Native preview/render/export is currently stereo-only; unsupported channel/object layouts are preserved and reported.
- Hunyuan and LTX package installation is not runtime readiness. Each requires a real inference smoke test and matching receipt.
- CI may validate packaging contracts while reporting interactive UI automation as not run when its driver is unavailable.

## 4. Forward execution order

### Gate A — Reconcile the current worktree

- Review all staged, modified, and untracked WinUI, Core, backend, packaging, workflow, and contract files.
- Separate accepted commits from in-flight work; do not call in-flight work complete solely because it compiles.
- Ensure all new files are included in the intended project/build or deliberately documented as qualification tooling.
- Run the current WinUI Release x64 build, Core tests, focused backend tests, and package-contract checks.

### Gate B — Finish native Studio reliability

- Async/cancelable startup with a usable shell while backend setup runs.
- One lifecycle-aware jobs/activity service with bounded polling and no duplicate page polling.
- Navigation, offline startup, backend restart, cancellation, repeated page entry, and shutdown tests.
- Timeline XAML initialization safety, crash logging, dispatcher safety, and recovery behavior.

### Gate C — Finish native audio and editing qualification

- Prove actual device playback, transport continuity, loop/seek behavior, failure recovery, and sustained underrun-free operation.
- Qualify the connected mixer, bus/send, PDC, meter, automation, and VST3 path on a real output device.
- Preserve honest unavailable/scanner-only/host-ready/worker-failed states and expand compatibility evidence beyond the qualified Steinberg AGain module.
- Qualify recording/monitoring only with a real device; retain unavailable states otherwise.

### Gate D — Finish WinUI post-production workflow

- Exercise timecode, alignment preview/apply, ADR cue/take review, reconform preview/apply, and interchange reports in the running app.
- Keep lossy exports explicit and preserve unsupported fields.
- Add native waveform extraction only with bounded, cancellable, tested implementation.
- Keep stereo-only processing visible and protect unsupported layouts from false success.

### Gate E — Finish renderer/model workflow

- Models page configures and probes Qwen, Whisper, Hunyuan, and LTX runtimes.
- Render preflight shows route, model, device, capability evidence, fallback policy, and blockers.
- Hunyuan uses WSL2/external Linux with Python 3.12, official checkout, selective assets, and no system Python 3.14.
- LTX uses its pinned isolated runtime and exact package manifest.
- Real Level-5 smoke tests produce valid output and hardware/runtime-fingerprinted receipts before renderer availability is enabled.
- A genuine internal temporal proof records project/revision, schedule, model/device, codec, duration, audio, motion evidence, hash, and provenance.

### Gate F — Finish native release qualification

- Source builds remain explicitly unpackaged; installed releases launch through registered package identity.
- Build the fresh x64 WinUI MSIX and the intended Windows installer from the same reviewed candidate and validated backend payload.
- Store staging uses exact Partner Center identity values and emits the Store upload package. Sideload/Setup.exe signing is tracked separately.
- Use the existing code-signing identity; fail closed when production signing is requested but unavailable.
- Verify signatures/timestamps, SBOM, checksums, backend manifest, package identity, and payload hashes.
- Run disposable-machine clean install, first run, project workflow, upgrade, repair, rollback, uninstall/data-retention, and recovery checks.
- Record Store submission metadata, certification result, known issues, and rollback instructions.

## 5. Documentation and stale-path policy

- `README_STUDIO.md`, `RELEASE.md`, the WinUI README, the release runbook, and packaging README must point to this blueprint and the current WinUI-first flow.
- Source launch instructions must identify unpackaged development builds. Release instructions must use packaged identity and must not launch stale generated executables directly.
- Old Electron, Gradio, standalone-engine, proxy-render, CPU-only, or development-identity instructions remain only when explicitly labeled compatibility, research, or local development.
- Every user-visible feature added to shared services must have a WinUI control, status, or diagnostic.
- Every release document must say whether a statement is current source behavior, a qualification requirement, historical evidence, or a blocked external gate.

### TensorRT component-runtime checkpoint (2026-09-22)

- Current source implements independently validated, content-addressed SD1.5 UNet and VAE decoder adapters with hybrid Diffusers fallback; native Models and Settings expose selected/all optimization, rebuild, cached-engine execution validation, deletion, refresh, and diagnostics.
- SDXL, SD3, Flux, SVD, AnimateDiff, LTX 2.5, WAN, and HunyuanVideo 1.5 are not declared TensorRT-capable until model-specific export, execution, numerical validation, and render dispatch exist. Qwen remains on llama.cpp and Whisper on CTranslate2.
- Fresh current-identity managed SD1.5 FP16 VAE and UNet engines were built and numerically validated on GPU 0, then loaded with `allow_build=False` and executed from the content-addressed cache in a new process. Synthetic TensorRT build/serialize/deserialize/execute passed independently on each of the three RTX A6000 GPUs; this is not multi-GPU inference. Current evidence is 48 component/runtime tests, 14 Director tests, 1,060 complete backend tests with 2 skipped, 12 repository packaging/static tests with 2 skipped, 39 packaging/signing Node tests with 1 skipped, 552 Core tests, a zero-warning Debug x64 WinUI build, and 2 frozen-backend startup tests. The native app stayed alive while supervising a healthy source backend, but Settings/Models/Render were not interactively exercised because no UI automation driver was available. Production sign/install, clean-machine, Store, and packaged Torch-TensorRT compilation remain separate gates.

### Source records reconciled by this blueprint

The comparison set included `blueprint/planning.md`, `WinUI-Hunyuan-Instructions.md`, `README_STUDIO.md`, the WinUI README, release/runbook and packaging guidance, backend model/runtime guidance, reactive CUDA validation, parity and architecture inventories, renderer/post plans, master blueprint documents, remediation plans, Copilot plans, and available ChatLog records. Missing external records are not treated as current evidence. Where records disagree, the stricter current code/test boundary and the WinUI-first release policy win; older claims remain only in the review-later list.

## 6. Superseded or review-later material

Keep these out of the forward execution path unless a later audit proves they are still useful:

- Older plans that target Electron/React as the primary product.
- The former 4 GiB WinUI spool proposal; the current policy is 512 MiB by default.
- Historical CPU-only or pre-WSL Hunyuan readiness records.
- Model catalog recommendations that conflict with the current managed Qwen/Hunyuan/LTX WinUI route.
- Simulated TensorRT Deforum or proxy-render paths retired by the current compatibility policy.
- Old test totals, old branch names, old package output directories, and old “partial/not started” tables.
- Unverified architecture targets or Store identities copied from examples.

## 7. Definition of WinUI completion

WinUI is complete when the current candidate can execute the full native flow without crash or silent state loss; all supported controls use canonical contracts; audio/render/model states are honest; project recovery and compatibility pass; the complete x64 solution/XAML build and applicable suites pass; genuine runtime qualification evidence exists for every claimed model/device feature; and the exact signed Store/release candidate passes packaging, installation, upgrade, rollback, accessibility, security, and customer-flow gates.

This document is the forward blueprint. It does not itself mark any gate complete.
