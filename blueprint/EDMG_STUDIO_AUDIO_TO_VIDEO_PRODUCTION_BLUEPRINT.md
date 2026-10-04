# EDMG Studio Audio-to-Video Production Blueprint

**Status:** Forward project plan, production guide, and acceptance contract  
**Primary product:** Native WinUI 3 EDMG Studio  
**Supporting product:** Shared Python backend  
**Compatibility surface:** React/Electron client; it may consume shared contracts but is not the primary product UI  
**Document role:** Merge the complete audio-to-video vision with the Studio capabilities already implemented, while separating source integration, automated tests, live model qualification, and end-to-end production proof  
**Last updated:** 2026-10-03

---

## 1. Executive vision

EDMG Studio will turn a complete song into a deliberate, editable, full-motion audiovisual production. It will not behave like a prompt box that happens to accept an audio file. It will behave like an AI-assisted director, editor, cinematographer, motion designer, render supervisor, and finishing system whose decisions remain traceable to the music and under the creator's control.

The target workflow is:

```text
Complete source audio
    -> authoritative technical analysis
    -> evidence-grounded musical interpretation
    -> creative treatment and persistent Story Bible
    -> editable scene-by-scene storyboard
    -> camera, motion, effects, and reactive keyframes
    -> deterministic production compilation
    -> hardware/model/render preflight
    -> preview, selected-scene, or full-production rendering
    -> interpolation, assembly, audio mux, and finishing
    -> universal media and plan-conformance validation
    -> final video, production receipt, and recoverable project state
```

The system must work when lyrics are absent. Lyrics, transcription, stems, and vocal separation are optional evidence sources, not prerequisites for authorship. Instrumental music must remain a first-class directing input.

The system must also remain honest. A catalog entry, endpoint setting, successful import, passing unit test, or compiled UI is not equivalent to a model completing real inference. A renderer is not production-ready until it has generated valid media on the intended execution plane and produced a matching receipt. A complete production is not successful merely because an MP4 exists.

---

## 2. Product principles

### 2.1 Analyze once, reuse everywhere

The source track is analyzed into one revisioned, authoritative evidence package. Director, Storyboard, Reactive Lab, Timeline, Render, Review, and Outputs consume that shared package. Reanalysis is exceptional and must be caused by a source change, an analyzer upgrade, or an explicit user request.

Reanalysis must never silently erase an approved plan, an applied Timeline, reviewed camera/motion keys, locked scenes, or manual edits. It may create a new pending draft and mark dependent artifacts stale. The user decides whether to migrate, compare, or replace them.

### 2.2 Separate fact, inference, and artistic choice

Every important decision must be identifiable as one of:

- **Measured fact:** directly computed from the media, such as an onset, energy rise, duration, spectral change, or detected section boundary.
- **Model-supported inference:** a conclusion supported by evidence but not objectively measurable, such as escalating tension or a feeling of arrival.
- **Creative interpretation:** an authored visual decision, such as moving from a submerged chamber into a glowing city.
- **User instruction:** a brief, reference, locked choice, manual edit, or approved exception.
- **Fallback/default:** a deterministic choice used because evidence, a model, or a renderer was unavailable.

The UI must not present interpretations as measured truth. Confidence, provenance, and fallback disclosures remain visible in expert views and production receipts.

### 2.3 Human authority, bounded automation

Generated direction remains a draft. Models may propose; they may not bypass review and mutate authoritative project state. Studio supports three autonomy levels:

1. **Guided:** pause after analysis, treatment, storyboard, Timeline application, and preflight.
2. **Review before render:** automatically build the complete production draft, then pause for approval before GPU-intensive rendering. This is the recommended default.
3. **Full automatic:** permitted only when the user has explicitly enabled it, preflight passes, the project has no unresolved blockers, and the chosen fallback policy is recorded.

Locked scenes, approved appearances, manual Timeline content, reviewed keyframes, and user-authored constraints may not be changed without an explicit replacement operation.

### 2.4 WinUI-first, expert-capable

Workspace is the default guided control room. AI Planner, Director, Storyboard, Reactive Lab, Timeline, Render, Models, Settings, Review, Queue, and Outputs remain available as specialist surfaces. The guided experience orchestrates existing capabilities; it does not replace them with a second pipeline.

Every backend capability that is part of the supported product must have a corresponding WinUI control, state display, or actionable diagnostic. API-only functionality is incomplete.

### 2.5 Local-first, provider-neutral execution

Studio owns stable contracts rather than coupling project data to one inference server. Nemotron and Cosmos may run through isolated local workers or an OpenAI-compatible serving boundary such as NVIDIA NIM, vLLM, or another qualified NVIDIA runtime. The same versioned Director and Specialist contracts must work across those execution modes.

Qwen remains an optional fallback or user-selected Director. It is not the default. NVIDIA Nemotron is the default managed Director, and Cosmos Reason2 is an optional visual-reasoning specialist. Cosmos Reason2 must remain distinct from any Cosmos video-generation service.

### 2.6 Deterministic production around probabilistic models

Models generate proposals. Deterministic code owns timing, identities, revisions, locked data, duration normalization, keyframe bounds, manifest compilation, resource checks, job idempotency, artifact publication, validation, and receipts.

### 2.7 Fail visibly and preserve recoverability

No failure may collapse into an unexplained generic result when an actionable cause is available. Jobs expose stage, progress, logs, retryability, cancellation state, selected execution route, and output ownership. Partial artifacts remain quarantined until publication succeeds. The last approved project state remains reopenable after interruption or crash.

---

## 3. Current implementation baseline

Studio already contains much of the required architecture. This blueprint preserves and consolidates it rather than starting over.

