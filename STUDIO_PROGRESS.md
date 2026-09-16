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

**Acknowledgement:** Repository instructions and the latest Reviewer update are loaded. Completed the user-authorized Qwen GGUF-directed abstract music-reactive preview without replacing the active CUDA environment.

- Updated UTC: 2026-09-16T21:57:00Z.
- Task / blueprint gate: User-authorized commit and push of the complete worktree to the repository default branch; this does not alter Store or release gate status.
- Branch / base commit / dirty state: Default branch `codex/Unified`; substantive batch `5a18eeda63a08bf61560ea1dfa4879287ba25856` is confirmed at `origin/codex/Unified`. This handoff finalization is the only post-push change pending its own commit.
- Owned files or work areas: All worktree changes covered by the explicit publication request: this handoff, Store submission blueprint, three Studio render tools, and vendored LTX 2 v1.3.0 source.
- Completed since last update: Published 421 changed paths to the default branch. Qwen3-VL 8B GGUF generated the scene on CUDA 1 and saved one exact 0-384000-sample Director scene at project revision 8. LTX 2.5 rendered on CUDA 2; the WAV excerpt was muxed into the final preview. The vendored LTX checkout records clean upstream tag `v1.3.0` at `598ab41247a77dbfe29b5186e915bcf4f9040ec7`, with license files included and no credential values found.
- In progress: Committing and pushing this final publication record.
- Remaining / blockers: No publication blocker. Full-song rendering was not requested or run. External regression records `C:\Users\user\Downloads\ChatLog5.md` and `C:\Scripts\EDMG_Studio_Master_Blueprint_AI_DAW_Timeline.md` are absent on this workstation. GitHub reported pre-existing Dependabot alerts after the push; remediation was not part of this task.
- Validation: Real-model output is an 8.000-second 512x320 H.264 video at 24 fps with 192 frames and stereo 48 kHz AAC. Native motion check passed with 65/65 perceptually unique frames, 64/64 meaningful transitions, and no frozen pairs. The three new Python tools pass `py_compile`; `git diff --check` passes. SHA-256: `18C3297C410F776AE7E7750A776B4D7D91E7CF4ADDC797A2D5F0382830934BE9`.
- Next step: None after the final handoff commit reaches `origin/codex/Unified`.
- Reviewer findings addressed: Preserved GPU-first behavior, used real model inference, made no dependency synchronization or CPU fallback changes, and retained third-party license/provenance files.

| UTC | Candidate and dirty state | Command and working directory | Exit / result | Saved evidence path |
| --- | --- | --- | --- | --- |
| 2026-09-16T20:56:51Z | `29407dd`; dirty | `.\\python_backend\\.venv\\Scripts\\python.exe -u .\\tools\\prepare_the_end_preview.py`; `studio\\edmg-studio` | Exit 0; Qwen GGUF CUDA 1 scene generated and persisted | `data\\projects\\8e6d6cc1148045949fff6405b07099e2\\outputs\\qwen-abstract-preview\\director-run.log` |
| 2026-09-16T21:06:13Z | `29407dd`; dirty | `.\\python_backend\\.venv\\Scripts\\python.exe -u .\\tools\\render_the_end_preview.py`; `studio\\edmg-studio` | Exit 0; real LTX CUDA 2 render and final mux completed | `data\\projects\\8e6d6cc1148045949fff6405b07099e2\\outputs\\qwen-abstract-preview\\preview-run.log` |
| 2026-09-16T21:06:28Z | `29407dd`; dirty | `ffprobe` plus contact-sheet extraction; repository root | Exit 0; exact 8 s audio/video streams, 192 frames, visual contact sheet created | `studio\\edmg-studio\\data\\projects\\8e6d6cc1148045949fff6405b07099e2\\outputs\\qwen-abstract-preview\\ffprobe.json` |
| 2026-09-16T21:56:00Z | `5a18eeda`; clean after push | `git push origin HEAD:codex/Unified`; repository root | Exit 0; remote ref confirmed at `5a18eeda63a08bf61560ea1dfa4879287ba25856` | GitHub `origin/codex/Unified` |

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
