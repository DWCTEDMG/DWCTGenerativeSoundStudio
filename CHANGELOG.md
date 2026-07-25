# Changelog

All notable changes to DWCT Generative Sound Studio are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and released versions follow semantic
versioning where the product packaging supports it. Dates use UTC where a specific release date is
recorded.

## [Unreleased]

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

### Security

- Updated Studio and Director dependency graphs so local development and production audits report
  zero known vulnerabilities at the recorded baseline.
- Added weekly Dependabot coverage for both pnpm package roots, the frozen `uv` backend project,
  and GitHub Actions security updates.

### Fixed

- Isolated the strict Electron integration probe from stale launcher backend URLs by pinning the
  spawned test shell to its ephemeral mock backend.
- Fixed packaging import paths for `pyinstaller_support` in the PyInstaller spec and release
  provenance helper.

## [1.1.0] - 2026-07-14

This section records the package-version baseline at commit `ce195b8`; no matching release tag was
present when the modernization ledger was created.

### Added

- Existing Studio desktop, backend, Render Conductor, Visual DNA, timeline, audio-analysis, model,
  Unreal preview/export, and live-control foundations used as the modernization baseline.

[Unreleased]: https://github.com/DWCTEDMG/DWCTGenerativeSoundStudio/compare/ce195b8...HEAD
[1.1.0]: https://github.com/DWCTEDMG/DWCTGenerativeSoundStudio/tree/ce195b8