### 3.1 Foundations to preserve

- Complete-audio import, validation, probing, storage, hashing, and project association.
- FFmpeg/NumPy-based signal analysis with revisioned snapshots and authoritative timing.
- Optional vocal separation and transcription.
- Instrumental/lyricless planning from rhythm, energy, spectral movement, structure, motifs, and creative brief.
- Direction generation, multiple plan variants, scene normalization, Story Bible/continuity data, and editable scene plans.
- Shared Workspace draft consumed by Director, Storyboard, Reactive Lab, and Timeline.
- Review-before-apply semantics, optimistic revision checks, and explicit destructive replacement controls.
- Prompt tracks, motion tracks, camera keys, zoom/pan/rotation/translation schedules, beat markers, cue events, and reactive values.
- Preservation of prior camera state across scene boundaries and protection of manual or locked Timeline content.
- Internal render planning, hardware inspection, render tier selection, model readiness checks, temporal strategy, frame limits, interpolation, assembly, NVENC, and original-audio inclusion.
- Render strategies involving still/keyframe generation, TensorRT-qualified components where supported, HunyuanVideo, LTX, Stable Video Diffusion, AnimateDiff, RIFE, NVIDIA FRUC, FFmpeg, and other explicitly qualified routes.
- Durable jobs, review, outputs, model management, settings, diagnostics, and native WinUI specialist surfaces.
- Provider-neutral Director and Specialist contracts, Nemotron/Cosmos adapters, schema repair, provenance, and graceful specialist failure.

### 3.2 Maturity vocabulary

Every feature and model route must use these states consistently:

| State | Meaning |
| --- | --- |
| Designed | The contract and acceptance criteria are documented. |
| Implemented | Source code and a user-reachable WinUI path exist. |
| Contract-tested | Automated tests validate schemas, state transitions, and failure behavior. |
| Integration-tested | Real components communicate using the intended boundary. |
| Runtime-qualified | The real model/runtime executes on target hardware and produces a valid receipt. |
| End-to-end qualified | A representative project completes the entire production chain and passes universal validation. |
| Release-qualified | The exact packaged candidate passes clean-machine, security, signing, accessibility, recovery, and customer-flow gates. |

No lower state implies a higher one.

### 3.3 Current honest assessment

The overall conceptual workflow and most production stages are implemented. Nemotron and Cosmos Reason2 are integrated at the contract, configuration, routing, and native-UI layers. Their large production weights and the complete NVIDIA-driven flow have not yet been proven together on a real project. A single arbitrary song has not yet been shown to move through the entire new intelligence layer, full-motion generation, final assembly, universal validation, and receipt publication without manual repair.

This is an integration and qualification gap, not a reason to discard the current architecture.

---

## 4. Canonical system architecture

```text
Native WinUI 3
  Workspace / Director / Storyboard / Reactive Lab / Timeline / Render
        |
        v
Shared Python control plane
  projects, revisions, media, analysis, drafts, plans, jobs, receipts
        |
        +--> deterministic audio-analysis pipeline
        |
        +--> Director provider interface
        |      +--> managed Nemotron worker (default)
        |      +--> OpenAI-compatible NIM/vLLM deployment
        |      +--> optional Qwen fallback
        |
        +--> Specialist provider interface
        |      +--> Cosmos Reason2 visual specialist
        |      +--> deterministic/no-specialist continuation
        |
        +--> production compiler
        |      storyboard + timeline + camera + motion + render manifests
        |
        +--> execution scheduler
        |      Windows / isolated worker / WSL2 / external Linux / hosted
        |
        +--> image and video renderers
        |      internal diffusion / TensorRT / Hunyuan / LTX / SVD /
        |      AnimateDiff / qualified Cosmos generator / external adapters
        |
        +--> interpolation and finishing
        |      RIFE / NVIDIA FRUC / FFmpeg / NVENC / audio mux
        |
        +--> validation and publication
               media checks + plan conformance + receipts + Outputs
```

### 4.1 Runtime deployment strategy

Use a hybrid provider model:

- **Local managed mode:** Studio launches and supervises an isolated worker that loads model weights directly. Best for single-workstation installation, privacy, and offline operation.
- **Local service mode:** Studio calls an OpenAI-compatible service on the workstation or local network. NIM or vLLM can own batching, health, metrics, and model serving while Studio owns projects and creative orchestration.
- **Remote service mode:** the same contracts target a secured GPU service. This is optional and must disclose locality, cost, privacy, latency, and retention.
- **Optimized render workers:** TensorRT/TensorRT-LLM or model-specific workers are used only where the exact model and workload have been qualified. The UI reports the actual admitted route rather than the requested one.

NIM, vLLM, and TensorRT-LLM are infrastructure choices, not project schema choices. The Studio contract remains stable while execution profiles evolve.

### 4.2 GPU and execution-plane policy

- The Windows control plane owns projects, revisions, jobs, staging, approval, publication, and receipts.
- WSL2 or external Linux workers receive immutable execution manifests and publish only through fenced staging paths.
- GPU identity is reconciled by UUID or PCI identity, never by assuming Windows and WSL ordinal numbers match.
- Multi-GPU behavior is declared explicitly as data parallel, model parallel, pipeline parallel, scene parallel, or single-device. Three detected GPUs do not prove that one model uses all three.
- CPU execution is an explicit user-selected fallback, not the default for a GPU product.
- Every runtime receipt records model ID/revision, runtime/version, device identities, precision, quantization, route, seed, and relevant compiler/cache identities.

---

## 5. Canonical project data model

Every derived artifact carries at least:

