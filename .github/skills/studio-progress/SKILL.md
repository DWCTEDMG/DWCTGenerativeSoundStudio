---
name: studio-progress
description: studio-progress
disable-model-invocation: true
---
# Report Studio progress

Read repository-root `AGENTS.md`, `.github/copilot-instructions.md`, and `STUDIO_PROGRESS.md`.
Continue the current authorized WinUI task as implementer. At a natural checkpoint, update only the Implementer update section of `STUDIO_PROGRESS.md` with:

- acknowledgement and UTC timestamp;
- current task/blueprint gate, branch/base commit, dirty state, and owned paths;
- completed, in-progress, and remaining work;
- actual test/build commands, working directories, exit codes, results, candidate identity, and saved evidence paths;
- blockers, next step, and Reviewer update findings assessed or addressed.

Preserve the Reviewer update and all other concurrent work. Do not start builds, tests, installs, model downloads, or publishing solely to fill this status record. Say which evidence is missing. Update this handoff again after meaningful milestones or validation results.
