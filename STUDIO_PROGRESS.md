# Studio implementation and review handoff

## Purpose and ownership

The user has chosen Visual Studio Copilot as the implementer and Codex as the reviewer for the current WinUI 3 work. This is the shared progress handoff, not another blueprint or a release certificate.

- Forward scope: [WinUI 3 consolidated blueprint](blueprint/WINUI3_CONSOLIDATED_BLUEPRINT.md).
- Detailed phase acceptance/history: [planning.md](blueprint/planning.md).
- Project instructions and regression references: [AGENTS.md](AGENTS.md).
- WinUI 3 is the current product focus. Preserve existing projects, reviewed Director/Reactive drafts, exact timeline data, and working release paths.
- Saved files are shared. Copilot's live conversation, unsaved buffers, and terminal output are not automatically shared with Codex.

## How to use this handoff

1. Copilot reads this file and `.github/copilot-instructions.md` at a natural checkpoint, then updates only **Implementer update** below. The reusable prompt is `.github/prompts/studio-progress.prompt.md`.
2. Copilot reports at task start, after a meaningful milestone or validation result, when blocked, and before handing back to the user. Keep the update short and include UTC time, base commit, exact scope, and evidence paths.
3. Codex reads saved changes, this handoff, and available evidence, then updates only **Reviewer update** below. Observations are labeled separately from the implementer's own report.
4. Re-read the latest file before making a narrow section edit. Preserve the other writer's section. Do not replace the whole file from an older copy.
5. In reviewer/monitor mode, Codex does not edit implementation, stage or commit another agent's work, push, build, launch, change dependency profiles, or run tests against the implementer's active environment. A later user request can explicitly assign such work.
6. Review findings are requests to evaluate within the existing task, not automatic permission to expand scope. A reader must never infer a pass, completion, or release approval from another agent's intention.
7. Every test/build result needs its command, working directory, exit code, count or summary, timestamp, candidate commit plus dirty state, and saved log path when available. Mark missing evidence and tests not run explicitly. Keep credentials and private keys out of this file and its logs.

### Activate in the current Visual Studio chat

Paste this once at a natural checkpoint:

> Read `.github/copilot-instructions.md` and `STUDIO_PROGRESS.md`. Continue your current authorized WinUI task as implementer. Update only the Implementer update section with your current task, completed and remaining work, owned files, exact test/build results and log paths, blockers, and next step. Keep it updated at meaningful checkpoints and read Reviewer update for findings to assess.