- `project_id`
- `project_revision`
- `source_audio_asset_id`
- `source_audio_sha256`
- `analysis_revision`
- `schema_version`
- `created_at_utc`
- `created_by` and origin type
- parent artifact IDs/revisions
- user approval state
- stale/superseded state
- extension bag for forward compatibility

### 5.1 AudioEvidencePackage

The authoritative analysis contains:

- exact duration, sample rate, channel layout, bit depth, and source hash;
- sample/time/frame conversion metadata;
- tempo curve, confidence, tempo changes, beat grid, downbeats, bars, and time-signature regions where detectable;
- structural sections, transitions, drops, silence, breaks, crescendos, climaxes, and endings;
- onset/transient events and density;
- RMS, peak, LUFS-like loudness, dynamic range, and normalized energy curves;
- low/mid/high and configurable band energies;
- spectral centroid, bandwidth, rolloff, flux, brightness, and texture descriptors;
- harmonic/percussive balance;
- pitch-class profile, tonal-center/key candidates, mode candidates, and harmonic confidence;
- tension, dissonance, stability, novelty, repetition, and motif-recurrence descriptors;
- stereo width, correlation, spatial changes, and channel anomalies;
- optional stems and stem-activity envelopes;
- optional transcript, lyric timing, vocal-presence regions, and transcription confidence;
- analyzer/version provenance and confidence per feature family;
- feature quality warnings and known limitations.

Not all analyzers will supply every field initially. Unsupported or low-confidence fields are explicit; they are never synthesized and labeled as measurements.

### 5.2 InterpretationRecord

The Director produces structured interpretations linked to evidence IDs:

- observation/evidence references;
- inferred musical function;
- emotional and narrative reading;
- alternative readings;
- confidence and uncertainty;
- lyric-dependent versus lyric-independent rationale;
- user-brief influence;
- selected creative consequence.

### 5.3 StoryBible

The persistent Story Bible defines:

- title, logline, thesis, and visual promise;
- world, era, locations, environmental rules, and scale;
- characters/subjects, identity locks, wardrobe/appearance locks, and prohibited mutations;
- visual grammar, composition rules, palette, lighting, texture, and material language;
- camera grammar and motion grammar;
- recurring motifs, symbols, transformations, and their musical triggers;
- narrative/emotional arc aligned to song sections;
- continuity rules, reference assets, negative constraints, and safety constraints;
- renderer strategy and known route limitations;
- approved facts versus editable creative choices.

### 5.4 ScenePlan

Every scene or shot contains:

- stable scene/shot ID and revision;
- exact start/end samples, seconds, frames, and musical positions;
- evidence IDs and creative purpose;
- subject, environment, action, composition, shot size, and screen-space constraints;
- camera start/end state, movement, lens/FOV, focus, aperture/DOF intent, look-at target, roll, and stabilization style where supported;
- visual motion, subject motion, environment motion, effect motion, and expected motion score;
- palette, lighting, atmosphere, texture, and continuity constraints;
- transition-in/out, overlap handles, and authored versus technical transition intent;
- renderer capability requirements and selected/fallback routes;
- generation prompt, negative constraints, references, seeds, and identity controls;
- reactive mappings and keyframe references;
- confidence, warnings, review state, lock state, and manual overrides.

### 5.5 Timeline and keyframe contracts

Canonical tracks include source audio, prompts, scenes, camera, subject motion, environment motion, effects, lighting/color, compositing, transitions, markers, and automation.

Camera keys support a staged capability model:

- Stage 1: zoom, pan, rotation, translation, and renderer-native schedules.
- Stage 2: position XYZ, yaw/pitch/roll, target, focal length/FOV, focus distance, aperture/DOF, near/far limits, stabilization, and constraints.
- Stage 3: editable interpolation, easing, handles, velocity/acceleration limits, collision/safe-volume constraints, and viewport preview.

Reactive mappings always use a control stack:

```text
raw feature
  -> normalization
  -> attack/release smoothing
  -> threshold/hysteresis for events
  -> artistic remap curve
  -> parameter-specific clamp
  -> keyframe/schedule generation
```

Studio must avoid mapping every feature directly to every parameter. Bass may influence large-scale weight or camera push; midrange may drive topology/density; high-frequency energy may drive micro-detail or emission; onsets may drive cuts or accents; sections may drive scene and palette changes. The Director chooses mappings that serve the treatment rather than producing a generic audio visualizer.

### 5.6 ProductionManifest

The deterministic compiler emits an immutable manifest containing:

- exact project, analysis, Director, Story Bible, storyboard, Timeline, and settings revisions;
- resolved scene/shot windows and frame ranges;
- resolved prompts, references, seeds, and identity constraints;
- admitted renderer per shot and explicit fallback policy;
- model IDs/revisions and required runtime profiles;
- GPU/resource request, parallelism mode, VRAM/disk estimates, cache keys, and staging paths;
- camera/reactive schedules and transition handles;
- resolution, aspect, frame rate, color pipeline, codec, bitrate/quality, audio policy, and output naming;
- validation policy and acceptance thresholds;
- approval record and manifest hash.

---

## 6. End-to-end production workflow

### Stage 0 — Create or open project

Studio establishes project identity, storage health, media permissions, autosave/recovery state, execution profile, and output policy. Opening an existing project never triggers regeneration.

**Gate:** project loads with migrations and unknown fields preserved; recovery choices are explicit.

### Stage 1 — Import and validate source audio

Studio copies or securely references the source, calculates its hash, probes media properties, and creates a durable media asset. It reports unsupported codecs, truncated media, channel-layout concerns, or authorization failures.

**Gate:** complete decodable source with stable identity and exact duration.

### Stage 2 — Analyze audio

