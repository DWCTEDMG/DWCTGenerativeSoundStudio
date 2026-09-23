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

**Acknowledgement:** Repository instructions and the latest Reviewer update were loaded. Existing dirty Settings/runtime work is preserved and excluded; CUDA and dependency profiles were not synchronized.

- Updated UTC: 2026-09-23T04:38:18Z. Task / gate: remove the mandatory-save blocker from native Workspace execution while preserving distinct Save and Apply behavior.
- Branch / base / state: `codex/Unified` at `f433749bc8d0e2741daf3fb8d17a96d29a3d5317`; dirty with this Workspace change and pre-existing Settings/runtime changes listed by `git status --short`.
- Owned paths: `studio/edmg-studio-winui/Pages/WorkspacePage.Command.cs`, `studio/edmg-studio-winui/Pages/WorkspacePage.xaml`, `studio/edmg-studio-winui/Pages/WorkspacePage.xaml.cs`, and this implementer section only. `WorkspacePage.Flow.cs` was inspected but has no final diff.
- Completed: **Make this** no longer checks inline draft save state. **Save draft** remains save-only. **Apply** sends the current document to the apply endpoint, persisting and committing it. Render handoff no longer requires Save and does not replace unsaved inline edits with a reviewed proposal. Explicit draft-replacement actions retain overwrite protection.
- Validation: from repository root, `dotnet build studio\edmg-studio-winui\EdmgStudio.WinUI.csproj --no-restore --configuration Release -p:PlatformTarget=x64` exited 0 with 0 warnings/0 errors; `%TEMP%\edmg-workspace-save-semantics-release-build.log`. `git diff --check` exited 0; `%TEMP%\edmg-workspace-save-semantics-diff-check.log`. An earlier Visual Studio Debug workspace build was blocked by active XAML compiler PID 40340 locking the Debug intermediate DLL; no process was terminated.
- Remaining / blockers / next step: no code blocker. Native interactive clicking was not run, so runtime UI behavior is not claimed; code presence and XAML compilation are verified.
- Reviewer findings addressed: latest diagnostics were read; this change does not alter the package-storage or WSL retry repairs.

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