Visual Studio supports repository instructions when its custom-instructions option is enabled; the file should appear in a Copilot response's References list. Writing these files does not prove the running Copilot chat has loaded them. If necessary, enable the option under Tools > Options > GitHub > Copilot > Copilot Chat. See [Microsoft's instructions documentation](https://learn.microsoft.com/en-us/visualstudio/ide/copilot-chat-context?view=visualstudio).

## Implementer update

<!-- IMPLEMENTER-UPDATE-START: Visual Studio Copilot owns this section. -->

**Acknowledgement:** Repository instructions and the latest Reviewer update were loaded. Existing dirty backend/runtime work is preserved; CUDA and dependency profiles were not synchronized.

- Updated UTC: 2026-09-24T13:55:07Z. Task / gate: commit and publish the completed `Cosmic` product repairs to the configured default branch; renderer qualification remains a separate unfinished runtime activity.
- Branch / base / state: `codex/Unified` at `7ede6a0ea8884b123653b4cba9392cfb407ab57c`, three commits ahead of `origin/codex/Unified`; dirty with the completed Director, Workspace, Timeline, SVD, audio, preview, TensorRT-source, and runtime-registry implementation/test set. Unrelated untracked `agents/` files remain excluded.
- Owned paths: managed Director runtime/workflow and focused tests; native Workspace/Timeline UX and backend media/editor contracts/tests; `PreviewRendererSession.cs`; TensorRT source/runtime routing and tests; this implementer section only.
- Completed: dense and GGUF Director routes expose automatic/all or explicit multi-GPU placement with provenance; long-form scene intent is processed in validated bounded windows; Workspace actions create revision-safe checkpoints without mandatory manual Save, while Save and Apply remain distinct. `Cosmic` revision 42 now has canonical primary asset `28e9f99bdc5d4cee85bafeaabb0576fb` and exactly one Timeline clip from sample 0 through 15,839,750 (329.9948 s). Timeline supports native import and same-project refresh through the existing `WindowsAudioEngine`. The Direct2D source-frame path now uses a persistent bitmap plus `CopyFromMemory`; the rebuilt native app selected and played the proven SVD artifact without the previous `WINCODEC_ERR_INVALIDPARAMETER` failure.
- Validation: repository-root media route test `studio\edmg-studio\python_backend\.venv\Scripts\python.exe -m pytest studio\edmg-studio\python_backend\edmg_studio_backend\tests\test_media_pool_service.py -q` exited 0 with `13 passed, 1 warning`; log `%TEMP%\edmg-audio-route-tests-20260924.log`. Earlier combined media/editor coverage exited 0 with `104 passed, 1 warning`; log `%TEMP%\edmg-audio-tests-20260924.log`. After stopping exact stale Studio PID 23160, `dotnet clean studio\edmg-studio-winui\EdmgStudio.WinUI.csproj -c Debug -p:Platform=x64 -v:minimal` and `dotnet build studio\edmg-studio-winui\EdmgStudio.WinUI.csproj -c Debug -p:Platform=x64 --no-restore -v:minimal` exited 0 with 0 warnings/0 errors; log `%TEMP%\edmg-winui-clean-rebuild-audio-20260924.log`. Fresh Debug PID 98724 reports `Cosmic`, 15 clips/4 tracks, and `Remote Audio · 48000 Hz · 1 clip`; automated native transport entered Pause, advanced, sought to 30 s, resumed, and Stop returned to zero. This proves graph/transport execution, not human-confirmed audible output. Native SVD preview reached `Pause video preview` in both pre-build and rebuilt processes. No dependency synchronization occurred.
- Remaining / blockers / next step: resume AnimateDiff with strict TensorRT and fallback disabled and require receipt-proven acceleration, then render and qualify LTX 2.5, with Hunyuan last. Human-confirmed physical-device audibility remains unclaimed; native graph and transport behavior are qualified.
- Reviewer findings addressed: capability claims remain evidence-based; package-aware paths and WSL retry changes are preserved; route-level upload/locked-track coverage now passes; no dependency sync, GPU-profile replacement, feature removal, or silent fallback is authorized.

<!-- IMPLEMENTER-UPDATE-END -->

## Reviewer update

<!-- REVIEWER-UPDATE-START: Codex owns this section. -->

**Observed UTC:** 2026-09-23T03:26:00Z. The user explicitly reassigned Codex from reviewer-only monitoring to full Studio diagnostics and repair.

**Baseline and root causes:** `codex/Unified` at `1c0e95fe5624bfcfa29338415eff954f404974a3`, plus the implementer's saved Settings changes. The 02:26 and 02:29 unhandled navigation failures were traced to XAML `SelectionChanged` running before later controls existed and unpackaged Debug calling `ApplicationData.Current.LocalSettings`. The same unpackaged storage assumption also existed in Reactive Lab recovery and Timeline audio/post-alignment caches. WSL GPU discovery made one attempt and left local Director auto-start failed when that attempt raced WSL initialization.

**Repairs:** preserve the Settings initialization gate and package-identity guard; add package-aware filesystem roots for unpackaged Reactive Lab and Timeline workflows without changing packaged paths; retry WSL `nvidia-smi` discovery up to three times with bounded cancellation-aware delays. Added focused storage-path and transient-WSL regression tests using red/green verification. Existing untracked `.github/agents/` and `studio/edmg-studio-winui/TextFile1.txt` remain untouched.

**Fresh evidence (repository root unless stated otherwise; no dependency sync):**

| Gate | Result | Evidence |
| --- | --- | --- |
| Frozen aggregate Python scopes | Exit 0; repository 174 passed/6 skipped; backend 1082 passed/5 skipped | `%TEMP%\edmg-full-diagnostics-20260923-030619\backend-tests.log` |
| Final WinUI Core suite | Exit 0; 564 passed/3 skipped external native-VST3 cases | `%TEMP%\edmg-full-diagnostics-20260923-030619\winui-core-tests-final.log` |
| Final WinUI Release x64/XAML build | Exit 0; 0 warnings/0 errors | `%TEMP%\edmg-full-diagnostics-20260923-030619\winui-release-build-final.log` |
| Frontend typecheck and lint | Both exit 0 | `%TEMP%\edmg-full-diagnostics-20260923-030619\frontend-typecheck.log`, `frontend-lint.log` |
| Frontend Vitest | Exit 0; 43 files/183 tests passed | `%TEMP%\edmg-full-diagnostics-20260923-030619\frontend-tests.log` |
| Release-toolchain Node tests | Exit 0; 108 passed/1 platform skip | `%TEMP%\edmg-full-diagnostics-20260923-030619\release-toolchain-tests.log` |
| Live backend/readiness | `/health` ok; system readiness ready; CUDA active on RTX A6000; TensorRT diagnostic ready; validated VAE and UNet engines present | Live API observation at 2026-09-23T03:05Z |
| WSL runtime preflight | Ubuntu WSL2 running; three RTX A6000 GPUs visible; llama.cpp 0.4.1-dev present | Direct `wsl.exe` observation at 2026-09-23T03:18Z |

**Acceptance limits:** the currently running Debug UI predates the final Reactive/Timeline/WSL-retry build, though it is responsive and the supplied Settings screenshot plus absence of a later unhandled entry show the two saved Settings fixes loaded. Native-app UI automation was unavailable, so page-by-page interactive traversal, real render inference, audible device playback, third-party VST3 compatibility, signed installer lifecycle, Store qualification, and live TensorRT acceleration on a new render remain unclaimed. Historical failed/quarantined TensorRT records remain diagnostics, not current engine failures; current API state reports `accelerating: false` until an actual render receipt proves use.

<!-- REVIEWER-UPDATE-END -->
