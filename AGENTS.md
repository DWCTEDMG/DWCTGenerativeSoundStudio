# AGENTS.md

## Visual Studio implementer / Codex reviewer coordination

For the user's current coordination workflow, read [STUDIO_PROGRESS.md](STUDIO_PROGRESS.md) before acting. Visual Studio Copilot owns implementation and the Implementer update section; Codex owns the Reviewer update section. WinUI 3 is the active product scope, with the shared Python backend supporting it.

In reviewer/monitor mode, inspect saved changes and available evidence without editing implementation, staging or committing another agent's work, pushing, launching, running builds/tests, or synchronizing dependencies in its active environment. A later user assignment can change that role. Re-read the handoff before narrow section edits and preserve the other writer's updates. Distinguish recorded baseline results, new observations, and currently verified candidate evidence.

Copilot instructions live in `.github/copilot-instructions.md`; the optional checkpoint prompt is `.github/prompts/studio-progress.prompt.md`. This file-based workflow does not expose either agent's live chat or unsaved buffers.

## Product / UX priority (user preference)

The **native WinUI 3 Studio UI is the priority**. When adding or changing functionality, surface it
in `studio/edmg-studio-winui/`, not just as a backend API endpoint or only in the React/Electron
compatibility client under `studio/edmg-studio/src/`. New backend capabilities should come with the
corresponding native controls (for example on Workspace, Render, Models, Settings, or the appropriate
specialist page) so users can drive them without curl/API calls. Assume the user wants every feature
available in WinUI unless they say otherwise.

The unified Workspace is the default guided control room for source media, reusable Whisper/audio
analysis, provider planning/BYOM, managed Qwen Director review, storyboard, Reactive Lab, and render
handoff. Keep AI Planner, Director, Storyboard, Reactive Lab, Timeline, Render, Models, and Settings
available as specialist surfaces; do not collapse or remove their expert workflows.

## Studio regression reference set

Before changing Studio architecture, Director/Reactive Lab handoffs, rendering, timeline behavior,
or the WinUI experience, check the implementation claims and acceptance criteria in all of these
records so completed milestone work is not accidentally removed:

- `studio/edmg-studio-winui/ChatLog3.md`
- `studio/edmg-studio-winui/ChatLog4.md`
- `C:\Users\user\Downloads\ChatLog5.md`
- `C:\Scripts\EDMG_Studio_Master_Blueprint_AI_DAW_Timeline.md`

The two external absolute paths are workstation reference records and may not exist in CI or on
another developer machine; their absence must not fail builds. Treat the master blueprint's
architecture phases 0-13 and its separate 14-item WinUI 3 Native Experience roadmap as distinct
checklists. A recent WinUI milestone does not prove that the corresponding professional DAW phase
is complete. Preserve and regression-test the Director-to-Reactive Lab draft recovery, reviewed
camera/motion keyframe persistence, render-profile compatibility, backend schema importability,
and WinUI XAML page compilation when touching related code.

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
- GPU-first policy: use automatic accelerator selection; CPU requires an explicit `--accelerator-profile cpu` or `EDMG_BACKEND_ACCELERATOR_PROFILE=cpu`. Never synchronize an existing GPU environment to CPU as a default.
- `scripts/run_pytest_scopes.py` preserves dependencies unless `--sync` is explicitly supplied. It detects/preserves CUDA, otherwise selects the Windows DirectML package lane, and fails without a supported GPU profile on other platforms. Runtime readiness remains separately validated.
- Python is pinned to 3.12 in the repository `.python-version`; use the pinned `uv` 0.11.28
  project environment rather than whichever interpreter or package installer is on `PATH`.
- From the repo root, validate and synchronize the baseline with
  `uv lock --project studio/edmg-studio/python_backend --check` followed by
  `uv run --project studio/edmg-studio/python_backend --frozen --no-sync python scripts/run_pytest_scopes.py --sync`.
- Start the backend with
  `uv run --project studio/edmg-studio/python_backend --frozen --no-sync python -m edmg_studio_backend serve --host 127.0.0.1 --port 7863`.
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
- Backend: `uv run --project studio/edmg-studio/python_backend --frozen --no-sync --group test python -m pytest` must exit 0. Test counts intentionally are not pinned here because they drift as coverage is added.
- Frontend: `pnpm run test:ui` must exit 0. The Windows-only
  `src/test/directorRuntime.test.ts` may log a hardcoded `C:\...` ENOENT message to stderr on Linux
  while the test and runner still pass; treat the exit code and assertions as authoritative.
- For a focused single-worker Vitest run, use `pnpm exec vitest run <test-file> --maxWorkers=1`.
  Vitest 4.1 does not accept the older `--minWorkers` option.
- `pnpm run lint` and `pnpm run typecheck` both pass clean on this branch (exit 0).
- Repo-level: the frozen uv project environment is the reliable green signal.
  Some repo-root orchestration tests may still fail on branches with in-flight render-tier work.
  Run both scopes with `uv run --project studio/edmg-studio/python_backend --frozen --no-sync --group test python scripts/run_pytest_scopes.py`.
  Proxy fallback coverage: `uv run --project studio/edmg-studio/python_backend --frozen --no-sync --group test python -m pytest tests/test_studio_proxy_fallback.py`.

### Storage
- Backend project data is written to `studio/edmg-studio/python_backend/data/` (gitignored) when
  `EDMG_STUDIO_HOME` is not set. Set `EDMG_STUDIO_HOME` to relocate data/models/cache/logs.

### Linux operator docs
- Canonical Linux packaging and Lightning setup: `studio/edmg-studio/packaging/linux/README.md`
- Lightning backend: `bash scripts/start_lightning_backend.sh` with `EDMG_BACKEND_ENV_MODE=active`
- HF bucket defaults ship in `launcher_env.defaults.json`; run `bash scripts/setup_linux_hf_bucket.sh`
- Remote backend switch: `bash scripts/set_studio_remote_backend.sh external https://...`
- Repo-level proxy-fallback tests in `tests/test_studio_proxy_fallback.py` should pass when run from repo root
