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

The update script already installs all dependencies (frontend `pnpm install` and backend
`pip install -e ".[studio_bundle,test]"`, which includes torch/diffusers/transformers/librosa).
The notes below are the non-obvious gotchas; standard commands live in the root `README.md`,
`studio/edmg-studio/README.md`, and the `package.json` scripts.

### Python
- Use `python3` (there is no `python` alias on this VM). The README uses `python`.
- The backend console script `edmg-studio-backend` installs to `~/.local/bin`, which is **not**
  on `PATH`. Start the backend with the module form instead:
  `cd studio/edmg-studio/python_backend && python3 -m edmg_studio_backend serve --host 127.0.0.1 --port 7863`.
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
- **Browser-only gotcha:** when running Vite in a plain browser (no Electron), open the UI with the
 backend URL as a query param:
 `http://127.0.0.1:5173/?backendUrl=http://127.0.0.1:7863`. Without it the app fails to load
 because the browser fallback in `src/components/api.ts` recurses infinitely (`getBackendUrl()`
 calls `window.edmg.backendUrl()` which `ensureBrowserBridge()` wires back to `getBackendUrl()`).
 This path never triggers under Electron (preload supplies `window.edmg`), so it is a
 browser-dev-only quirk, not a setup problem.

### Tests (known results on Linux)
- Backend: `cd studio/edmg-studio/python_backend && python3 -m pytest` → 105 pass.
- Frontend: `pnpm run test:ui` → 48 pass (23 files). The Windows-only
 `src/test/directorRuntime.test.ts` logs a hardcoded `C:\...` ENOENT error to stderr but still
 passes; the runner exits 0. This stderr noise is a pre-existing platform quirk, not a failure.
- `pnpm run lint` has **3 pre-existing errors** (unused vars in `src/pages/Render.tsx` and
 `src/pages/Settings.tsx`); `pnpm run typecheck` passes clean. The lint errors are code issues,
 not environment problems.
- Repo-level: `python3 -m pytest` from the repo root has **7 pre-existing failures**
  (`test_azure_model_cache`, `test_studio_render_tiers`, `test_studio_sd_feature_slice`) caused by
  test/code mismatches (e.g. expected log text and model-selection logic), unrelated to environment
  setup; the other 55 pass / 5 skip.

### Storage
- Backend project data is written to `studio/edmg-studio/python_backend/data/` (gitignored) when
  `EDMG_STUDIO_HOME` is not set. Set `EDMG_STUDIO_HOME` to relocate data/models/cache/logs.