Studio runs deterministic signal analysis across the complete track. Optional separation and transcription may run in parallel or as later enrichment. Analysis is cached by source hash, analyzer version, and options.

The WinUI analysis view shows progress by feature family, confidence/warnings, and whether existing downstream artifacts will become stale. Users may reuse a compatible analysis rather than repeat it.

**Gate:** authoritative timing, valid analysis schema, source-hash match, and usable structural/energy evidence. Lyrics are not required.

### Stage 3 — Interpret the music

Nemotron receives the creative brief plus bounded audio-derived evidence. If the runtime supports native audio, Studio may also provide the audio through the qualified multimodal route; measured evidence remains the deterministic backbone.

Nemotron returns evidence-linked interpretations, competing readings where ambiguity matters, and a recommended dramatic arc. Deterministic interpretation remains available if Nemotron is unavailable. Qwen is a selectable fallback, not an invisible substitution.

**Gate:** schema-valid interpretation; fact/inference/creative layers distinguishable; fallbacks disclosed.

### Stage 4 — Build creative treatment and Story Bible

Studio creates the full-song treatment: world, subjects, symbolic system, visual grammar, camera language, motion language, continuity rules, arc, render intent, and prohibited changes. The user can lock individual elements.

**Gate:** treatment covers the complete song, respects the brief, contains no unresolved identity contradiction, and has an explicit renderer feasibility assessment.

### Stage 5 — Generate storyboard variants

Studio creates one or more complete, duration-bounded scene plans. Variants reuse the same evidence and Story Bible but may differ in narrative abstraction, visual density, edit cadence, renderer cost, or risk. The user may compare and merge variants.

**Gate:** scenes cover the intended duration without gaps or accidental overlaps; every scene has purpose, timing, continuity, and a feasible visual strategy.

### Stage 6 — Optional Cosmos specialist review

Cosmos Reason2 is invoked only where visual reasoning adds value: reference consistency, shot critique, image/video evidence review, spatial continuity, ambiguous visual choices, or render-result diagnosis. It returns bounded findings and suggestions; Nemotron or deterministic orchestration remains responsible for the authoritative Director draft.

Cosmos failure never destroys a valid baseline plan. Its provenance and impact are recorded. A Cosmos video generator, if later supported, is a separate renderer with separate readiness.

**Gate:** specialist output is schema-valid, advisory, and traceable; no unreviewed mutation occurs.

### Stage 7 — Generate camera, motion, and reactive draft

The production compiler converts scenes into editable tracks and keyframes. Macro structure follows sections and phrases; micro motion follows smoothed signals and events. Deterministic seeds preserve continuity. Randomness is reserved for local variation rather than scene identity or macro timing.

The draft includes camera, subject, environment, particles/effects, lighting/color, compositing, transitions, prompt schedules, and renderer hints.

**Gate:** all schedules are bounded, finite, correctly timed, and attached to the current analysis/storyboard revision.

### Stage 8 — Review and edit

Workspace presents a production summary and blockers. Specialist pages provide deep editing. Review includes:

- evidence and interpretation;
- Story Bible locks;
- storyboard completeness;
- camera/motion preview;
- continuity and identity checks;
- renderer feasibility and estimated cost/time;
- warnings, assumptions, and fallbacks.

Users may edit or regenerate a scene without invalidating unaffected approved scenes. Dependency-aware invalidation identifies exactly what must be recompiled or rerendered.

**Gate:** explicit approval with current revisions and no unresolved blocking issue.

### Stage 9 — Apply to canonical Timeline

Application uses optimistic revision control. Planner-owned content may be replaced after confirmation; manual and locked content is preserved. Director-to-Reactive Lab draft recovery and reviewed camera/motion persistence are mandatory regression contracts.

**Gate:** Timeline duration matches the source; tracks are internally consistent; undo/recovery data is written; reopen produces the same state.

### Stage 10 — Compile production manifest

The compiler resolves every choice into bounded production data and rejects:

- timing gaps/overlaps not explicitly authored;
- invalid sample/frame conversions;
- missing assets, models, references, or permissions;
- unsupported dimensions, frame rates, color/codec combinations, or renderer capabilities;
- impossible or unbounded camera values;
- excessive velocity, acceleration, rotation, or deformation;
- inadequate subject/face coverage where required;
- identity/continuity conflicts;
- changes to locked content;
- stale analysis, storyboard, Timeline, or settings revisions;
- jobs that exceed configured VRAM, disk, time, or cost limits without acknowledgement.

**Gate:** immutable manifest and hash.

### Stage 11 — Preflight

Preflight reports **Ready**, **Warnings**, and **Blocked**, with actions rather than raw JSON. It checks:

- exact model files and pinned revisions;
- runtime health and compatibility;
- GPU identity, driver/runtime, VRAM, precision, and multi-GPU strategy;
- expected scene/frame workload and disk space;
- renderer capability against each shot;
- keyframe, temporal model, interpolation, assembly, encoder, and audio routes;
- cache compatibility and resumability;
- network, credentials, privacy, and cost for hosted services;
- fallback policy and quality consequences.

The before-render summary states exactly what will run, where, and what will happen if it fails.

**Gate:** no blockers; warnings explicitly accepted; selected route admitted by evidence.

### Stage 12 — Render

Studio supports:

- **Draft preview:** low-cost representative output for direction, timing, and motion review.
- **Selected scenes/shots:** render only chosen or invalidated work.
- **Full production:** render the complete approved manifest.
- **Automatic after approval:** proceed from successful preflight only when enabled.

Each shot is idempotent and content-addressed. Approved cached outputs are reused only when all relevant inputs match. Workers publish through fenced staging; canceled or stale jobs cannot overwrite newer output. Progress reports meaningful stages, not only a percentage.

