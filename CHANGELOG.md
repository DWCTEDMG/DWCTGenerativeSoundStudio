# Changelog

All notable changes to DWCT Generative Sound Studio are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and released versions follow semantic
versioning where the product packaging supports it. Dates use UTC where a specific release date is
recorded.

## [Unreleased]

The next desktop/backend candidate is version `1.2.0`. It is not a public release until the signed
artifact, clean-machine, previous-version upgrade, and hardware evidence gates in `RELEASE.md` pass.

### Added

- Shared system readiness service (`GET /v1/system/readiness`) and Settings panel covering FFmpeg,
  Python/uv runtime, GPU, disk, writable paths, and models.
- Locked Python toolchain via `uv` 0.11.28, Python 3.12, accelerator profiles, and committed
  `studio/edmg-studio/python_backend/uv.lock`.
- Small redistributable CC0 test fixture inventory under `tests/fixtures/` with golden
  project/analysis/schedule/media metadata and SHA-256 goldens.
- Versioned project manifests, SQLite job/event store, autosave journal + crash recovery UI,
  artifact manifests on internal renders, and Project Health.
- Extracted System and Project durability routers, typed API contracts for readiness, health, and
  recovery, Timeline undo/redo foundation, Music Graph compatibility adapter, and unified Render
  Queue job status helpers.
- Versioned v1 contracts and compatibility adapters for Project, Music Graph, Creative Intent,
  Render Plan, Artifact, capability, job, and cue documents.
- Modernization integration ledger and branch-policy documentation.
- Security reporting policy, root environment example, and explicit repository license posture.
- Named-hardware Day 1 benchmark harness for launch, project, timeline, analysis, Electron smoke,
  and Python test-scope timings.
- A read-only installed-app baseline lane for packaged upgrade proof, with independent baseline and
  candidate hashes, strict newer-version enforcement, path confinement, cleanup integrity checks,
  and evidence that the previous installation was unchanged.
- A separate `validate:release:production` gate that preflights Windows signing credentials before
  starting the full candidate pipeline and forces signing to fail closed.
- Pinned, checksum-verified Windows and Linux FFmpeg/FFprobe archives with the exact GPLv3 license,
  source/build commits, and packaged redistribution evidence.
- A host/target guarded Linux CPU/CUDA AppImage lane with profile-specific artifact names and a
  final packaged GUI/backend smoke gate suitable for native Linux or WSL2/WSLg.
- A canonical/compatibility ownership matrix and an explicit Triton provider promotion contract.
- A Settings build-identity summary for packaged desktop/backend versions, accelerator profile,
  Python runtime, and expandable source, binary, and dependency-lock fingerprints.
- A Models workflow that detects the four recognized root-level TensorRT engines under the active
  Studio Home, rejects incomplete or unsafe inputs, checks free space, streams a cancellable
  SHA-256-verified copy through an owned staging directory, and atomically publishes a schema-v1
  canonical bundle without moving, renaming, overwriting, or deleting the legacy sources. An
  engine-only copy remains explicitly not installed and not renderer-ready until its complete
  manifest-listed ONNX inventory, integer compiled profile, and matching Hub model ID plus immutable
  revision are explicitly verified.

### Security

- Updated Studio and Director dependency graphs so local development and production audits report
  zero known vulnerabilities at the recorded baseline.
- Added weekly Dependabot coverage for both pnpm package roots, the frozen `uv` backend project,
  and GitHub Actions security updates.
- Pinned patched transitive `brace-expansion` 1.1.18/2.1.4/5.0.9 and `fast-uri` 3.1.5 releases
  across Electron Builder, ESLint, and TypeScript ESLint, plus `js-yaml` 4.3.1 after the
  GHSA-5p4m-2wfm-xmqj disclosure, so both production-only and complete pnpm audits report no known
  vulnerabilities.
- Updated the packaged Director's transitive `fast-uri`, `ip-address`, and `hono` overrides to
  3.1.5, 10.3.1, and 4.12.34 for the current host-confusion, SSRF, and CORS ReDoS advisories.

### Changed

- Updated the Studio within its current compatibility majors to Hugging Face Hub 2.14.6,
  TypeScript ESLint 8.66.0, globals 17.9.0, PostCSS 8.5.26, and Vite 8.2.1. Framework and runtime
  major upgrades remain isolated for dedicated migration evidence.

