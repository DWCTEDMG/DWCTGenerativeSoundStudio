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

**Acknowledgement:** Repository instructions and the latest Reviewer update were loaded. The user expanded the VST3 gate to require a separately named x64 `EdmgStudio.Vst3Scanner.exe`; existing staged TensorRT/VST3 work is preserved and CUDA was not synchronized or replaced.

- Updated UTC: 2026-09-23T01:27:30Z. Task / gate: commit and push the qualified TensorRT, WinUI, and split native VST3 implementation to the repository default branch.
- Branch / base / state: `codex/Unified` at `aff8b9dbc9d5ce6ba3b0d6cbfcd8d23fa5aadb39`; `origin/codex/Unified` has no divergence. The 89-file implementation batch is staged and passed `git diff --cached --check`; unrelated `.github/agents/` remains untracked and excluded.
- Completed: built distinct C++17 x64 `EdmgStudio.Vst3Scanner.exe` and `EdmgStudio.Vst3Host.exe` targets from Steinberg VST3 SDK 3.8.1 commit `3cdf9ca5d1f5b1b21e0a86832aa4abe55607bd96`. Compile-time operation gates restrict scanning to the scanner and qualification/workers to the host. Valid modules without audio-effect classes return explicit unsupported status, are cached, and are not quarantined. Settings resolves scanner and host independently and reports ready/unsupported/failed counts. Candidate and MSIX contracts bind both executable identities.
- Processing retained: paired-pipe float32 DSP, selected event-bus MIDI, rich parameter metadata/editing, component/controller state, latency, fatal crash/timeout isolation, worker compatibility checks, ordered inserts and delayed bypass, project persistence/lifecycle, Timeline controls, and negotiated-quantum AudioGraph-to-Core mixer bridging.
- Real plug-in evidence: clean and extracted scanners each found two AGain classes with status `success`; clean and extracted hosts each qualified AGain 2-in/2-out, one event-input bus, three parameters, 12 component-state bytes, 257 controller-state bytes, and finite checksum `0.375`, exit 0 (`%TEMP%\edmg-vst3-dedicated-scan.log`, `%TEMP%\edmg-vst3-dedicated-qualify.log`, `%TEMP%\edmg-vst3-split-packaged-scan.log`, `%TEMP%\edmg-vst3-split-packaged-qualify.log`). Scanner worker mode and host scan mode both failed closed with exit 2. Clean and extracted host lifecycle/MIDI/state/crash/timeout tests each passed 3/3 (`%TEMP%\edmg-vst3-native-managed-split.log`, `%TEMP%\edmg-vst3-split-packaged-managed.log`).
- Regression/package evidence from repository root unless noted: focused scanner/VST3/mixer/audio tests passed 27 with 3 native tests skipped when environment paths were absent (`%TEMP%\edmg-vst3-scanner-focused-final.log`); those three native tests passed separately with real paths. Complete Core Debug run passed 560 with the same 3 environment-dependent tests skipped (`%TEMP%\edmg-vst3-core-split-full.log`); WinUI Debug x64 built with 0 warnings/errors (`%TEMP%\edmg-vst3-scanner-winui.log`); release-candidate Node tests passed 9/9 (`%TEMP%\edmg-vst3-scanner-release-final.log`); packaging foundations passed (`%TEMP%\edmg-vst3-scanner-packaging-final.log`). All commands exited 0.
- Exact candidate: packaged Release x64 build passed with 0 warnings/errors (`%TEMP%\edmg-vst3-split-msix.log`). Candidate `edmg-rc1-a5356f78e1f4d8800404e5622c2668526720b6ee521ecd919453972b039c49e2`; MSIX `%TEMP%\edmg-vst3-split-msix\ED2F9BCD-A580-4603-8A17-A7AD5FF6D451_1.2.1.0_x64.msix`, SHA-256 `E181B96E226394CE10CCB0D2B4E4C14028ED06470B1C5F40A83805A0B9F5F6D9`. Packaged host SHA-256 `AAFB3AA5C40D7B9641EDB229C0D5159E9B59FAB4F7E65B3072250D963C04F80D` and scanner SHA-256 `E376DF9F394C8221EEC0AE9CBBFE6D23C362957EDAE2675475597C4EB1CF07AE` exactly match candidate provenance.
- Remaining limits: the MSIX is unsigned, backendless by explicit developer diagnostic allowance, and non-distributable. No installed third-party module was found beyond official AGain. Interactive Settings/Timeline controls, audible AudioGraph/WASAPI playback, sustained underrun/latency behavior, arbitrary plug-in compatibility, ASIO, editor embedding, and hard-realtime safety were not verified and are not claimed.
- Blockers / next step: implementation and deterministic/package qualification are complete for the available specification. Real-device interactive/audio and signed clean-machine/Store qualification require separate operator evidence. The user authorized committing and pushing the staged implementation to the default branch; commit and push are the remaining actions.
- Reviewer findings addressed: all five VST3/audio defects remain corrected and regression-covered; the reviewer’s device-audio and realtime caveats remain open and explicit.

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