### Stage 13 — Interpolate, assemble, and finish

Studio applies the admitted interpolation route, authored transitions, color/format normalization, encode, original-audio mux, and metadata. Technical overlap for continuity must not be confused with an authored dissolve.

Color assumptions, transfer characteristics, range, pixel format, alpha policy, and audio channel handling are explicit. Unsupported multichannel/object layouts are preserved or blocked; they are never silently flattened while reported as intact.

### Stage 14 — Universal validation

Every final candidate passes one common validator regardless of renderer. It checks:

- artifact exists, is nonempty, and decodes from beginning to end;
- container/codec/pixel format are allowed;
- width, height, frame rate, duration, and decoded frame count match policy;
- original or approved audio is present, decodable, aligned, and correctly bounded;
- no unexplained black, corrupt, duplicate, or frozen spans exceed thresholds;
- actual motion satisfies scenes that require motion;
- all approved scene windows are represented;
- shot ordering and transitions correspond to the manifest;
- output comes from the current project/manifest revision;
- fallbacks, retries, partial rerenders, and deviations are disclosed;
- hashes and provenance are complete.

Semantic and perceptual checks may flag results for human review, but deterministic media failures block publication.

### Stage 15 — Publish and review

Successful output moves atomically into project Outputs with thumbnail/proxy, manifest, receipts, validation report, model/runtime provenance, and reproducibility information. The Review surface supports A/B comparison, frame stepping, markers, scene-level rerender requests, and approval.

**Gate:** validated media plus complete production receipt. An MP4 without the receipt is an artifact, not a qualified production.

---

## 7. Native WinUI production experience

### 7.1 Workspace guided flow

The primary call to action is **Build Music Video**. It orchestrates existing APIs and state:

```text
Source -> Analyze -> Interpret -> Direct -> Storyboard -> Motion -> Review
       -> Apply -> Preflight -> Render -> Validate -> Output
```

The workflow resumes from the latest compatible durable stage. It must never ask the user to analyze the same unchanged audio twice merely because another page failed to load its shared draft.

Workspace displays:

- current project/source and analysis freshness;
- current Director and specialist routes;
- completed, active, blocked, stale, and approval-required stages;
- treatment/Story Bible summary;
- scene, camera-key, motion-key, and cue counts;
- model/runtime readiness;
- selected render route and estimated resource use;
- next recommended action;
- links into specialist surfaces without losing place.

### 7.2 Specialist surfaces

- **AI Planner:** briefs, deterministic baseline, variants, provider comparison.
- **Director:** evidence, interpretations, treatment, Story Bible, Nemotron/Qwen choice, locks, provenance.
- **Storyboard:** scene/shot grid, timing, references, prompts, continuity, renderer assignment, review state.
- **Reactive Lab:** feature visualization, smoothing/remap, cue events, camera/motion/effect mappings, safe apply/reload.
- **Timeline:** sample-accurate tracks, keyframes, automation, transport, manual editing, undo/redo, recovery.
- **Render:** Simple/Advanced modes, visual route summary, preflight, selected/full render, quality/cost/time controls.
- **Models:** install, verify, qualify, optimize, delete, diagnostics, licenses, revisions, capability badges.
- **Settings:** execution profiles, endpoints, secrets via environment/secure storage, fallback and autonomy policies.
- **Queue:** durable progress, pause/cancel where supported, retry/recovery, stage diagnostics.
- **Review/Outputs:** validation, receipts, A/B, rerender markers, reveal/export/publish.

### 7.3 Shared native components

Create reusable `StatusCard`, `ReadinessPanel`, `ModelPicker`, `EvidenceBadge`, `StageProgress`, `EmptyState`, `JobProgressCard`, `PropertySection`, `ValidationReport`, and `ProductionReceiptView` controls. Use teaching tips and actionable InfoBars for recoverable problems. Preserve keyboard navigation, high contrast, scaling, screen-reader names, focus order, and compact/comfortable density.

### 7.4 Render UX

Render defaults to outcome-oriented choices: goal, aspect, resolution, duration/scope, quality/time budget, frame rate, and autonomy. Advanced mode exposes models, engines, precision, schedules, chunking, overlap, interpolation, codecs, and fallbacks.

A sticky command surface keeps **Preflight**, **Render selected**, **Render full**, **Save preset**, and **Reset** available. A persistent readiness card displays route, model, GPU, frame estimate, disk estimate, warnings, and blockers. A global job strip keeps render state accessible throughout Studio.

---

## 8. Intelligence-layer plan

### 8.1 Nemotron Director

Nemotron is the default managed Director. Its responsibilities are:

- interpret musical structure and meaning from bounded evidence and, when qualified, native audio;
- produce evidence-linked readings and alternatives;
- author treatment and Story Bible proposals;
- create/revise complete storyboard proposals;
- reason across long-form arc and continuity;
- request specialist review through bounded orchestration, not direct uncontrolled tool use;
- return versioned structured output.

Nemotron does not own exact timing arithmetic, authoritative IDs, revision mutation, locked data, renderer admission, or final publication.

### 8.2 Cosmos Reason2 specialist

Cosmos Reason2 is invoked for visual evidence and critique:

- reference-image understanding;
- generated-frame/clip critique;
- identity, object, and spatial continuity;
- composition and cinematography analysis;
- diagnosing why a rendered shot fails the intended scene;
- recommending bounded storyboard or renderer adjustments.

Its results are advisory `SpecialistResult` records. A failing or missing specialist produces a disclosed warning and continues with the baseline where safe.

### 8.3 Qwen optional path

