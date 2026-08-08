# AGENTS.md

## Product / UX priority (user preference)

The **Studio UI is the priority**. When adding or changing functionality, surface it in the
Studio desktop UI (`studio/edmg-studio/src/`), not just as a backend API endpoint. New backend
capabilities should come with the corresponding UI controls (e.g. on the Render, Workspace,
Models, or Settings pages) so users can drive them without curl/API calls. Assume the user wants
every feature available in the UI unless they say otherwise.

## Cursor Cloud specific instructions

EDMG Studio is a music-reactive AI video generation studio. The product lives under
`studio/edmg-studio/` and has two services that matter for local development:

- **Backend** — FastAPI app in `studio/edmg-studio/python_backend/` (port `7863`).
- **Frontend** — React/Vite app in `studio/edmg-studio/` (Vite dev server on port `5173`),
  normally wrapped by an Electron shell.

The update script already installs all dependencies (frontend `pnpm install` and a frozen
backend `uv sync` from `studio/edmg-studio/python_backend/uv.lock`).
The notes below are the non-obvious gotchas; standard commands live in the root `README.md`,
`studio/edmg-studio/README.md`, and the `package.json` scripts.

### Python
- Python is pinned to 3.12 in the repository `.python-version`; use the pinned `uv` 0.11.28
  project environment rather than whichever interpreter or package installer is on `PATH`.
- From the repo root, validate and synchronize the baseline with
  `uv lock --project studio/edmg-studio/python_backend --check` followed by
  `uv sync --project studio/edmg-studio/python_backend --frozen --extra cpu --extra core --extra audio --group test --group lint`.
- Start the backend with
  `uv run --project studio/edmg-studio/python_backend --frozen --extra cpu --extra core --extra audio python -m edmg_studio_backend serve --host 127.0.0.1 --port 7863`.
- Ollama and ComfyUI are **not** installed here. Set `EDMG_AI_PROVIDER=rule_based` so planning
  uses the built-in `RuleBasedPlanner` (no LLM server needed). The create→upload→analyze→plan
  flow works fully with the rule-based provider; only actual model rendering needs GPU + model
  downloads that are not present.

### Frontend / pnpm
- Always run `pnpm` from inside `studio/edmg-studio`. Run from the repo root and corepack picks a
  newer pnpm (v11) that fails the pinned `packageManager` (10.33.0) version check.
- `pnpm run dev` runs Vite **and** Electron concurrently; Electron cannot launch headless in the
  cloud VM. To exercise the UI in a browser, run Vite alone:
  `pnpm exec vite --host 127.0.0.1 --port 5173 --strictPort`.
- Backend CORS is open, so a browser can call the backend cross-origin without extra config.
- **Browser-only backend selection:** plain-browser Vite sessions default safely to
  `http://127.0.0.1:7863`. Use
  `http://127.0.0.1:5173/?backendUrl=https://...` to override that default for a remote backend.
  `src/components/api.ts` keeps the browser fallback independent from the Electron bridge so URL
  resolution cannot recurse; `src/test/api.test.ts` carries the regression coverage.

### Tests
- Backend: `uv run --project studio/edmg-studio/python_backend --frozen --extra cpu --extra core --extra audio --group test python -m pytest` must exit 0. Test counts intentionally are not pinned here because they drift as coverage is added.
- Frontend: `pnpm run test:ui` must exit 0. The Windows-only
  `src/test/directorRuntime.test.ts` may log a hardcoded `C:\...` ENOENT message to stderr on Linux
  while the test and runner still pass; treat the exit code and assertions as authoritative.
- For a focused single-worker Vitest run, use `pnpm exec vitest run <test-file> --maxWorkers=1`.
  Vitest 4.1 does not accept the older `--minWorkers` option.
- `pnpm run lint` and `pnpm run typecheck` both pass clean on this branch (exit 0).
- Repo-level: the frozen uv project environment is the reliable green signal.
  Some repo-root orchestration tests may still fail on branches with in-flight render-tier work.
  Run both scopes with `uv run --project studio/edmg-studio/python_backend --frozen --extra cpu --extra core --extra audio --group test python scripts/run_pytest_scopes.py`.
  Proxy fallback coverage: `uv run --project studio/edmg-studio/python_backend --frozen --extra cpu --group test python -m pytest tests/test_studio_proxy_fallback.py`.

### Storage
- Backend project data is written to `studio/edmg-studio/python_backend/data/` (gitignored) when
  `EDMG_STUDIO_HOME` is not set. Set `EDMG_STUDIO_HOME` to relocate data/models/cache/logs.

### Linux operator docs
- Canonical Linux packaging and Lightning setup: `studio/edmg-studio/packaging/linux/README.md`
- Lightning backend: `bash scripts/start_lightning_backend.sh` with `EDMG_BACKEND_ENV_MODE=active`
- HF bucket defaults ship in `launcher_env.defaults.json`; run `bash scripts/setup_linux_hf_bucket.sh`
- Remote backend switch: `bash scripts/set_studio_remote_backend.sh external https://...`
- Repo-level proxy-fallback tests in `tests/test_studio_proxy_fallback.py` should pass when run from repo root
