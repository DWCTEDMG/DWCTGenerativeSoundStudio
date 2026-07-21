# Changelog

All notable product and packaging changes for DWCT Generative Sound Studio are
tracked here. Dates use UTC.

## Unreleased

### Added

- Shared system readiness service (`GET /v1/system/readiness`) and Settings panel
  covering FFmpeg, Python/uv runtime, GPU, disk, writable paths, and models.
- Locked Python toolchain via `uv` 0.11.28, Python 3.12, accelerator profiles,
  and committed `studio/edmg-studio/python_backend/uv.lock`.
- Small redistributable test fixture inventory under `tests/fixtures/` with
  golden project/analysis/schedule/media metadata.
- Versioned project manifests, SQLite job/event store, autosave journal + crash
  recovery UI, artifact manifests on internal renders, and Project Health.
- Extracted System/Project durability routers, typed API contracts for readiness/
  health/recovery, Timeline undo/redo foundation, Music Graph compatibility
  adapter, and unified Render Queue job status helpers.

### Fixed

- Packaging import paths for `pyinstaller_support` in the PyInstaller spec and
  release provenance helper.