Qwen remains available for compatibility, lower-resource local inference, user preference, and disaster recovery. The UI must clearly show when Qwen is selected or used as fallback. It may not silently masquerade as Nemotron.

### 8.4 Prompt and context discipline

- Send compact projections rather than asking a model to echo the complete authoritative project.
- Keep source timing, renderer metadata, locked fields, and identity data server-owned.
- Budget context explicitly and measure serialized request size before dispatch.
- Chunk long evidence by section while preserving a global arc summary.
- Require strict schemas and at most a bounded repair attempt.
- Merge model proposals deterministically and validate before persistence.
- Record prompt/template version, model revision, token/context budget, and repair/fallback events without logging secrets.

---

## 9. Rendering strategy

### 9.1 Hierarchical route selection

1. Determine shot requirements: motion type, duration, identity, references, camera control, resolution, and continuity.
2. Filter to installed, licensed, compatible, and runtime-qualified routes.
3. Score quality, controllability, predicted motion, VRAM, latency, cost, and failure history.
4. Choose primary and permitted fallback per shot.
5. Compile immutable manifests.
6. Re-evaluate only if inputs or readiness change; never silently change route mid-production.

### 9.2 Rendering lanes

- **Keyframe/still lane:** image diffusion and TensorRT-qualified components for anchors, references, and low-motion material.
- **Image-to-video lane:** SVD, AnimateDiff, or another qualified route for bounded shots.
- **Text/reference-to-video lane:** Hunyuan, LTX, or other qualified full-motion models.
- **External/hosted lane:** optional provider routes with explicit privacy/cost disclosure.
- **Interpolation lane:** RIFE first when configured/qualified, NVIDIA FRUC where admitted, CPU filters only as explicit fallback.
- **Assembly lane:** FFmpeg/NVENC with exact timing, transitions, audio preservation, and validation.

### 9.3 Continuity strategy

Use Story Bible locks, references, deterministic seeds, previous approved frames/keyframes, overlap handles, scene-state carryover, and specialist critique. Cache keys include every continuity-sensitive input. A user can rerender a shot without invalidating unrelated approved work.

### 9.4 Resource strategy

- Preview and storyboard proxies remain cheap and fast.
- Full-resolution renders use scene-level checkpointing and resumable jobs.
- GPU concurrency is bounded by measured VRAM and model residency.
- Disk estimates include intermediates, caches, proxies, logs, and final output.
- Long productions support scene parallelism when continuity permits; adjacent dependent shots remain ordered.
- Thermal, OOM, worker-loss, timeout, and disk-pressure failures surface actionable recovery choices.

---

## 10. Production receipts and observability

Each stage emits a receipt or durable event. The final receipt includes:

- project/source/analysis/plan/Timeline/manifest revisions and hashes;
- user approvals and autonomy mode;
- Director/specialist providers, model IDs/revisions, prompt/schema versions, and fallbacks;
- renderer/model/runtime/device per shot;
- seeds, references, cache keys, retry counts, and deviations;
- interpolation, encoder, codec, color, audio, and assembly details;
- start/end time and stage durations;
- validation measurements and outcome;
- artifact hashes, sizes, paths, and lineage;
- environment fingerprint sufficient for diagnosis without secrets.

Metrics include analysis time, Director latency, schema-repair rate, specialist use, preflight failures, per-route success, OOM/retry rate, frames per second, cache hit rate, frozen/black-frame findings, render-time estimate accuracy, and user rerender frequency.

Logs use correlation IDs across WinUI, backend, provider, worker, and artifact. User-facing errors provide message, cause, hint, affected stage, whether state is safe, and a direct recovery action.

---

## 11. Security, privacy, and supply chain

- Secrets are never stored in project documents or returned by settings APIs.
- Local/remote execution is disclosed before media leaves the workstation.
- Provider requests are minimized to required evidence and references.
- Uploaded or generated media follows explicit retention and deletion policy.
- Model manifests pin repository, revision, files, hashes, license, source, and expected size.
- Workers run with least privilege and authorized staging paths.
- Media access uses canonical containment/authorization checks.
- Untrusted model output is treated as data, schema-validated, and never executed as instructions.
- Job IDs, manifests, publication, and retries are idempotent and fenced.
- Release artifacts include dependency locks, SBOM, checksums, signatures, and provenance.

---

## 12. Testing and qualification matrix

### 12.1 Contract tests

- schema versioning, unknown-field preservation, and migrations;
- exact samples/seconds/frames conversions;
- source-hash and revision invalidation;
- fact/inference/creative provenance;
- locked-scene and manual-Timeline preservation;
- Director/specialist schema validation and repair limits;
- prompt context-size enforcement;
- compiler rejection cases;
- manifest determinism and cache keys;
- idempotent jobs, cancellation fencing, and publication;
- validation thresholds and receipt completeness.

### 12.2 Integration tests

- import -> analyze -> reopen;
- lyricless analyze -> plan;
- transcription-present and transcription-failed paths;
- Director draft -> Reactive Lab -> Timeline apply;
- stale draft and conflict recovery;
- model discovery/readiness -> preflight;
- selected-shot render -> assembly;
- worker crash/timeout/OOM -> safe retry;
- interpolation and audio mux;
- final validator across every supported render lane.

### 12.3 Live qualification ladder

1. Load exact model files locally without network substitution.
2. Minimal deterministic inference on one target GPU.
3. Cache/reload inference with building disabled where applicable.
4. Representative project input.
5. Multi-GPU placement or scene parallelism proof if claimed.
6. Short shot producing decodable, non-frozen motion.
7. Multi-shot section with continuity and original audio.
8. Complete song.
9. Universal validation and production receipt.
10. Reopen, resume, selected-scene rerender, and recovery.
11. Packaged candidate and clean-machine customer flow.

