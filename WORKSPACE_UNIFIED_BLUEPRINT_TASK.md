# Workspace Unified Control Blueprint Task

**Status:** Implemented and regression-verified in the native WinUI 3 client. Phase commits are
`aaca973`, `5d8d7de`, `de6bdae`, `361ff13`, and `92c3ee5`. This document is the accepted task and
preservation checklist, not proof of real-model, device-audio, interactive GUI, render, signing, or
Store qualification.

## Goal

Create a streamlined Workspace experience that combines the current Director, AI Planner, Reactive Lab, Storyboard, audio analysis, project readiness, and render handoff functions into one cohesive workspace flow without removing or weakening any existing specialist capability.

The specialist pages remain available from the sidebar for users who want to work with each tool individually. The Workspace becomes the main guided control surface: project input, Whisper/audio analysis, Qwen direction, plan generation, storyboard review, reactive motion/camera refinement, and render handoff should feel like one session instead of separate labs.

## Product Intent

The default Workspace path should be:

1. Choose or load the active project.
2. Collect source media and audio.
3. Run or reuse Whisper/audio analysis.
4. Generate or refine creative direction with the configured planner.
5. Let the internal Qwen Director model review and strengthen the plan.
6. Review storyboard scenes and shared workflow direction.
7. Refine motion, camera, reactive cues, and timeline handoffs.
8. Apply the reviewed workflow and open render with the correct context.

Qwen and Whisper should drive the guided default flow when available and ready. Bring-your-own-model support must remain available through the existing provider/model controls and must not be removed or hidden from advanced users.

## Non-Negotiable Preservation Rules

- Do not remove the existing AI Planner Lab, EDMG Director, Reactive Lab, Storyboard, Timeline, Render, Models, or Settings surfaces.
- Do not remove any existing Workspace fields, selectors, draft recovery behavior, project readiness checks, media pool controls, JSON import/export tools, or render handoff actions.
- Preserve Director-to-Reactive Lab draft recovery.
- Preserve reviewed camera and motion keyframe persistence.
- Preserve render-profile compatibility and render context handoff behavior.
- Preserve backend schema importability and WinUI XAML page compilation.
- Preserve CUDA/GPU-first behavior. Do not silently synchronize or replace GPU environments with CPU packages.
- Do not claim model readiness from installation alone. Distinguish installed, validated, runtime-ready, smoke-tested, and production-qualified states.
- Do not claim full render, UI, or release readiness without direct evidence.

## Workspace UX Shape

The Workspace should expose an "All tools" or equivalent combined view as the default mode. This view should bring the major functions together in the same scrollable work surface:

- Project session and project readiness.
- Creative brief, visual style, provider, model, native audio toggle, renderer choice, and "Make this" command.
- Audio upload, Whisper/transcription status, BPM, sections, tags, transcript, and analysis metadata.
- Shared workflow direction editor with scene intent, actions, camera, effects, notes, and revision-safe save/apply behavior.
- Qwen Director controls for managed direction generation, review, draft JSON, apply, and status.
- Storyboard scene review and editable storyboard-to-timeline controls.
- Embedded or expandable AI Planner specialist controls.
- Embedded or expandable Reactive Lab controls for motion, camera, cues, and keyframes.
- Project readiness, music/live readiness, creative DNA, specialist handoffs, and debug tools.

Focused tabs or selector modes may remain for Storyboard, AI Planner, and Reactive Lab, but the combined Workspace view is the primary guided path.

## Qwen and Whisper Default Flow

The Make workflow should evolve from "planning only" into an orchestrated Studio session:

1. Ensure project and media state are current.
2. Upload pending source audio if needed.
3. Run Whisper/audio analysis when no current analysis exists or when the selected source changes.
4. Generate a baseline plan using the selected provider/model.
5. If a managed internal Qwen Director model is ready, submit a Director generation job against the shared workflow document and current analysis context.
6. Poll or surface job progress without blocking the UI indefinitely.
7. Review the generated Director draft when available.
8. Show the reviewed Qwen proposal in the existing Director/shared workflow surfaces.
9. Let the user apply the reviewed workflow into the project and open Render.

