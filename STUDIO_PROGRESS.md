$env:EDMG_BACKEND_ACCELERATOR_PROFILE = "cuda"

uv run --project studio\edmg-studio\python_backend `
  --frozen --no-sync `
  python -m edmg_studio_backend serve `
  --host 127.0.0.1 `
  --port 7863# Studio implementation and review handoff

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

**Acknowledgement:** Repository instructions and the latest Reviewer update are loaded. The authorized WinUI local AI runtime orchestration implementation is complete without changing backend TensorRT/render dispatch contracts.

- Updated UTC: 2026-09-22T05:16:48Z.
- Task / blueprint gate: implemented `studio\edmg-studio-winui\IMPLEMENTATION_PLAN.md`; supports consolidated blueprint Gates B and E.
- Branch / base commit / dirty state: `codex/Unified` at `e8e10cd19b97e64fca27d0d5b1a2b32d74f3f119`, aligned 0 ahead/0 behind `origin/codex/Unified` before publication. The user authorized committing and pushing the entire current worktree, including the pre-existing backend contract-test and plan-file changes.
- Owned paths: `src\EdmgStudio.Core\Runtime\`, local-runtime Core tests, `Services\AppServices.cs`, `App.xaml.cs`, `Pages\SettingsPage.xaml*`, and this Implementer section; publication scope is the complete user-authorized worktree.
- Completed: persisted runtime settings; WSL/CUDA discovery and safe command execution; llama.cpp and TensorRT-LLM providers; ownership-safe startup, readiness, cancellation cleanup, restart, and bounded shutdown; async app lifecycle integration; native Settings status/actions/diagnostics/log access; malformed-health handling; deterministic coverage.
- Validation/evidence from repository root against the current dirty candidate: `dotnet test studio\edmg-studio-winui\tests\EdmgStudio.Core.Tests\EdmgStudio.Core.Tests.csproj --configuration Release -p:PlatformTarget=x64 --nologo` exited 0 with 548/548 passed (`files\local-runtime-core-release.log`); focused `FullyQualifiedName~LocalRuntime` exited 0 with 21/21 passed (`files\local-runtime-focused-release.log`); `dotnet build studio\edmg-studio-winui\EdmgStudio.WinUI.slnx --no-restore --configuration Release -p:PlatformTarget=x64 --nologo` exited 0 with 0 warnings/errors and complete XAML compilation (`files\local-runtime-winui-release.log`); frozen/no-sync focused backend contracts exited 0 with 50/50 passed (`files\local-runtime-backend-focused.log`). Logs are under session `155679d1-6423-4733-beb0-e40ece40f2f0`.
- Baseline regressions observed, not caused by owned paths: aggregate frozen/no-sync run exited 1 with 172 passed/4 skipped/2 static-scan failures from untracked `tools\LTX-2-v1.3.0` and `tools\ltx-2.5-env` contents (`files\local-runtime-python-regressions.log`); backend-only suite exited 1 with 1037 passed/2 skipped/4 existing engine-package expectation failures (`files\local-runtime-backend-release.log`).
- Remaining / acceptance limits: no live WSL runtime/model was installed or launched, so actual CUDA inference, GPU-memory behavior, endpoint routing, multi-GPU splitting, and interactive Settings operation remain unqualified hardware/device evidence rather than deterministic completion claims.
- Blockers: none for implementation or deterministic acceptance; live qualification requires installed WSL llama.cpp/TensorRT-LLM binaries and compatible models.
- Next step: reviewer inspection or separate live-hardware qualification; no additional implementation is pending in this task.
- Reviewer findings addressed: GPU-first/no-sync policy is preserved; external endpoints are never killed; Studio only stops recorded owned PIDs; render TensorRT remains separate; code presence, deterministic tests, native compilation, and live evidence are reported distinctly.

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