### 12.4 Required test assets

Maintain a small licensed/internal qualification set:

- instrumental track with clear sections and drops;
- lyrical track with vocals;
- changing-tempo track;
- ambient/low-transient track;
- odd-meter or ambiguous-meter track;
- long track stressing context and scene count;
- stereo-width/spatial-change track;
- reference images with identity/continuity constraints.

Expected evidence is versioned, but creative output is judged by invariants and bounded metrics rather than brittle exact prose.

---

## 13. Delivery roadmap

### Phase 0 — Baseline and truth ledger

**Goal:** freeze the current candidate's real capability state.

**Work:** inventory code, WinUI surfaces, routes, tests, installed models, live runtimes, receipts, dirty work, and stale documentation; classify every claim with the maturity vocabulary.

**Exit:** approved matrix of present, partial, missing, and unqualified capabilities; no architectural rewrite authorized by ambiguous status.

### Phase 1 — Canonical contracts and evidence provenance

**Goal:** make analysis, interpretation, Story Bible, storyboard, keyframes, manifests, and receipts versioned and composable.

**Work:** expand missing fields; add provenance/confidence; formalize fact/inference/creative layers; preserve extension fields and migrations.

**Exit:** round-trip, migration, and stale-dependency tests pass; existing projects reopen unchanged.

### Phase 2 — Complete technical audio analysis

**Goal:** deliver the professional evidence package requested by the vision.

**Work:** audit current measurements; add tempo curves, bars/downbeats, dynamics, harmonic/percussive, tonal, motif, tension, stereo, and confidence features in prioritized increments; expose them in WinUI.

**Exit:** qualification set produces valid, bounded evidence; missing/low-confidence features are explicit; no lyrics required.

### Phase 3 — Evidence-grounded NVIDIA Director

**Goal:** qualify Nemotron as the real default Director.

**Work:** install/pin weights; validate worker/service profiles; enforce compact context; run text, evidence, and audio-native tests where supported; persist interpretation and provenance.

**Exit:** real project evidence -> valid Director plan on target A6000 hardware, with receipt and safe fallback.

### Phase 4 — Cosmos visual specialist

**Goal:** qualify optional visual critique without coupling it to production correctness.

**Work:** install/pin Reason2; qualify image and short-video evidence; implement bounded request selection; expose specialist findings in review UI.

**Exit:** valid specialist result improves or critiques a real scene; timeout/invalid result leaves baseline usable.

### Phase 5 — Story Bible and storyboard completeness

**Goal:** make every scene production-compilable and editable.

**Work:** fill scene schema/UI gaps; add variant comparison/merge, locks, confidence, references, renderer requirements, continuity graph, and dependency invalidation.

**Exit:** complete-song storyboard has no missing required fields, gaps, or unresolved continuity blockers.

### Phase 6 — Camera, motion, and reactive system

**Goal:** advance from schedules to a professional virtual-cinematography and audio-reactive control system.

**Work:** complete staged camera model; smoothing/remap UI; parameter clamps; curve editing; motion preview; deterministic phrase seeds; safe Timeline application.

**Exit:** reviewed keys persist, reopen identically, preview correctly, and compile without out-of-range values.

### Phase 7 — Deterministic production compiler

**Goal:** guarantee that creative intent becomes an executable, bounded manifest.

**Work:** implement full validation catalog, capability matching, cost/resource budgets, immutable manifest hashes, dependency graph, selected-scene invalidation, and actionable diagnostics.

**Exit:** invalid plans fail before GPU work; valid manifests are deterministic and reproducible.

### Phase 8 — Render orchestration and route qualification

**Goal:** select and execute the best real route for each shot.

**Work:** qualify priority video models; unify preflight; implement scene checkpointing, cache/resume, resource-aware scheduling, fenced publication, and truthful fallback.

**Exit:** representative multi-shot section renders with real motion, continuity, audio, and per-shot receipts.

### Phase 9 — Universal finishing and validation

**Goal:** make final success mean the same thing across every renderer.

**Work:** common assembly and validation service; frozen/black/corrupt detection; scene/manifest correspondence; audio sync; deviation report; atomic Outputs publication.

**Exit:** all supported lanes pass the same validator; deliberate negative fixtures fail closed.

### Phase 10 — Build Music Video orchestration

**Goal:** provide the polished default workflow without removing expert tools.

**Work:** Workspace stage machine, resume logic, autonomy controls, approval checkpoints, live readiness, actionable blockers, global job strip, and final summary.

**Exit:** a new user can complete the workflow from one guided surface and enter any specialist page without state loss.

### Phase 11 — Full-track end-to-end qualification

**Goal:** prove the product promise.

**Work:** run instrumental and lyrical projects through real Nemotron, optional Cosmos, storyboard, Timeline, full-motion rendering, finishing, validation, and reopen/recovery.

**Exit:** complete validated MP4s and authoritative receipts; documented performance, limitations, and fallbacks.

### Phase 12 — Release qualification

**Goal:** ship the exact native candidate honestly.

**Work:** performance/soak, accessibility, security, dependency, packaging, signing, clean install, upgrade, rollback, uninstall/data retention, offline and degraded-mode tests, Store certification evidence.

**Exit:** signed x64 candidate passes the established release gates. Model/runtime features advertise only the qualifications bundled or discoverable on the target machine.

---

## 14. Priorities and sequencing

### P0 — Required for the core promise

- Shared authoritative analysis and revision safety.
- Evidence-grounded lyricless interpretation.
- Real Nemotron qualification.
- Complete Story Bible/storyboard contracts.
- Safe camera/motion/reactive compilation.
- Production manifest and preflight.
- At least one qualified full-motion route.
- Universal validation and final receipt.
- Guided WinUI Build Music Video workflow.