### Fixed

- Launched the packaged Windows backend directly from Electron instead of through PowerShell, so a user shell policy, profile, or offline OneDrive configuration cannot prevent the bundled backend and GPU runtime from starting. Unknown pre-existing listeners are isolated onto a private port rather than reused.
- Included Faster-Whisper's required Silero VAD ONNX asset and distribution metadata in every packaged backend, and made release-manifest validation fail closed when that runtime asset is missing or empty.
- Stopped Faster-Whisper from downloading and trying every larger fallback model after a successful empty transcription of silence or music; the same model now receives the intended no-VAD retry, while model fallback remains available for real load or inference errors.
- Gave Windows CPU, DirectML, and CUDA installers profile-qualified names and made release evidence fail closed on mixed or stale installers, blockmaps, and updater metadata. Raw Electron Builder output now carries an explicit `unqualified` fallback name so it cannot be mistaken for a release package.
- Displayed the exact running desktop executable location in Settings build identity so installed, loose, and source copies can be distinguished when diagnosing version or accelerator-profile mismatches.
- Serialized the UI suite inside the canonical desktop release gate so Windows and Linux packaging cannot fail nondeterministically from an exhausted Vitest fork pool on build hosts.
- Isolated the strict Electron integration probe from stale launcher backend URLs by pinning the
  spawned test shell to its ephemeral mock backend.
- Fixed packaging import paths for `pyinstaller_support` in the PyInstaller spec and release
  provenance helper.
- Unified the desktop, backend package, FastAPI, health response, and stability-report version at
  `1.2.0`, with tooling and regression tests that reject future version drift.
- Corrected the Electron/browser `openExternal` bridge contract so production and test adapters
  consistently return the normalized opened URL.
- Preserved the exact server-resolved TensorRT bundle path through dedicated TensorRT video and
  SVD/AnimateDiff TensorRT-anchor execution. Public requests continue to provide stable model IDs,
  cannot substitute arbitrary local filesystem paths, and never trigger external-folder discovery.
- Unified TensorRT status, canonical/environment resolution, and standalone execution around one
  fail-closed bundle contract. A valid canonical bundle wins over external overrides; runtime uses
  the manifest-selected UNet engine after SHA-256 verification and loads auxiliary Diffusers
  components from the manifest-pinned base-model commit.
- Retired the legacy TensorRT Deforum service that deserialized an engine but generated simulated
  noise frames instead of running inference. Current Studio controls use the canonical internal
  TensorRT video path; the legacy URL and persisted job type remain compatibility-only adapters,
  explicitly report that Deforum schedules are not applied, and are covered by contract tests.
- Kept backend-resolved TensorRT bundle paths out of newly persisted public job payloads, injected
  them only into in-memory worker payloads, redacted private model paths from public preflight
  evidence, bounded standalone/compatibility request workloads, and marked the old route deprecated
  in OpenAPI.
- Removed the obsolete `--minWorkers` flag from the Studio CI command so the frontend suite is
  compatible with Vitest 4 while retaining the single-worker ceiling used on constrained runners.
- Added the existing zero-warning frontend lint command to the desktop validation chain inherited
  by release and production validation, with a release-toolchain regression assertion.
- Made packaged customer, upgrade, and zero-state proofs hermetic so they cannot inherit or mutate
  a developer's real Studio storage, backend URL, authentication, or installed application state.
- Bound Windows backend/helper Authenticode signatures to the exact packaged manifest hashes after
  Electron Builder copies and signs those files; production rejects the wrong signer, and unsigned
  local candidates remain explicitly non-promotable.
- Rebuilt the large-payload Inno contract around a fresh archive and integrity sidecar, signed
  Setup/uninstaller support, and exact app-owned upgrade cleanup without a recursive install-root
  wildcard.

## [1.1.0] - 2026-07-14

This section records the package-version baseline at commit `ce195b8`; no matching release tag was
present when the modernization ledger was created.

### Added

- Existing Studio desktop, backend, Render Conductor, Visual DNA, timeline, audio-analysis, model,
  Unreal preview/export, and live-control foundations used as the modernization baseline.

[Unreleased]: https://github.com/DWCTEDMG/DWCTGenerativeSoundStudio/compare/ce195b8...HEAD
[1.1.0]: https://github.com/DWCTEDMG/DWCTGenerativeSoundStudio/tree/ce195b8
