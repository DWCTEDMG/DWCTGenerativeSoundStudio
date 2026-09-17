# Studio implementation handoff

Follow the repository's `AGENTS.md` and the user's current instructions. The active product focus is native WinUI 3 in `studio/edmg-studio-winui/`, with the shared Python backend supporting it. The unified Workspace is the primary guided flow across source media, Whisper/audio analysis, provider planning/BYOM, managed Qwen Director review, storyboard, Reactive Lab, and render handoff; preserve the dedicated specialist pages. Read `blueprint/WINUI3_CONSOLIDATED_BLUEPRINT.md` for forward gates and `blueprint/planning.md` for accepted phase history. Preserve the regression references listed in `AGENTS.md`.

For the user's agreed coordination workflow, Visual Studio Copilot is the implementer and Codex is the reviewer. Use repository-root `STUDIO_PROGRESS.md` as the shared handoff:

- Read the latest Reviewer update at natural checkpoints and assess its findings within the existing authorized task.
- Update only the section between `IMPLEMENTER-UPDATE-START` and `IMPLEMENTER-UPDATE-END` at task start, meaningful milestones, validation results, blockers, and handoff. Include acknowledgement, UTC time, task/gate, branch/base commit and dirty state, owned paths, completed and remaining work, blockers, next step, and findings addressed.
- Record actual commands, working directories, exit codes, counts, and saved log paths. Distinguish tests not run from passing tests, deterministic simulation from real-device evidence, and code presence from working native integration.
- Re-read before editing and preserve the reviewer's section. Keep secrets, signing keys, tokens, and private service credentials out of progress records.
- Continue the current authorized task; this coordination file is not a request to rebuild the product or execute every blueprint item. Coordinate ownership before changing another agent's files or staging/publishing shared work.
- Preserve the selected accelerator profile and running environment. Do not run a CPU synchronization that replaces CUDA packages in an active environment as part of status reporting.
- Keep working WinUI paths and project data intact. Actual Store/signing, real-model rendering, device audio, and clean-machine qualification require their own evidence.

The shared file is not a live chat connection. A first implementer update acknowledges that these instructions were loaded.
