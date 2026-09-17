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

**Acknowledgement:** Repository instructions, the active Workspace task, consolidated blueprint, phase history, regression references, and latest Reviewer update are loaded. The user directly assigned completion of the native unified Workspace implementation; Visual Studio Copilot owns this implementation scope.

- Updated UTC: 2026-09-17T11:06:05Z.
- Task / blueprint gate: `WORKSPACE_UNIFIED_BLUEPRINT_TASK.md` Phases 1-4 complete. Unified Workspace orchestration and honest readiness UX preserve specialist surfaces, revision-safe Director/Reactive data, render handoff, and GPU-first behavior.
- Branch / base commit / dirty state: `codex/Unified` at `361ff134625387245691febcc59a15e7215ab966`, matching `origin/codex/Unified`. Phase 4 changes only this Implementer update; the user's untracked `WORKSPACE_UNIFIED_BLUEPRINT_TASK.md` remains outside commits.
- Owned files or work areas: native Workspace XAML/code-behind, focused Core readiness/orchestration contracts and tests, directly related backend regression scopes, and this Implementer section.
- Completed since last update: Completed the final native and backend regression gate. The unified control room, explicit draft review/application, preserved specialist editors, readiness evidence boundaries, and revision-safe workflow/render handoffs are implemented and persisted in Phase 1-3 commits. No Phase 4 code regression required a fix.
- Remaining / blockers: No implementation blocker. Interactive Storyboard editing, shared workflow save/apply, Director review/apply, Reactive keyframe editing, and render handoff were not manually smoke-tested in the GUI and remain explicitly unverified.
- Validation: Release x64 WinUI solution build passed with 0 errors and 20 existing test-analyzer warnings. Full native Core suite passed 520/520. Focused backend schema/Workspace/Director/render tests passed 87 with 1 real-audio test skipped because `STUDIO_TEST_AUDIO` was not set. No dependency restore/synchronization, real model inference, device audio, long render, or interactive UI qualification was performed.
- Next step: Commit and push this Phase 4 evidence handoff; no further implementation remains in the authorized Workspace task.
- Reviewer findings addressed: The latest Reviewer update contains no Workspace-specific finding. Its evidence boundaries remain enforced: deterministic tests and compilation do not qualify real Qwen/Whisper inference, device audio, renderer output, or interactive native UX.

| UTC | Candidate and dirty state | Command and working directory | Exit / result | Saved evidence path |
| --- | --- | --- | --- | --- |
| 2026-09-17T11:04:16Z | Phase 3 candidate based on `de6bdae046`; Phase 3 files dirty plus user task file | `dotnet test studio\edmg-studio-winui\tests\EdmgStudio.Core.Tests\EdmgStudio.Core.Tests.csproj --no-restore --configuration Release --filter FullyQualifiedName~WorkspaceReadinessSummaryTests\|FullyQualifiedName~WorkspaceDirectorRunnerTests\|FullyQualifiedName~StudioPageHelpersTests\|FullyQualifiedName~StudioApiClientTests --nologo`; repository root | Exit 0; 63 passed, 0 failed, 0 skipped | `C:\Users\user\AppData\Local\Temp\workspace-phase3-final-tests.log` |
| 2026-09-17T11:04:16Z | Same Phase 3 candidate | `dotnet build studio\edmg-studio-winui\EdmgStudio.WinUI.slnx --no-restore --configuration Release -p:PlatformTarget=x64 --nologo`; repository root | Exit 0; 0 warnings, 0 errors | `C:\Users\user\AppData\Local\Temp\workspace-phase3-final-build.log` |
| 2026-09-17T11:06:05Z | `361ff13462`; clean tracked tree plus user task file | `dotnet build studio\edmg-studio-winui\EdmgStudio.WinUI.slnx --no-restore --configuration Release -p:PlatformTarget=x64 --nologo`; repository root | Exit 0; 0 errors, 20 existing test-analyzer warnings | `C:\Users\user\AppData\Local\Temp\workspace-phase4-build.log` |
| 2026-09-17T11:06:05Z | Same Phase 4 candidate | `dotnet test studio\edmg-studio-winui\tests\EdmgStudio.Core.Tests\EdmgStudio.Core.Tests.csproj --no-build --no-restore --configuration Release -p:PlatformTarget=x64 --nologo`; repository root | Exit 0; 520 passed, 0 failed, 0 skipped | `C:\Users\user\AppData\Local\Temp\workspace-phase4-core.log` |
| 2026-09-17T11:06:05Z | Same Phase 4 candidate | Existing `.venv` Python `-m pytest -q` over contracts v1, Workspace planning/Reactive, Director review/workflow/readiness, conductor, and render-plan routes; repository root | Exit 0; 87 passed, 1 skipped (`STUDIO_TEST_AUDIO` absent), 1 dependency deprecation warning | `C:\Users\user\AppData\Local\Temp\workspace-phase4-backend.log` |
| 2026-09-17T11:06:05Z | Same Phase 4 candidate | `git diff --check`; repository root | Exit 0 | Console record |

