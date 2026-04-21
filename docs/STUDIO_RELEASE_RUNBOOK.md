# EDMG Studio Release Runbook

This runbook is for operators and end users installing the packaged Studio app
without terminal work.

## 1. First install

1. Run the packaged Windows installer.
2. Choose the app install directory if you do not want the default location.
3. Launch EDMG Studio.
4. Open `Setup`.
5. Pick a `Studio Home` on the drive you want for heavy runtime storage, such as
   `D:\EDMG-Studio`.

The packaged app install directory and `Studio Home` are intentionally separate:

- install directory: the app itself
- Studio Home: projects, models, cache, logs, external tools, and Electron data

## 2. Choose storage roots

Studio manages separate roots under `Studio Home` by default:

- `data`
- `models`
- `cache`
- `logs`
- `external`

If you keep the default managed layout, Studio will place these under:

```text
<Studio Home>\data
<Studio Home>\models
<Studio Home>\cache
<Studio Home>\logs
<Studio Home>\external
```

Studio also manages:

- Ollama models under `<Studio Home>\models\ollama`
- Electron app/session data under `<Studio Home>\electron`

If you change roots from an older layout, Studio queues a migration and applies
it on restart.

## 3. Choose AI provider

Open `Settings` to choose the planning provider.

Supported first-class paths:

- `Ollama`
  - zero-cost local default
- `OpenAI-compatible`
  - local or hosted endpoints that expose an OpenAI-style API
- `Remote AI service`
  - separate HTTP AI service endpoint
- `Rule-based fallback`
  - no paid model dependency

Provider notes:

- If you choose `Ollama`, `Setup` will help verify/install the local path.
- If you choose `OpenAI-compatible`, set the base URL, model, and API key in
  Studio Settings.
- If you choose `Remote AI service`, provide the service URL in Settings.
- If you choose `Rule-based fallback`, Studio should not force Ollama install.

## 4. Install models and tools

From `Setup`:

- verify bundled FFmpeg
- verify/install the managed 7-Zip portable tool
- verify/install Ollama under the Studio-managed `external\ollama` root when Ollama is your chosen provider
- verify/download ComfyUI Portable if you want the local ComfyUI path

From `Models`:

- install curated Hugging Face models
- import supported Civitai assets
- bring your own local model files

## 5. First project proof

Use this path to confirm the install is healthy:

1. Create a project.
2. Upload a WAV or other supported audio file.
3. Run `Analyze`.
4. Generate a plan.
5. Apply the plan to the timeline.
6. Run a fast render.
7. Verify the output appears under `Outputs`.

## 6. Upgrade and migration recovery

If you are moving from an older `C:\`-based layout:

1. Set the new `Studio Home`.
2. Save and restart Studio.
3. Wait for the queued migration to complete.
4. Re-open `Setup` and confirm the migration status shows success.

Expected migrated categories:

- project data
- models
- cache
- logs
- external tools
- most Electron user data

## 7. Common recovery steps

### Setup says FFmpeg is missing

- packaged Studio should prefer its bundled FFmpeg
- if that fails, rebuild the package and re-run `Setup`

### Ollama is selected but not available

- use `Setup` to install or repair Ollama into the Studio-managed external tools root
- confirm the managed models directory lives under `models\ollama`
- confirm the managed executable lives under `external\ollama\ollama.exe`

### ComfyUI is reachable but unusable

- Studio should fall back to proxy/internal render paths when the configured
  checkpoint/runtime is not actually usable
- verify the render recommendation in `Render` or pipeline validation

### Old data still appears split across drives

- confirm `Studio Home` points at the desired target root
- restart Studio so the pending migration can run
- confirm migration status in `Setup`

### Packaged release proof

Operators should run:

```powershell
cd studio/edmg-studio
pnpm run check:tooling
pnpm run validate:release
```

That includes:

- pnpm/package-manager and lockfile guardrails
- staged desktop validation
- packaged customer-flow proof
- packaged upgrade-proof migration test
- packaged zero-state setup proof for Studio-managed Ollama and 7-Zip

Canonical packaged desktop version source:

- `studio/edmg-studio/package.json#version`
