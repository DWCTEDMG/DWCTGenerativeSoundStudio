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
**Acknowledgement:** Repository instructions and the latest Reviewer update were loaded. Implementer checkpoint: deterministic LTX authored-scene multi-GPU repair is complete; the user-authorized partial `Cosmic` artifact has been assembled with resume state preserved.

- Updated UTC: 2026-09-25T08:08:03Z. Task / gate: cancel the pre-scheduler LTX render safely and assemble its contiguous accepted frames into an explicitly partial MP4.
- Branch / base / state: `codex/Unified` at `cdfa5eac6149166bbaefafb4055bd1970e6b920b`; dirty authorized backend, WinUI, Director, test, handoff, and gitignored project-output files. Unrelated `agents\` and hybrid-plan files remain untouched.
- Owned paths: LTX/backend request and runtime services, Render-page LTX controls, native request builder, focused tests, this Implementer section, and the partial artifact receipt. No staging, commit, backend restart, dependency synchronization, or accelerator-profile change was performed.
- Completed: canceled job `a9019204cc044590a8b2aa48f8a9ba50` through `POST /v1/projects/8be2f05f91aa472fb1c72e70ea1f133c/jobs/a9019204cc044590a8b2aa48f8a9ba50/cancel` at 2026-09-25 07:50:48; confirmed zero matching LTX Python children while backend PID 77304 remained alive. Preserved 562 contiguous native frames (`0..561`) and the resumable checkpoint, assembled at 2 fps, motion-interpolated to 24 fps, and muxed the supplied audio to the 281-second partial duration.
- Artifact: `studio\edmg-studio\data\projects\8be2f05f91aa472fb1c72e70ea1f133c\outputs\videos\internal_v00_512x512_2rf_24of_32bc74e8f9_partial_canceled_562f.mp4`; SHA-256 `86B5BAAA12C1EACD42B81DA252DB82C079BD90086C3531B293E858612D8C2EAC`; receipt is the adjacent `.receipt.json`. This is explicitly partial/canceled and is not a completed full-song LTX qualification.
- Validation: `ffprobe -v error -show_entries stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,duration,nb_frames -show_entries format=duration,size -of json <artifact>` exited 0: H.264 video, 512x512, 24/1 fps, 6,744 frames, AAC audio, both streams and container exactly 281.000000 seconds, 28,999,908 bytes. First, middle, and last native PNGs decoded as 512x512 RGB. Assembly used the frozen project environment with `--no-sync` and the existing `assemble_image_sequence`, `interpolate_video_fps`, and `mux_audio` helpers; exit 0.
- Prior validation remains: focused backend suite 74 passed; native request-builder suite 23 passed; Visual Studio WinUI project build succeeded. Reviewer findings for honest model-parallel blocking, selected-GPU handling, automatic device discovery, cache fallback, metadata scope, and sibling cancellation remain addressed.
- Scheduler load / launch: stopped only the old WinUI PID 52088 and backend launcher/worker PIDs 12836/77304 after the canceled render was durable. From repository root, `dotnet clean studio\edmg-studio-winui\EdmgStudio.WinUI.csproj -c Debug -p:Platform=x64 --nologo` and `dotnet build studio\edmg-studio-winui\EdmgStudio.WinUI.csproj -c Debug -p:Platform=x64 --no-restore --nologo` exited 0. Started the backend with `uv run --project studio\edmg-studio\python_backend --frozen --no-sync python -m edmg_studio_backend serve --host 127.0.0.1 --port 7863`; launcher/worker PIDs 16188/61892 report `/health` OK, version 1.2.0. Launched rebuilt Debug WinUI PID 84964; it remained running and responsive at 2026-09-25T08:29:19Z. The updated scheduler is now loaded.
- Remaining / blockers: real bounded three-GPU native LTX qualification has not run and must not be inferred from deterministic tests or this legacy partial artifact; work-tag discrepancy, TensorRT artifact-level proof, completed full-song LTX qualification, and Hunyuan-last qualification remain open.<!-- IMPLEMENTER-UPDATE-END -->

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