### P1 — Required for professional strength

- Cosmos visual specialist qualification.
- Advanced camera/lens model and curve editing.
- Multi-route per-shot selection.
- Dependency-aware selected-shot rerender and caching.
- A/B review, continuity critique, and cost/time forecasting.
- Complete GPU/runtime observability.

### P2 — Differentiators after reliability

- Learned personalization from approved edits without leaking private media.
- Reusable visual DNA/style packages.
- Collaborative review and portable production manifests.
- Live-performance/real-time reactive modes using the same analysis/control contracts.
- Cloud render bursts and marketplace execution profiles.
- Advanced 3D scene, depth, segmentation, pose, and geometry control.

---

## 15. What makes EDMG Studio distinctive

The differentiator is not merely using NVIDIA models or generating video from music. The product stands out by combining:

1. **Music-native authorship:** decisions originate in full-track structure, evidence, and musical meaning rather than a generic prompt.
2. **Lyric-independent intelligence:** instrumental music receives the same serious directing workflow as lyrical music.
3. **Traceable creativity:** users can see why a scene exists, which musical evidence influenced it, and where interpretation begins.
4. **Director-to-production continuity:** the same Story Bible, storyboard, camera, motion, and reactive data reaches the Timeline and renderer instead of being discarded between tools.
5. **Professional editability:** every generated result is a draft with locks, revisions, undo/recovery, selective regeneration, and specialist surfaces.
6. **Deterministic compilation:** probabilistic model output is converted into bounded manifests before expensive rendering.
7. **Honest heterogeneous execution:** local workers, NIM/vLLM services, TensorRT paths, video models, interpolation, and external routes share one truthfully reported capability system.
8. **Receipt-backed production:** completion means validated media plus provenance, not a progress bar reaching 100 percent.
9. **Native Windows production UX:** a guided WinUI control room coexists with deep Timeline, Reactive Lab, Models, Render, and Review tools.
10. **Failure-resilient workflow:** missing lyrics, unavailable specialists, failed renderers, stale drafts, and interrupted jobs degrade explicitly without erasing approved work.

The product promise can therefore be stated as:

> EDMG Studio listens to the entire song, measures what happened, interprets what it may mean, helps the artist direct a coherent visual world, compiles that intent into editable production data, renders through the best qualified resources available, and proves that the final video matches the approved plan.

---

## 16. Definition of done

The blueprint is complete only when all of the following are true for the exact candidate being claimed:

- A complete real song imports and produces an authoritative analysis package.
- The workflow succeeds without lyrics.
- Nemotron performs real inference using the intended model revision and target execution plane.
- Cosmos Reason2, when enabled, performs a real bounded specialist review and can fail safely.
- The treatment and Story Bible persist across save/reopen and constrain regeneration.
- The storyboard covers the full song and every scene satisfies the required contract.
- Camera, motion, effects, and reactive schedules are editable, bounded, applied safely, and preserved.
- Manual and locked Timeline content survives regeneration unless explicitly replaced.
- Preflight identifies the actual installed models, runtimes, GPUs, costs, limits, and fallbacks.
- The selected real video route generates non-frozen full-motion material.
- Selected-scene rerender and resume do not corrupt or overwrite newer project state.
- Assembly preserves approved timing and audio.
- The universal validator checks the entire final artifact and blocks deterministic failures.
- The final output includes a complete production receipt and artifact hashes.
- Workspace provides the full guided flow while all specialist surfaces remain functional.
- The native app survives restart, backend interruption, worker failure, cancel/retry, save/reopen, and recovery without silent state loss.
- Automated suites, real runtime qualifications, packaging, signing, accessibility, security, and clean-machine gates pass for the exact release candidate.

Until those conditions are met, status reports must state precisely which layers are implemented, tested, runtime-qualified, or still unproven.

---

## 17. Immediate implementation package

The best next package is deliberately narrow and high-leverage:

1. Audit the present analysis schema against `AudioEvidencePackage` and record exact gaps.
2. Finalize shared provenance fields and maturity/status vocabulary.
3. Install and live-qualify the pinned Nemotron model with a compact evidence request.
4. Run a real instrumental project through interpretation, Story Bible, and storyboard generation.
5. Qualify Cosmos Reason2 on one reference image and one short generated clip.
6. Complete the storyboard-required-field validator.
7. Compile the reviewed project into an immutable `ProductionManifest`.
8. Add the WinUI Workspace stage tracker and **Build Music Video** orchestration around existing APIs.
9. Render one representative multi-scene section through a qualified full-motion route.
10. Apply the universal final validator and publish the first complete receipt.

That package proves the new NVIDIA intelligence layer and the production compiler before committing resources to a full-track render. Once it passes, the same path scales to a complete song and becomes the reference workflow for every subsequent renderer and release candidate.

---

## 18. Document governance

- This file is the audio-to-video production contract, not evidence that its phases are complete.
- `STUDIO_PROGRESS.md` remains the implementer/reviewer handoff.
- `blueprint/WINUI3_CONSOLIDATED_BLUEPRINT.md` remains the broader native-product and release plan.
- `blueprint/planning.md` retains detailed milestone history and acceptance records.
- Completed milestones and regression contracts in the available ChatLog records must be preserved.
- Missing external reference records are not treated as current evidence.
- When documents disagree, the stricter current code/test/runtime boundary, project-data preservation rule, and WinUI-first policy win.
- Update this blueprint when architecture or acceptance criteria change; record candidate-specific results and timestamps in the handoff or qualification receipts rather than rewriting requirements to match a passing implementation.

