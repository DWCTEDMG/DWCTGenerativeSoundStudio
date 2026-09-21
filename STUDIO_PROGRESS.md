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

**Acknowledgement:** Repository instructions and the latest Reviewer update are loaded. This checkpoint assesses the remaining WinUI-first delivery work while preserving the current Hunyuan, WinUI debugger/taskbar, llama.cpp, and multi-GPU planning changes.

- Updated UTC: 2026-09-21T03:43:26Z.
- Task / blueprint gate: completed the user-authorized reconciliation, validation, commit, and push of the complete shared worktree, including Codex-authored changes.
- Branch / base commit / dirty state: `codex/Unified`; combined candidate commit `b0204a4442bf4294d086d95ecf58e0695fbc723a` was pushed to `origin/codex/Unified`; the worktree was clean immediately after publication and now contains only this handoff update.
- Owned files or work areas: the authorized combined candidate and this Implementer-only handoff update; the Reviewer section remains preserved.
- Completed: reconciled, committed, and pushed the combined candidate; preserved the unpackaged WinUI safeguards, taskbar COM hardening, Hunyuan and llama.cpp runtime corrections, runtime validation tooling, and Codex-authored multi-GPU plan; corrected the new manual-dispatch test to authenticate when the configured backend requires bearer auth.
- Validation/evidence: from repository root, `dotnet build studio\edmg-studio-winui\EdmgStudio.WinUI.slnx --no-restore --configuration Release -p:PlatformTarget=x64 --nologo` exited 0 with 0 warnings and 0 errors (`%TEMP%\combined-candidate-winui-build.log`); `dotnet test studio\edmg-studio-winui\tests\EdmgStudio.Core.Tests\EdmgStudio.Core.Tests.csproj --no-build --no-restore --configuration Release -p:PlatformTarget=x64 --nologo` exited 0 with 523 passed (`%TEMP%\combined-candidate-core-tests.log`); the three changed backend test modules exited 0 with 44 passed and one dependency deprecation warning (`%TEMP%\combined-candidate-python.log`); changed Python modules compiled successfully (`%TEMP%\combined-candidate-pycompile.log`); `git diff --check` exited 0. No dependency synchronization, model launch, or new device qualification was performed.
- Real-device evidence: retry 9 parent log is `studio\edmg-studio\data\projects\8e6d6cc1148045949fff6405b07099e2\outputs\videos\the-end-comparison\hunyuan_video15-preview-retry9.log`; diagnostics are under `...\hunyuan_video15\.hunyuan-runs\3e2bc3d139e54e77902a3408ced22384`. It failed at the first sequence-parallel NCCL broadcast with CUDA 999, produced no validated output, and does not qualify Hunyuan readiness.
- Remaining: diagnose and correct the retry-9 NCCL failure and obtain a validated audio-attached Hunyuan artifact. Subsequent work is Gates B-F: native reliability, real-device audio/editing, running-app post workflow, model/runtime qualification, and signed clean-machine release qualification. Multi-GPU orchestration Phases 0-6 remain a separate proposed roadmap unless explicitly authorized.
- Blockers: Hunyuan Level-5 proof is blocked by the repeat NCCL CUDA 999 failure. Device audio, interactive UI, real-model, signing/Store, and clean-machine gates require their respective environments and evidence.
- Next step: inspect retry-9 worker diagnostics and distributed-group lifecycle, implement the narrow correction, rerun the bounded preview, and validate output/provenance.
- Reviewer findings addressed: kept GPU-first/no-sync policy, distinguished accepted code from runtime qualification, included the Codex-authored plan as requested, and left the Reviewer section unchanged.

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
