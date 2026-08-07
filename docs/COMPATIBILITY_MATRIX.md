# EDMG Studio Compatibility Matrix

Last reviewed: 2026-08-06

## Canonical ownership

- Desktop product: `studio/edmg-studio`
- Backend API: `studio/edmg-studio/python_backend/edmg_studio_backend`
- Bundled EDMG engine: `studio/edmg-studio/python_backend/enhanced_deforum_music_generator`
- Python release lock: `studio/edmg-studio/python_backend/uv.lock`
- Project state: versioned project manifest and domain documents under Studio Home
- Jobs: SQLite/WAL job and event store
- Renderer: Studio internal renderer, with external providers behind adapters
- User controls: Studio React UI; raw configuration is diagnostic/advanced only

Compatibility code may translate an older contract into these canonical systems. It must not own a
second source of truth.

## Active compatibility paths

| Compatibility path | Supported consumer | Canonical target | Required evidence | Removal condition |
|---|---|---|---|---|
| Root `enhanced_deforum_music_generator` wrapper | Repo-root tests and older Python entry points | Bundled backend engine package | Import parity and engine golden tests | All supported entry points import the canonical package directly |
| Root `utils` wrapper | Older `utils.*` imports | `enhanced_deforum_music_generator.utils` | Static import inventory and unit parity | Import inventory is empty for one supported release |
| Root `config`, `core`, and `edmg` wrappers | Older engine scripts | Bundled backend packages | CLI/import smoke tests | Supported launchers no longer reference them |
| Root `librosa` shadow package | Source-tree tests on incompatible environments | Declared `librosa` dependency plus project-namespaced fallback | Audio-analysis goldens on CPU and packaged backend | Fallback is project-namespaced and Python-upgrade matrix is green |
| Root install/start/setup scripts | Standalone-engine users | Root Studio launchers and in-app Setup | Clean install migration guide and Studio setup proof | Announced migration window ends and no supported workflow consumes them |
| `desktop/electron` | Older JSON-first desktop shell | Canonical Studio Electron shell | Legacy launch inventory and migration documentation | One supported release after deprecation, with no maintained consumer |
| Legacy project fields | Existing project folders | Versioned project/domain schemas | Round-trip, migration backup, unknown-field preservation, rollback | Never removed without a schema migration and supported-version policy |
| Legacy setup `bundle`/`flavor` inputs | Older desktop/setup clients | Exact accelerator profile | Request-contract and conflict tests | Supported clients all send the exact profile field |
| JSON job mirrors | Older diagnostics/tools | SQLite jobs/events | Restart/recovery and mirror parity tests | Export/migration exists and mirror-read inventory is empty |
| Public native-media GET compatibility | Electron `<audio>`, `<video>`, and image elements | Authenticated backend media access | Path confinement, read-only allowlist, remote-auth tests | All supported clients use authenticated media fetch/blob URLs |
| Browser development bridge | Vite/browser-only development | Electron preload contract | Shared TypeScript contract, URL security, adapter parity tests | Retain while browser development is supported |
| Root-level legacy TensorRT engines in the active Studio Home | Existing pre-1.2 local engine sets | `models/internal/tensorrt/local_sd15_tensorrt_bundle` | Read-only detection; safe-file and disk preflight; source-preserving, cancellable, hash-verified atomic copy; renderer-readiness tests | At least one supported release has shipped the explicit migration and supported-install telemetry or support inventory no longer finds the legacy layout |
| `/render/tensorrt-deforum` and persisted `tensorrt_deforum` jobs | Older Studio clients and queued jobs | Canonical internal-video execution with `render_mode=tensorrt` while preserving the deprecated public job type | Route/job/OpenAPI contract tests; explicit `legacy_deforum_schedule_applied=false`; current UI route inventory | No supported client calls the URL and supported persisted-job inventory is empty for one release |
| ComfyUI workflows | Optional external renderer users | Studio render plan/provider contract | Capability, cancellation, artifact, provenance, and fallback tests | Not scheduled; adapter remains optional while supported |
| ChatGPT EDMG Director sidecar | ChatGPT/MCP workflows | Studio backend project and planning contracts | Contract tests and managed-sidecar packaging | Retain while product-supported; never fork project state |

## Enforcement rules

1. New product code must not import a root compatibility package when a canonical package exists.
2. A compatibility adapter must identify the old input contract, canonical output contract, owner,
   tests, and removal condition.
3. Unknown persisted fields must be preserved under a versioned extension boundary or rejected with
   an actionable migration error; they must not be silently discarded.
4. Compatibility code may translate, validate, and warn. It may not create a parallel project,
   job, model, settings, or render store.
5. Deprecation diagnostics must be structured and must not expose paths, secrets, or raw exception
   bodies to remote clients.
6. Removal requires static import/route inventory, migration fixtures, supported-version policy,
   release notes, rollback instructions, and clean-machine proof.
7. Compatibility routes and fields remain covered by contract tests until the same release that
   removes them.

## Pull-request checklist

When a change touches a path in this matrix, record:

- old and canonical contracts;
- whether the change is read-compatible, write-compatible, or breaking;
- migration and rollback behavior;
- affected Studio UI;
- tests proving existing projects and renders still work; and
- whether the removal condition moved closer or a new dependency was introduced.
