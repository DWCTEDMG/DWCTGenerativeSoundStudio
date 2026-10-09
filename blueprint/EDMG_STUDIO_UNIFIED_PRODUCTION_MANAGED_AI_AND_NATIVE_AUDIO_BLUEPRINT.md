# EDMG Studio unified production, managed AI, and native audio blueprint

Status: canonical program overview and acceptance ledger. Implementation presence is not gate acceptance.

## 1. Scope and source authority

The product is native WinUI 3. Audio-to-video production is the workflow spine;
managed intelligence is its planning/execution subsystem; JUCE is its optional
Timeline audio subsystem. Expert surfaces remain available alongside guided Workspace.

The following historical source documents retain their detailed requirements:

- [Production](EDMG_STUDIO_AUDIO_TO_VIDEO_PRODUCTION_BLUEPRINT.md)
- [Managed AI](EDMG_MANAGED_AI_RUNTIME_AND_CREATIVE_DIRECTOR_BLUEPRINT.md)
- [Native audio](../JUCE_WINUI_TIMELINE_AUDIO_ENGINE_BLUEPRINT.md)

The WinUI-local JUCE copy is a duplicate reference, not another program. This
document does not change those inputs. Source-specific acceptance criteria remain
required: consolidation must not weaken a requirement by omitting it from a summary.
Candidate commands, counts, identities, logs, and receipts belong in
[STUDIO_PROGRESS.md](../STUDIO_PROGRESS.md) and immutable evidence artifacts.

## 2. Authority and topology

```text
WinUI Workspace and specialist surfaces
  ├─ C# canonical project / Timeline / commands / undo / revisions
  │    └─ engine-neutral immutable audio projection
  │         ├─ AudioGraph: default and rollback
  │         └─ isolated JUCE host: optional Preview
  └─ Python control plane
       ├─ source analysis and audio evidence
       ├─ Nemotron Director and optional Cosmos specialist
       ├─ managed runtime supervision / GPU admission / receipts
       └─ deterministic production compilation / rendering / validation
```

C# owns native editing, canonical Timeline state, locks, commands, and recovery.
Python owns backend project persistence, analysis, AI jobs, runtime management,
render execution, and artifact publication through existing revisioned contracts.
Their projections must agree; neither an AI response nor an audio host may mutate
authoritative project state directly. JUCE owns execution snapshots and observations.

No Python, inference, network request, directory traversal, UI dispatch, blocking
lock, dynamic graph construction, or log flushing belongs in the audio callback.

## 3. Evidence vocabulary

| Dimension | Ordered states |
| --- | --- |
| Product | Designed → implemented → contract-tested → integration-tested → end-to-end-qualified → release-qualified |
| AI/runtime | Declared → installed → launchable → execution-ready → capability-qualified → production-qualified |
| Native audio | Source present → simulated → real process → device-qualified → Timeline-qualified → plugin/recording-qualified → packaged/release-qualified |

No lower state implies a higher one. Qualification is capability-specific: text
generation does not prove audio perception, image/video reasoning, valid DirectorPlan,
safe cancellation, production rendering, or sustained device playback. A healthy
backend means only that its declared checks passed. Installed weights require exact
revision, shard completeness, integrity, and compatible runtime evidence.

## 4. Canonical production flow

1. Create/open, import authorized source audio, hash/probe and associate it.
2. Analyze once; reuse revisioned timing, structure, energy, transcription, and cues.
3. Separate measured facts, model interpretations, and user artistic decisions.
4. Build treatment, Story Bible, scene variants, and continuity constraints.
5. Generate a Nemotron proposal; request Cosmos visual evidence when appropriate.
6. Review and edit scene, camera, motion, reactive, and renderer drafts.
7. Explicitly apply approved drafts to the canonical Timeline with revision checks.
8. Compile an immutable ProductionManifest from the approved project state.
9. Preflight media, models, routes, GPU resources, limits, and output authorization.
10. Render through admitted routes; expose progress, cancellation, recovery, ownership.
11. Interpolate, assemble, include source audio, and finish the requested output.
12. Universally validate, atomically publish, inspect the receipt, and save/reopen.

AudioEvidencePackage, InterpretationRecord, StoryBible, ScenePlan, ProductionManifest,
runtime descriptors/decisions/receipts, and native audio snapshots are versioned
contract families. Preserve unknown optional project extensions outside the runtime
projection; reject unknown required fields. Use explicit units, fixed-width numeric
fields, integer sample timing, source identities, project/graph revisions, snapshot
identities, command sequences, idempotency, bounded queues, and structured errors.

## 5. Managed intelligence and resources