If Qwen is unavailable, not validated, or fails, Workspace should keep the baseline plan and provide a clear status. It must not erase user edits or silently downgrade the result without explanation.

Whisper should remain the default audio understanding layer for transcript/tags/sections when available. Existing analysis reuse should be respected so users are not forced to re-run transcription on every action.

## BYOM Requirements

Bring-your-own-model must remain available and functional:

- Preserve provider selection, configured provider, OpenAI-compatible endpoints, Ollama/NIM/local options, model override fields, and native-audio-capable routing.
- Keep per-request provider/model overrides scoped to the request unless the user explicitly saves settings elsewhere.
- Do not require managed Qwen for basic plan generation.
- Do not require Whisper for users who already have valid imported or cached analysis.
- Clearly indicate which model drove each generated artifact when possible.

## Required Skill Usage

Use the local Codex skills as part of the implementation workflow. The current task explicitly calls for:

- `$studio-engineer` at `C:\Users\user\.codex\skills\studio-engineer\SKILL.md` for Studio-specific audio, visual, render-pipeline, Qwen/Whisper, workflow, and validation judgment.
- `$creative-engineering` at `C:\Users\user\.codex\skills\creative-engineering\SKILL.md` for the combined Workspace UX, architecture tradeoffs, orchestration shape, and practical creative problem solving.

Also use any other relevant installed skills when their scope directly matches a phase of the work. Examples include:

- `$winui-app` for WinUI 3 layout, XAML, native navigation, adaptive UI, and build/launch verification.
- `$frontend-design` only if the Workspace experience needs additional visual or interaction design guidance beyond existing WinUI conventions.
- `$playwright` or other UI automation skills only when they are applicable to the surface being tested.
- Security skills only for an explicit security review or security-sensitive change.

Do not mechanically load unrelated skills just to satisfy the phrase "all skills." Skill usage should be deliberate: select every skill that materially improves this implementation, read its instructions before acting, and record the important skill-driven constraints in the phase notes or commit summary.

## Implementation Phases

### Phase 1: Unified Workspace Surface

Create the combined Workspace view that keeps the existing controls and embeds or expands the specialist experiences in one place.

Acceptance gates:

- Workspace opens to the combined view by default.
- Storyboard, AI Planner, and Reactive Lab remain reachable as individual sidebar or selector destinations.
- Existing unsaved-edit protections still trigger.
- XAML compiles.
- No current fields or actions disappear from Workspace.

Suggested commit scope:

- XAML layout changes.
- Workspace selector behavior.
- Specialist frame embedding/lazy-loading behavior.
- Any focused UI tests or compile fixes required by the layout change.

### Phase 2: Orchestrated Make Flow

Extend the Workspace Make action into a guided multi-step flow that can run audio analysis, plan generation, managed Qwen Director generation/review, and render handoff preparation while preserving BYOM and baseline fallback behavior.

Acceptance gates:

- Existing provider/model plan generation still works.
- Pending audio upload and analysis reuse still work.
- Managed Qwen Director generation uses existing backend Director APIs rather than bypassing them.
- Director job status is visible and recoverable.
- Reviewed Director drafts can be applied into the shared workflow document.
- User edits and revision conflicts are protected.
- Qwen absence/failure leaves the baseline plan usable.

Suggested commit scope:

- Workspace command orchestration.
- Director job submission/status/review/apply integration.
- Status messaging and cancellation behavior.
- Focused Core/API contract tests.

### Phase 3: Whisper and Model Readiness UX

Tighten Workspace status around Whisper, Qwen, and BYOM readiness so users understand what is driving the session.

Acceptance gates:

- Workspace distinguishes no analysis, cached analysis, active Whisper analysis, and failed analysis.
- Workspace distinguishes configured, installed, runtime-ready, validation-ready, smoke-tested, and unavailable internal Director models.
- BYOM state is still explicit.
- User-facing status does not overclaim model qualification.

