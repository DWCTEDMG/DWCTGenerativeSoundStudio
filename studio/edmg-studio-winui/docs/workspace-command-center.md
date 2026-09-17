# Workspace command center

The native Workspace keeps its specialist rooms and adds one continuous command
path: choose audio, enter the creative brief and style, select the planning model
and video renderer, generate the shared draft, edit it, then apply and open Render.
No render starts implicitly. Existing Director, Storyboard, Planner, Reactive Lab,
Timeline, and Render entry points remain available independently.

Provider and model overrides are request-scoped; they do not rewrite global AI
settings. OpenAI-compatible audio models can receive the full source track as a
mono 16 kHz WAV. Other planners receive analyzed audio context. Selecting native
audio requires an endpoint/model that actually implements input_audio; Qwen VL
models should not be treated as Qwen Omni models. Endpoints and credentials remain
configured through the existing provider settings.

Strict AI requests fail instead of silently accepting the provider's deterministic
fallback. Completed stages remain saved on cancellation or failure. Generated
plans publish through the existing shared planner draft, retaining its history,
locked content, reactive overrides, and revision checks. The selected renderer is
passed to the existing Render room, where all render controls remain accessible.

## Verification (2026-09-17)

- Release x64 WinUI solution build: passed, zero errors and warnings in final build.
- Core suite: 512 tests passed, including request serialization coverage.
- Focused backend provider/workflow/review suite: 32 passed with real audio enabled;
  two subsequent endpoint regression tests also passed.
- Supplied LANDR track: 329.995 seconds; real lightweight analysis, local planning,
  editable shared draft, camera/motion scheduling, timeline apply and persisted
  reopen passed in an isolated temporary project. This was not an AI video render.
- Native process/window responded; UI Automation confirmed Workspace command
  controls and retained room navigation. Full interactive production rendering
  and exhaustive visual/responsive qualification were not performed.
- Compatible audio transport, per-request model selection and fallback rejection
  are covered with mocked providers. Live NVIDIA inference could not be qualified:
  no NVIDIA API key was available in the verification environment. Live Qwen Omni
  and OpenAI inference remain environment-dependent and unverified.

Run the real-audio regression by setting STUDIO_TEST_AUDIO to a WAV path and running
edmg_studio_backend/tests/test_workspace_planning.py in the existing backend
environment. Do not synchronize dependencies or replace CUDA packages for this test.
