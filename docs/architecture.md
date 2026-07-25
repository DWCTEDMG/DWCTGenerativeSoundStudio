# Architecture

## Goals
- EDMG Studio provides a desktop UI (Electron) backed by a local FastAPI service.
- The backend exposes a stable JSON API envelope: `{ "ok": true|false, ... }`.
- Errors intended for users follow a structured `UserFacingError` format.

## High-level components
### Desktop App (Node/TS)
- Package root: `studio/edmg-studio/`
- Package manager: `pnpm@10.33.0` via `packageManager`
- Typecheck: `pnpm run typecheck`
- Dev: `pnpm run dev`

### Python Backend (FastAPI)
- Toolchain: Python 3.12 and uv 0.11.28 with committed `uv.lock`
- Run: `uv run --project studio/edmg-studio/python_backend --frozen --extra cpu --extra core --extra audio python -m edmg_studio_backend serve --host 127.0.0.1 --port 7863`
- `edmg_studio_backend/app.py` sets up routes + exception handlers
- `edmg_studio_backend/errors.py` defines user-facing error model
- Logging via `enhanced_deforum_music_generator/utils/logging_utils.py`

## Data flow
1. UI triggers an action (generate / render / process).
2. UI calls backend endpoint.
3. Backend validates input, runs the job, logs progress.
4. Backend returns `{ ok: true, ... }` or `{ ok: false, error: {...} }`.

## Conventions
### API envelope
- Success: `{ "ok": true, "data": ... }` or `{ "ok": true, ... }`
- Failure: `{ "ok": false, "error": { "message": "...", "hint": "...", "code": "..." } }`

### Errors
- Prefer raising `UserFacingError(message, hint, code, status_code)`
- Unknown exceptions map to `{ ok:false, error:{ code:"INTERNAL" } }`

### Logging
- Use the project logger helper to keep formatting consistent
- Avoid printing secrets/tokens/API keys

## Testing
- Check the backend lock before synchronization: `uv lock --project studio/edmg-studio/python_backend --check`.
- Combined Python scope from the repo root: `uv run --project studio/edmg-studio/python_backend --frozen --extra cpu --extra core --extra audio --group test python scripts/run_pytest_scopes.py`.
- CI, cloud bootstraps, and release builds consume the same frozen project; see
  [`PYTHON_TOOLCHAIN.md`](PYTHON_TOOLCHAIN.md).
- Node/TS: Vitest + jsdom smoke tests under `studio/edmg-studio/src/test`