Nemotron is the intended Director. Cosmos Reason2 is an optional observing/advising
specialist; it cannot apply changes. Qwen is an explicit compatibility/fallback model.
Transformers, vLLM, TensorRT-LLM, and NIM are distinct execution routes, not model identities.

Models exposes install, exact identity, license/size requirements, repair/removal,
capability evidence, smoke results, and receipts. Settings exposes policy and permitted
execution planes. Workspace exposes creative readiness and review/apply. Expert
diagnostics may disclose runtime details; ordinary production must not require ports,
container names, or terminal commands. Setup repairs prerequisites; Forge inspects
readiness and routes users to the workflow that owns each action.

Route selection admits only matching model/runtime/hardware/capability evidence.
GPU leases use physical identity, bounded memory admission, cancellation, expiry,
crash reconciliation, and workload ownership. Residency supports warm/cold policy,
explicit eviction, and coordination between Director, specialist, and render jobs.
Do not load large models into a GPU already committed to another workload.

Runtime fallback, model fallback, renderer fallback, and audio-engine fallback are
four separate policies. Report actual route, reason, and any degraded capability.
CPU execution requires explicit policy; it is never the silent GPU-environment default.

Pin dependencies and downloaded model code. Bind services to permitted interfaces,
authorize media/output paths, bound requests and queues, and keep secrets, media,
plugin state blobs, and sensitive payloads out of diagnostics. No model output may
execute tools or commands outside the existing authorized application boundary.

## 6. Native audio sequence

Phase 1 closes first. Phase 2 waits for accepted Phase 1 evidence. Phases 3–7 proceed
in dependency order. Phase 8 gathers all feasible parity, soak, and packaging evidence;
unavailable device, licensing, and release gates remain open.

| Phase | Required implementation and acceptance |
| --- | --- |
| 1: isolated lifecycle | Separate production host; authenticated versioned IPC; architecture/build/capability validation; bounded messages/writes/shutdown/restarts; cancellation, malformed/stale/duplicate events, crash/orphan handling; actual Settings states; x64 build and real-process handshake. No device claim. |
| 2: generated transport | Stable device identity and capabilities; typed negotiation; deterministic source; exact position; play/stop/pause/resume/seek/loop/end; command ordering; load/xruns/queue metrics; device loss/default change; representative rates/buffers; audible/device recovery evidence. |
| 3: Timeline media | Authorized bounded file-backed readers or owned shared memory; offsets/fades/resampling/channel mapping; immutable revisioned snapshots built off callback and activated atomically; missing/corrupt/stale/layout rejection; edited/long/reopened Timeline and replacement qualification. |
| 4: mixer/automation/meters | Tracks/buses/sends/master, gain/pan/mute/solo, cycle/channel validation, immutable exact-target automation and smoothing, bounded meters independent of UI cadence; deterministic parity and real callback consumption. |
| 5: plugins/PDC | Existing catalog/scanner identities and quarantine; separate scanning/hosting; audio/MIDI buses, parameters/state/bypass, latency and graph compensation; crash/hang isolation; AGain, instrument, representative effects; no arbitrary compatibility claim. |
| 6: bounce/recording | Same declared graph semantics; exact range/rate/depth/layout/format; cancellation/progress/receipt; authorized atomic output, no partial publication; recording only after device-qualified playback, with input/monitoring/preroll/latency/takes/recovery. |
| 7: Preview UX | Explicit Preview selection, stopped-only switching, devices/rate/buffer, actual lifecycle/capability/load/xruns/latency, restart and visible fallback; navigation/reopen/shutdown/suspend/recovery/accessibility/XAML qualification. |
| 8: parity/default gate | Representative AudioGraph/JUCE corpus, classified differences, sustained edits/seek/loops/replacement/meters/plugin faults/restarts/device loss, CPU/memory/handles/deadlines/recovery; native payload/discovery/repair; license inventory; signed/clean-machine servicing and customer flow. |

Exactly one engine owns the playback device. Switching drains callbacks while stopped,
captures sample position and snapshot identities, closes the old device, negotiates the
new one, restores position without autoplay, and explicitly falls back to AudioGraph
on failure. Large songs never travel as general JSON PCM payloads.

AudioGraph remains default and rollback until a separately accepted default decision.
That decision requires Timeline, mixer, automation, plugin, device, sustained-soak,
recovery, packaged-install, upgrade/rollback, clean-machine, and redistribution evidence.
Keep AudioGraph for at least one stable release after any approved default switch.
Preserve unsupported multichannel/object data; block unsupported execution rather than
silently flattening it while claiming preservation.

## 7. Acceptance ledger