<!-- IMPLEMENTER-UPDATE-END -->

## Reviewer update

<!-- REVIEWER-UPDATE-START: Codex owns this section. -->

**Observed UTC:** 2026-09-16T09:09:15.155224+00:00. User explicitly assigned implementation of GPU-first defaults after the commit/audit request.

**Baseline:** `66dcbe9dffcff36e1a4d92f6eb17ee49f52dfaee` on `codex/Unified` contains the previously pending 71-file workflow/release batch. The following validation applies to that baseline plus the current GPU-policy changes, not a new hardware qualification.

**Current change:** Automatic GPU preference in source setup/test/launcher paths; CUDA environment preservation; no implicit CPU fallback in internal renderer selection; visible automatic Setup choices; source startup and tests avoid dependency synchronization. CPU-only CI opts in explicitly. See `docs/STUDIO_ACCELERATOR_POLICY.md` for support boundaries.

**Fresh evidence (all commands from repository root unless stated otherwise):**

| Command | Result | Local evidence |
| --- | --- | --- |
| `dotnet build studio/edmg-studio-winui/EdmgStudio.WinUI.slnx --no-restore --configuration Release -p:PlatformTarget=x64 --nologo` | Exit 0; complete XAML build; 0 errors, 17 analyzer warnings | `%TEMP%/gpu-default-build.log` |
| `dotnet test studio/edmg-studio-winui/tests/EdmgStudio.Core.Tests/EdmgStudio.Core.Tests.csproj --no-build --no-restore --configuration Release -p:PlatformTarget=x64 --nologo` | Exit 0; 511 passed | `%TEMP%/gpu-default-core.log` |
| `studio/edmg-studio/python_backend/.venv/Scripts/python.exe scripts/run_pytest_scopes.py` | Exit 0; selected CUDA, sync disabled; repository 172 passed/4 skipped; backend 1013 passed/4 skipped | `%TEMP%/gpu-default-all-python.log` |
| Focused profile/installer/launcher/setup tests after final helper changes | Exit 0; 66 passed | `%TEMP%/gpu-default-focused.log` |
| `node --test main-process/backend-runtime.node-test.mjs` from `studio/edmg-studio` | Exit 0; 18 passed | `%TEMP%/gpu-default-node.log` |

Targeted Ruff checks and whitespace checks pass. The aggregate run used the existing CUDA environment without synchronization; torch/torchaudio remain `2.11.0+cu130`, torchvision `0.26.0+cu130`. This does not claim full-repository lint cleanliness: the earlier audit found pre-existing backend lint issues and a missing `current_correlation` import in the generic exception handler.

**Acceptance limits:** Automatic approval review blocked the attempted unpackaged GUI launch with backend spawning disabled (reason: "blocked by policy"). The updated Setup surface compiled but was not exercised interactively. No real model inference, VST3 hosting, AudioGraph mixer integration, capture, signed installer lifecycle, or Store qualification was performed. Native bounded WAVE alignment is implemented; old statements that it is entirely unavailable have been corrected in the blueprints.

Copilot's Implementer section is preserved. Unrelated local changes are not part of this GPU-policy work.

<!-- REVIEWER-UPDATE-END -->