Suggested commit scope:

- Readiness summaries.
- Model/provider labels.
- Status and error copy.
- Focused tests for readiness contract serialization if needed.

### Phase 4: Regression Verification and Polish

Run focused verification across the affected UI, Core contracts, and backend schema/API paths.

Acceptance gates:

- WinUI XAML build succeeds.
- Focused Core tests covering Workspace/Director contracts pass.
- Backend schema imports and relevant focused tests pass without dependency synchronization unless explicitly required.
- Storyboard editing, shared workflow save/apply, Director review/apply, Reactive Lab keyframes, and render handoff are manually smoke-checked or explicitly marked unverified.
- Evidence clearly states what was run, what passed, what was not run, and what remains unqualified.

Suggested commit scope:

- Polish and regression fixes only.
- Documentation update if behavior or acceptance evidence changes.

## Commit and Push Discipline

For the active implementation thread, each completed phase should be committed and pushed to the default branch before starting the next phase, as requested by the user.

Default branch from the current handoff context is `codex/Unified`, but this must be freshly verified in the implementation thread before committing or pushing.

Each phase commit should be focused and should include:

- The exact phase scope.
- Build/test evidence or a clear statement of what was not run.
- No unrelated reverts.
- No dependency synchronization unless explicitly needed and approved by the Studio GPU policy.

## Verification Checklist

- `git status --short --branch`
- Default branch verification before push.
- WinUI solution build for XAML compilation.
- Focused Core tests for Workspace, Director, and API contracts.
- Focused backend import/schema/API tests for Director and Workspace planning.
- Manual Workspace UI smoke test when feasible:
  - combined view loads
  - project selection works
  - analysis panel shows current state
  - Make flow starts and reports status
  - Qwen job readiness/status is visible
  - storyboard remains editable
  - Reactive Lab controls remain reachable
  - render handoff opens with context
- Explicit evidence labels:
  - implemented
  - compiled
  - tested
  - smoke-tested
  - runtime-qualified
  - not verified

## Known Risk Areas

- Lazy-loading embedded specialist pages may trigger duplicate refreshes or project-session conflicts.
- Reactive Lab has its own unsaved keyframe state and must not be refreshed in a way that drops edits.
- Director review and apply are revision-sensitive; stale drafts must be blocked cleanly.
- Applying a Director draft may need a Workspace workflow reload so the user sees the latest shared document immediately.
- Long-running Qwen jobs need cancellation/status behavior that does not freeze the UI.
- BYOM/native-audio paths should not be broken by making managed Qwen the preferred default.

## Completion Record

The native Workspace now defaults to the combined **All tools** workbench and preserves the
specialist destinations. The Make flow uploads pending audio, runs or reuses analysis, generates a
baseline provider/BYOM plan, optionally invokes a runtime-ready managed Qwen Director, exposes draft
review/application, preserves the baseline on Qwen failure, and prepares the Render handoff.

Workspace readiness distinguishes absent/cached/active/failed analysis and configured, installed,
adapter-reachable, validation-ready, smoke-tested, and Level-5 runtime-ready model evidence. BYOM
selection remains explicit and is not represented as endpoint qualification.

Recorded verification at completion: Release x64 WinUI compilation passed; the full Core suite
passed 520 tests; focused backend schema/Workspace/Director/render coverage passed 87 tests with one
real-audio case skipped because `STUDIO_TEST_AUDIO` was unset. Interactive GUI editing/handoffs, real
Qwen or Whisper inference, device audio, long rendering, signing, Store submission, and clean-machine
release qualification were not performed and remain separate gates.

## Definition of Done

The task is done when Workspace feels like one guided native workbench for source media, analysis, planning, Qwen direction, storyboard, reactive refinement, and render handoff, while every existing specialist function remains available either inside the combined Workspace or from its original dedicated page.

Completion requires implementation, focused automated verification, and honest evidence of any remaining unverified runtime or UI gates.