| Gate | Evidence required to close |
| --- | --- |
| Contracts and preservation | Revision conflicts, locks, extension round-trip, sample timing, Director/Reactive draft recovery, reviewed camera/motion persistence, render-profile compatibility, schema importability, native XAML compilation |
| Director | Exact model/runtime identity; real text/audio capabilities where promised; schema-valid reviewed draft; locks; bounded repair; cancellation/recovery; native controls and receipt |
| Specialist | Authorized real visual input, evidence output, provenance, graceful unavailable/invalid response, no project mutation |
| Runtime fabric | Ownership, launch/shutdown/restart, physical GPU admission/residency, route evidence, crash cleanup, allowed execution planes, explicit fallbacks |
| Production compiler | Deterministic manifest from approved revision; input hashes, render/effect schedules, route/resource decisions, validation and stale rejection |
| Video routes | Real temporal output for each admitted route, exact runtime/model/device receipts, frame/duration/quality checks; no still/proxy/cache substitution |
| Finishing | Timing/frame/audio synchronization, declared codec/layout, valid independent decode, cancellation and atomic publication |
| Complete production | Representative full-track import through intelligence, reviewed apply, temporal render, finishing, universal validation, save/reopen, cancellation/recovery, final receipt without manual repair |
| Native audio | The accepted dependency-ordered Phase 1–8 requirements above, with device and simulation evidence separated |
| Release | Licensing/redistribution, dependency closure, signed candidate, supported hardware, accessibility/customer flow, clean-machine install/launch/repair/upgrade/rollback/uninstall/data retention; applicable Store evidence |

Recorded historical tests and builds are baseline evidence. Re-run relevant regressions
after changes; do not promote them to current qualification merely because source
matches an earlier branch. Production and release gates remain open until explicit receipts.

## 8. Source coverage matrix

Every source section is retained by reference in addition to the consolidated requirements.

| Source sections | Consolidated owner | Treatment |
| --- | --- | --- |
| Production 1–4: vision/principles/baseline/architecture | 1–4 | Merged product spine and authority; historical baseline stays in source/handoff |
| Production 5–6: contracts and stages 0–15 | 4, 7 | Retained contract families and full workflow; detailed field/stage criteria remain required |
| Production 7–8: WinUI and intelligence | 4–5 | Merged surfaces and Director/specialist roles |
| Production 9–12: rendering, receipts, security, qualification | 3, 5, 7 | Merged evidence/resource/security policies; route-specific tests retained |
| Production 13–18: roadmap, priorities, distinctiveness, done, governance | 7–9 | Retained production gates/order and document governance |
| Managed AI 1–7: baseline, goals, architecture, identity, contracts, routing | 1–5 | Merged ownership/identity/evidence; detailed schemas remain in source |
| Managed AI 8–10: adapters, defaults, GPU/residency | 5, 7 | Retained interchangeable routes, exact evidence, admission/eviction |
| Managed AI 11–13: orchestration, WinUI, internal APIs | 4–5, 7 | Retained draft/apply, native ownership, lifecycle APIs |
| Managed AI 14–17: security, observability, fallback, performance | 3, 5, 7 | Deduplicated shared policy; four fallbacks remain separate |
| Managed AI 18–24: phases/tests/acceptance/risks/files/done/order | 7–9 | Retained all managed-AI completion criteria and qualification ladders |
| JUCE architecture/contracts/runtime/UX requirements | 2–3, 6–7 | Embedded native subsystem; original detailed requirements retained |
| JUCE Phases 1–8 and default decision | 6–7 | Dependency order and unavailable external gates explicit |
| Duplicate WinUI-local JUCE blueprint | 1 | Deduplicated source, no acceptance criterion removed |

## 9. Delivery order and definition of done

1. Establish candidate-bound truth ledger and freeze contracts/preservation requirements.
2. Confirm JUCE Phase 1 prerequisite and qualify Phase 2 devices before later acceptance.
3. Qualify real Director/specialist routes; implement managed supervision and GPU admission.
4. Complete canonical evidence, Story Bible/scene review, production compiler, render routes,
   finishing, and universal validation. Advance JUCE Phases 3–7 as prerequisites close.
5. Qualify a full-track WinUI production workflow and native-audio representative corpus.
6. Gather Phase 8 local evidence; close external release gates only with actual evidence.

Done means a user can install/qualify the intended models through WinUI, analyze a song
once, generate a real evidence-grounded proposal, review/apply/edit, render a valid
full-track artifact, cancel/recover/save/reopen, and inspect the actual execution receipt.
Native audio and packaged release have their own additional accepted gates. No lower
state, endpoint health, simulated result, or source presence substitutes for these gates.
