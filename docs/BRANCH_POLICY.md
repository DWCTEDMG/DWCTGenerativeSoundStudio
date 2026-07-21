# Branch and release policy (P0-02)

## Purpose

Keep a stable integration lane while feature work continues on short-lived branches.

## Required lanes

| Lane | Branch pattern | Purpose |
| --- | --- | --- |
| Integration | `codex/uv-integration` (current) / eventual `develop` | Daily integration of blueprint work packages |
| Release | `release/x.y` | Freeze for packaging, SBOM, and clean-machine smoke |
| Default / production | `main` (when adopted) | Only merges that pass required checks |

## Rules

1. Prefer small PRs mapped to one blueprint WP or day-lane deliverable.
2. Required checks before merge: frozen `uv lock --check`, backend pytest (CPU profile), frontend typecheck/lint/tests, and Studio workflow FFmpeg-aware jobs.
3. Do not force-push shared integration or release branches.
4. Experimental model work must stay behind capability/lane flags and must not claim production readiness without benchmark evidence.
5. Hotfixes may branch from the active release lane and cherry-pick back to integration.

## Review expectations

- Behavior changes include tests.
- Schema/migration changes include rollback notes.
- UI-facing backend work includes Studio controls, not API-only surfaces.
