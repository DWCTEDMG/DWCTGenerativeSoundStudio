# Studio v1 contracts

The version 1 contract family freezes the JSON exchanged between Studio domains while preserving
the current project store, APIs, Render Conductor, and renderer implementations.

## Contract family

Every top-level document carries `schema_version: "1.0"`, a stable `id`, `created_at`, and
`updated_at`. The eight frozen names are:

| Contract | Purpose |
|---|---|
| `edmg.project` | Authored project state and references to derived documents |
| `edmg.music_graph` | Canonical time-aware music analysis shared by consumers |
| `edmg.creative_intent` | Engine-neutral authored direction and constraints |
| `edmg.render_plan` | Inspectable task DAG, allocations, estimates, and warnings |
| `edmg.artifact` | Output provenance, hashes, lineage, review, safety, and license state |
| `edmg.capability` | Provider-neutral media operations and controls |
| `edmg.job` | Durable execution state vocabulary |
| `edmg.cue` | Time-aware internal and external live-control events |

The authoritative Python models and JSON Schema generator live in
`studio/edmg-studio/python_backend/edmg_studio_backend/contracts/`. The matching frontend types
live in `studio/edmg-studio/src/contracts/v1.ts`. Persisted field names use snake case on both sides
so browser, Electron, Python, project files, and external adapters exchange one representation.

## Compatibility rule

Version 1 is additive. Existing `project.json`, job JSON, Render Conductor plans, and Unreal or
workbench cues remain valid in their current paths. Compatibility adapters convert those shapes to
the frozen contracts and retain unknown legacy fields under `extensions` rather than discarding
them. This is the boundary future migrations must use before changing stored formats.

The canonical internal renderer remains
`studio/edmg-studio/python_backend/edmg_studio_backend/services/internal_video.py`. Contracts may
wrap its inputs and outputs, but contract work must not duplicate or replace that implementation.

## Change policy

- Backward-compatible optional fields may be added within v1 only with Python and TypeScript tests.
- Required-field, semantic, enum, or representation changes require a new schema version and an
  explicit migration adapter.
- Unknown fields are rejected at frozen contract boundaries; legacy adapters are responsible for
  retaining existing extension data.
- JSON Schema changes, frontend type changes, adapters, fixtures, and documentation land together.

## Verification

Run the focused contract checks before the wider Studio gates:

```powershell
cd studio/edmg-studio/python_backend
py -3.12 -m pytest edmg_studio_backend/tests/test_contracts_v1.py -q

cd ..
pnpm exec vitest run src/test/contracts.test.ts --maxWorkers=1
pnpm run typecheck
```
