# Project format

## `project.json`

Projects are stored under `<studio-home>/data/projects/<project_id>/project.json`.

Required fields:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Stable project id |
| `name` | string | Display name |
| `created_at` | string | `YYYY-MM-DD HH:MM:SS` |
| `meta` | object | Timeline, audio, analysis, plans, Visual DNA refs |
| `schema_version` | int | Current: `1` |

Saves are atomic (`project.json.tmp` → replace). Loading migrates older documents and writes a `project.vN.<stamp>.bak.json` backup before persisting the upgrade.

## Autosave and recovery

| Path | Role |
| --- | --- |
| `autosave.journal.json` | Dirty in-progress meta journal |
| `autosave/snapshot-*.json` | Bounded recovery snapshots |

`GET /v1/projects/{id}/recovery` reports dirty journals. Apply or discard through the Timeline recovery controls.

## Jobs

Job truth lives in `<studio-home>/data/jobs.sqlite` (WAL). Per-project `jobs/*.json` mirrors remain for older tooling. Job events are queryable at `GET /v1/projects/{id}/jobs/{job_id}/events`.

## Artifacts

Internal renders write `<output>.mp4.artifact.json` beside the video with content hash, engine, model id, params, lineage, and review state.

## Music Graph

`GET /v1/projects/{id}/music_graph` adapts existing analysis meta into Music Graph v1 (`schemaVersion: "1.0"`). Legacy projects keep working without re-analysis; bars may be empty until a fresh analysis run.
