# Studio Modularity Roadmap

## Goal

Make EDMG Studio more personal and modular without changing the core application shape:

- keep top-level tabs stable
- let users customize the panels inside pages
- allow theme selection and future theme packs
- use Studio Forge as the readiness, guided-routing, builder, and preview surface for these capabilities
- keep Unreal Engine optional if it is added later

This plan is additive only. It does not replace:

- the Electron shell
- the React frontend
- the FastAPI backend
- the Setup Wizard
- the default internal renderer
- optional ComfyUI sidecars
- model management
- packaging or backend spawn flow

## Principles

1. Top-level navigation stays canonical.
2. Per-page internals can become modular.
3. Layout state is user-scoped UI state, not project content.
4. Themes are frontend-only token sets.
5. Runtime integrations remain optional providers or bridges.
6. Studio Forge reports and guides; canonical pages own execution and project mutation.

## Current Progress

The current frontend implementation already includes:

- a global Studio theme provider
- local per-page layout persistence
- shared layout customization controls
- local layout profile slots (`Personal`, `Focus`, `Technical`, `Presentation`)
- modular rollout on `Dashboard`, `Projects`, `Settings`, `Models`, `Studio Forge`, `Outputs`, `Render Queue`, `Cloud`, `AI Planner Lab`, `Reactive Lab`, and `EDMG Director`
- phase-2 progress already landed for named layout profiles and Studio Forge layout/preview surfaces
- Studio Forge is default-visible, with `VITE_EDMG_DISABLE_STUDIO_FORGE=1` available as an explicit packaging or support opt-out
- Studio Forge derives live system, model, storage, CUDA/provider/task, project, and variant readiness from existing APIs
- guided recipes show completed, current, and blocked stages and route to the canonical action owner

These changes are frontend-only. They do not alter backend contracts, Setup Wizard flow,
model installs, render defaults, desktop backend spawning, or packaging behavior.

## Page Modularity Model

Each customizable page should define a panel registry:

```ts
type StudioPanelDefinition = {
  id: string;
  page: string;
  label: string;
  description: string;
  defaultVisible: boolean;
  advancedOnly?: boolean;
};
```

Each user gets saved layout state per page:

```ts
type StudioPageLayoutState = {
  order: string[];
  hidden: string[];
};
```

Phase 1 uses local frontend persistence. A later phase can move this into desktop-managed user settings under Studio Home if cross-machine or multi-window sync becomes important.

## Theme Model

Themes should be token-driven and safe:

- colors
- borders
- panel backgrounds
- sidebar/main shell accents
- button tones

Do not theme by rewriting page markup. Theme by overriding CSS variables.

Future extensions:

- font packs
- density modes
- custom user theme JSON
- per-theme background treatments

## Studio Forge Role

Studio Forge is the Studio-side 1.0 readiness and guided-workflow shell for modular Studio behavior:

- truthful runtime, storage, accelerator, provider, model, and task inspection
- active-project and selected-variant readiness
- selectable recipes with completed, current, and blocked stages
- theme and page-layout preview
- workflow compatibility and bridge previews
- safe calls to action into `Setup`, `Models`, `Workspace`, `Render`, `Review`, and `Outputs`

Forge is deliberately non-authoritative. Setup owns runtime configuration, Models owns model installs and restores, Workspace owns project planning, Render owns render dispatch, Review owns OSC/MIDI/WebSocket live publishing, and Outputs owns Unreal export/import-plan/returned-media actions. Forge reports their state and routes users to them; it does not duplicate their mutations.

## Unreal Engine Direction

Unreal should only be added as an optional bridge, never as a required runtime.

Recommended shapes:

- export target for shot and scene metadata
- render handoff target
- control bridge over files and the Studio live-publisher handoffs
- optional provider surfaced by Studio Forge previews

Not recommended:

- embedding Unreal into Studio
- making Unreal the default render path
- changing Setup or packaging to require Unreal

Current status:

- the repo now has a non-destructive Unreal bridge MVP for preview, export bundles, import-plan generation, and return-import back into Studio outputs
- Forge links those handoffs through the canonical Workspace and Outputs pages
- Review owns the existing OSC, MIDI, and WebSocket publishers; those publishers are not direct Unreal Remote Control
- the Unreal importer remains a first-pass cameras/cuts/markers consumer and has no verified in-editor smoke test
- Unreal remains optional, preview-oriented, and non-authoritative
- there is still no required Unreal runtime dependency, packaged plugin, direct Unreal Remote Control integration, Movie Render Queue automation, or full editor automation

## Phase Plan

Some phase-2 UI pieces are already in the repo, and a limited Unreal bundle MVP
exists, but the roadmap below remains the intended direction.

### Phase 1

- frontend-only theme provider
- per-page layout state hook
- layout customizer UI
- apply layout customization to safe, non-critical pages first
- document the Unreal bridge strategy and keep any bridge work non-destructive

### Phase 2

- expand modular layouts to more operational pages
- add named layout profiles
- add density and font choices
- add Studio Forge layout/theme previews

### Phase 3

- desktop-managed persistence for appearance/layout state
- optional import/export of themes and layouts
- preview-only Unreal bridge validation in Studio Forge

## Current Implementation Boundary

The implementation boundary stays away from:

- backend contracts
- setup/install flows
- render defaults logic
- model install logic
- backend spawning
- packaging scripts

Forge may read existing backend contracts to present readiness and guidance, but
it does not move their mutation logic into the frontend. The Unreal bridge and
Outputs import/export surfaces remain additive rather than execution-authoritative.
There is no claim of a packaged Unreal plugin, direct Remote Control, MRQ, full
scene construction, or verified in-editor automation.
