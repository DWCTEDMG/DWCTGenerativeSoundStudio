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

**Acknowledgement:** Pending the first update from Visual Studio Copilot. The reviewer has not sent a message to the running Copilot chat.

- Updated UTC: Not yet reported.
- Task / blueprint gate: Not yet reported.
- Branch / base commit / dirty state: Not yet reported by implementer.
- Owned files or work areas: Not yet reported.
- Completed since last update: Not yet reported.
- In progress: Not yet reported.
- Remaining / blockers: Not yet reported.
- Validation: No implementer result has been posted to this handoff yet.
- Next step: Report current work and validation at the next checkpoint.
- Reviewer findings addressed: None reported yet.

Use this table for the latest meaningful validation results; replace the pending row when actual evidence exists.

| UTC | Candidate and dirty state | Command and working directory | Exit / result | Saved evidence path |
| --- | --- | --- | --- | --- |
| Pending | Pending | Not reported | Not run/reported in this handoff | Not supplied |

<!-- IMPLEMENTER-UPDATE-END -->

## Reviewer update

<!-- REVIEWER-UPDATE-START: Codex owns this section. -->

**Observed UTC:** 2026-09-15T19:48:26Z. This is a snapshot of a changing worktree.

**Baseline:** Local HEAD and the remote default branch both resolve to `ba5c7763c6d19ef6724aaad4709be31a897c5889` on `codex/Unified`. Its subject is `docs: record aggregate backend qualification` and its commit metadata includes a Copilot co-author. Individual uncommitted files cannot be attributed to a particular agent from Git status alone.

**Work in progress:** 51 tracked modified files and 15 untracked files at the snapshot, before this handoff setup. File writes continued during inspection. Visual Studio, dotnet, and MSBuild processes were present; process presence does not prove a build is currently running or that it passed.

### What the saved changes show

| Blueprint area | Observed current work | Acceptance boundary |
| --- | --- | --- |
| B: native reliability | Shared `StudioJobsActivityService` and shell/Queue/Review/Dashboard/Outputs/Forge integration; dispatcher/lifetime changes | Needs navigation, cancellation, error-state, and backend-recovery evidence for the current changes. |
| C: audio | New `LiveMixerCallbackAdapter` and tests; Windows audio diagnostics/qualification changes | Core callback code exists, but the AudioGraph file-node playback path still does not execute live bus/send/PDC/automation processing. |
| D: post | Native WAVE extraction/alignment, Timeline Post controls, compatibility/history and channel-layout checks | Current edits need validation; device capture, supported formats/layouts, and user acceptance boundaries remain explicit. |
| E: models/rendering | Typed render preflight, Qwen/Whisper Models controls, stricter runtime readiness, and temporal-proof sidecars | Installed models and source tests do not prove real model inference or motion. Require current hardware/runtime receipts. |
| F: Store/release | Candidate manifest and hash binding, signing/lifecycle validation, Store metadata schemas, and related README updates | Code-signing availability is user-reported. Current signatures, clean-machine install/upgrade/rollback, and Store certification are not established by these edits. |

### Evidence available now

- Commit `ba5c776` records **164 passed / 4 skipped** for repository Python scope and **987 passed / 4 skipped** for backend-package scope in the consolidated blueprint. These are recorded baseline results, not reruns by this reviewer and not qualification of the newer dirty worktree.
- This review has not run builds, tests, model jobs, installers, or dependency synchronization. No passing current-candidate result is inferred from a changed test file.
- Copilot's current task description, progress percentage, remaining estimate, and live chat state are unknown until it writes its own handoff.

### Next handoff requested

Copilot should identify the active gate(s), post exact current test/build evidence, and distinguish code that exists from native or packaged behavior that has been exercised. Keep the large in-flight implementation batch out of any reviewer commit.

### Follow-up monitoring

Scheduled review setup is pending. Until confirmed, this file is updated when the reviewer is asked to inspect progress.

<!-- REVIEWER-UPDATE-END -->
