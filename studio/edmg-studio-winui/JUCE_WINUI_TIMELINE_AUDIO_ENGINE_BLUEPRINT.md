# JUCE + WinUI Timeline Audio Engine Blueprint

**Status:** Proposed implementation plan; no JUCE Timeline integration is implied by this document.

**Product boundary:** WinUI 3 remains the native Studio product surface. JUCE becomes an optional real-time audio engine behind the existing Timeline and DAW contracts. The shared Python backend remains responsible for AI, analysis, planning, and render services and must never run work on the real-time audio thread.

**Related authority:** `blueprint/WINUI3_CONSOLIDATED_BLUEPRINT.md`, `blueprint/planning.md`, and `AGENTS.md`. Where this proposal conflicts with current source behavior or an accepted gate, the current implementation and stricter fail-closed rule win.

## 1. Goal

Add a production-quality JUCE audio engine to the native Studio Timeline without replacing the WinUI editing experience or destabilizing the working WASAPI shared-mode AudioGraph path.

The integration must support incremental adoption, deterministic project behavior, explicit runtime capability states, and immediate rollback to AudioGraph. It must not turn the existing `juce_example` health-check console program into the production engine.

## 2. Architectural decision

Use a dedicated JUCE C++ engine component with a versioned typed boundary. Keep WinUI 3 and the existing C# Core model authoritative for editing, persistence, commands, undo/redo, and presentation.

Recommended topology:

```text
WinUI 3 Timeline / Mixer / Settings
                |
                v
EdmgStudio.Core audio-engine contracts
                |
       engine selection + adapter
          /                     \
         v                       v
Windows AudioGraph       JUCE engine host
(existing fallback)      (new C++ component)
                                  |
                                  +--> audio/MIDI devices
                                  +--> transport and mixer graph
                                  +--> plugin processing
                                  +--> metering and diagnostics

WinUI / Core --> shared Python backend --> analysis, AI, planning, rendering
                     (never called from a real-time callback)
```

### Recommended deployment shape

Begin with an out-of-process local engine host and a small native protocol library. A process boundary provides crash isolation for audio drivers and third-party plugins, allows independent engine restart, and avoids bringing JUCE and plugin faults into the WinUI process. Reconsider an in-process DLL only after the protocol and recovery behavior are proven and measured latency shows the process boundary is unsuitable.

The existing `juce_example` remains a connectivity sample. Create a separate production target rather than expanding the sample executable.

## 3. Non-negotiable design rules

1. WinUI owns visible Timeline, mixer, plugin, device, settings, diagnostics, and recovery UI.
2. The canonical C# project and Timeline documents remain authoritative; JUCE receives immutable runtime snapshots and emits runtime observations.
3. Exactly one engine owns playback and the selected audio device at a time.
4. AudioGraph remains the default until the JUCE candidate passes its acceptance gates.
5. Engine switching is allowed only while transport is stopped and after all callbacks are drained.
6. No network, Python, AI/model inference, filesystem traversal, project mutation, UI dispatch, blocking lock, logging flush, or dynamic graph construction occurs on the real-time thread.
7. Real-time state uses preallocated buffers, immutable snapshots, lock-free or bounded single-producer/single-consumer queues, and explicit overflow behavior.
8. Sample positions are the synchronization authority. Wall-clock time is diagnostic only.
9. Plugin scanning and plugin execution stay isolated. A failed or hung plugin cannot make the Studio claim that the engine is healthy.
10. Existing projects open unchanged. Engine preferences are optional, versioned settings and must not rewrite Timeline content.
11. Preserve Director-to-Reactive Lab draft recovery, reviewed camera/motion keyframes, render profiles, extension data, revision semantics, and WinUI XAML compilation.
12. Capability labels distinguish code presence, deterministic simulation, process health, device qualification, plugin qualification, and audible real-device evidence.

## 4. Component responsibilities

### 4.1 WinUI 3

WinUI continues to provide:

- Timeline editing, selection, snapping, waveform presentation, and transport controls.
- Track, bus, send, automation, plugin, meter, device, and routing presentation.
- Project save/reopen/recovery, revision checks, undo/redo, and user approval.
- Engine selection and honest readiness diagnostics in Settings and Timeline.
- Actionable failures, restart controls, fallback decisions, and qualification receipts.

WinUI must not directly perform DSP or issue per-sample/per-buffer UI calls.

### 4.2 EdmgStudio.Core

Core provides the engine-neutral domain boundary:

- Canonical transport and Timeline projection.
- Immutable mixer and automation snapshots.
- Engine lifecycle state machine and capability model.
- Validation, negotiation, stale-revision rejection, and fallback policy.
- Conversion between existing project contracts and the runtime protocol.
- Test doubles and deterministic callback harnesses shared by both engines where practical.

### 4.3 JUCE engine host

The host owns:

- Audio and MIDI device discovery, opening, negotiation, callbacks, and shutdown.
- Sample-accurate transport, looping, seeking, preroll, and discontinuity handling.
- Clip readers, resampling, channel mapping, fades, gain, pan, buses, sends, and master output.
- Immutable automation consumption and parameter smoothing.
- Plugin instantiation, processing, state, latency, bypass, and fault containment.
- Plugin-delay compensation and graph-latency reporting.
- Real-time meters, callback timing, underrun/overrun counters, and bounded diagnostics.
- Offline bounce using the same graph semantics where deterministic equivalence is supported.

The host does not own project files, user edits, render jobs, AI planning, or backend credentials.

### 4.4 Shared Python backend

The backend continues to own media analysis, Whisper, provider planning, Director review, reactive generation, model management, and video rendering. Communication remains asynchronous and outside the audio callback. Results enter the canonical project workflow through existing revision-safe application boundaries before they can affect JUCE runtime snapshots.

## 5. Typed boundary

Define a versioned protocol covering the following contract families.

| Contract | Required content |
| --- | --- |
| Handshake | Protocol version, build identity, architecture, feature flags, engine state, compatibility result |
| Device | Stable ID, name, API, input/output channels, sample rates, buffer sizes, exclusive/shared support, current selection |
| Transport | Project revision, play/stop/pause, exact sample position, sample rate, loop range, preroll, seek sequence |
| Timeline snapshot | Snapshot ID, project revision, tracks, clips, source IDs, exact source/timeline sample ranges, fades, channels |
| Mixer snapshot | Tracks, buses, sends, gain, pan, mute/solo, inserts, routing, channel layouts, graph revision |
| Automation snapshot | Target IDs, sample-domain points/segments, interpolation, snapshot revision |
| Plugin | Stable instance ID, module identity/hash, bus layout, parameters, state blob reference, latency, bypass, health |
| Meter frame | Sequence, engine sample position, peaks, RMS, clipping, optional loudness, dropped-frame count |
| Diagnostics | Callback load, xruns, queue pressure, device loss, plugin failure, protocol errors, restart count |
| Offline render | Exact range, format, channels, sample rate, output authorization, progress, cancellation, receipt |

### Boundary requirements

- Use fixed-width numeric fields and explicit units.
- Represent Timeline positions as integer samples, not floating-point seconds.
- Version envelopes and support capability negotiation before opening a device.
- Reject unknown required fields and preserve unknown optional project fields outside the runtime projection.
- Include project revision, graph revision, snapshot ID, and monotonically increasing command sequence where applicable.
- Make commands idempotent or explicitly non-repeatable.
- Return structured errors; never convert failed initialization into a healthy state.
- Keep large audio data out of general control messages. Use bounded shared memory or engine-owned readers after authorization and lifecycle semantics are proven.

## 6. Engine lifecycle and state model

Use explicit states:

```text
Unavailable -> Discovered -> Compatible -> Starting -> Ready
Ready -> Running -> Suspended -> Ready
Ready/Running -> Degraded -> Restarting -> Ready
Any active state -> Failed
Any stopped state -> ShuttingDown -> Stopped
```

Each transition records a reason, timestamp, protocol/build identity, device identity when relevant, and whether fallback is safe. UI labels must not report `Ready` until handshake, snapshot load, device negotiation, callback startup, and a bounded continuity probe succeed.

## 7. Engine selection and rollback

Add an audio-engine setting with these values:

- **AudioGraph (stable):** existing behavior and initial default.
- **JUCE (preview):** selectable only when compatible and qualified to the configured level.
- **Automatic:** introduced only after JUCE has passed the full parity gate; until then it resolves to AudioGraph.

Switch procedure:

1. Stop transport and reject new transport commands.
2. Capture exact sample position and current canonical snapshot IDs.
3. Fade out and drain the active engine.
4. Close its device and confirm callback termination.
5. Start the target engine, negotiate the device, and load snapshots.
6. Seek to the captured sample position without auto-playing.
7. Expose success or a structured failure.
8. If JUCE startup fails, restore AudioGraph explicitly and report the fallback; never play both.

A crash while playing must stop transport state, release or recover the device, preserve project edits, and offer restart or AudioGraph fallback. Silent automatic continuation is allowed only after a tested policy proves position and state continuity; otherwise user confirmation is required.

## 8. Delivery phases

### Phase 0 - Baseline and acceptance lock

**Work**

- Inventory current AudioGraph transport, mixer, automation, VST3 worker, offline export, recording, and device qualification behavior.
- Capture current contracts, tests, latency behavior, known limitations, and real-device evidence.
- Define a representative project corpus: single clip, edited clips, loop, automation, buses/sends, plugin, resampling, long project, missing media, and unsupported channel layout.
- Record AudioGraph rollback behavior and protect it with regression tests.

**Exit gate**

- Baseline behavior and capability limitations are documented.
- The corpus opens without mutation and produces repeatable reference observations.
- No claim is made that JUCE is integrated.

### Phase 1 - Protocol and lifecycle skeleton

**Work**

- Add a production JUCE host target separate from `juce_example`.
- Define versioned handshake, lifecycle, command, event, and error envelopes.
- Add a C# adapter and deterministic fake host.
- Implement process launch, authentication appropriate to local IPC, graceful shutdown, crash detection, restart limits, and build/protocol compatibility checks.
- Do not open an audio device or process project audio yet.

**Exit gate**

- WinUI can display unavailable, incompatible, starting, ready-without-device, failed, and stopped states truthfully.
- Host crash/restart and stale-message tests pass.
- AudioGraph behavior is unchanged.

### Phase 2 - Device and transport proof

**Work**

- Implement device enumeration and explicit selection.
- Negotiate sample rate, buffer size, channels, and shared/exclusive mode without silently changing project data.
- Implement transport commands and exact sample-position reporting using a generated tone or bounded test source.
- Handle start, stop, pause, seek, loop, device loss, default-device change, and shutdown.

**Exit gate**

- Deterministic transport tests pass across multiple sample rates and buffer sizes.
- Real-device qualification proves continuous playback, loop and seek behavior, device-loss recovery, and bounded callback load.
- The result is labeled device-qualified, not full Timeline-qualified.

### Phase 3 - Timeline clip playback

**Work**

- Project canonical Timeline tracks and clips into immutable runtime snapshots.
- Add authorized media readers, source/timeline sample mapping, clip offsets, fades, resampling, and channel mapping.
- Queue snapshot changes outside the callback and swap them at safe boundaries.
- Preserve missing-media and unsupported-layout errors.

**Exit gate**

- Single and multi-clip projects match expected sample positions and durations.
- Seek, loop, edit-while-stopped, and snapshot replacement tests pass.
- Long playback has no unbounded allocation, blocking callback work, or unexplained discontinuity.

### Phase 4 - Mixer, automation, and meters

**Work**

- Implement tracks, buses, sends, master, gain, pan, mute/solo, and channel layout negotiation.
- Consume immutable automation snapshots with smoothing and exact target IDs.
- Stream bounded meter frames independently of UI refresh rate.
- Implement latency accounting before adding plugins.

**Exit gate**

- Existing mixer and automation semantics have parity tests against deterministic references.
- Meter backpressure drops old observations without blocking audio.
- Routing cycles and invalid targets fail before snapshot activation.

### Phase 5 - Plugin hosting and delay compensation

**Work**

- Reuse existing scanner/qualification evidence and stable plugin identities where compatible; do not create a second conflicting catalog.
- Keep scanning out of process and separate from real-time hosting.
- Implement plugin load, buses, process, MIDI/events, parameters, state round-trip, bypass, latency, graph rebuild, timeout, crash isolation, and quarantine.
- Implement plugin-delay compensation and report total graph latency.

**Exit gate**

- The already-qualified Steinberg AGain path passes in the JUCE host.
- At least one instrument and a representative set of effects pass scan/load/process/state/latency/restart tests before broad compatibility is claimed.
- Plugin failure cannot corrupt project state or take down WinUI.
- Arbitrary third-party compatibility and hard-real-time safety remain unclaimed without evidence.

### Phase 6 - Offline bounce and recording

**Work**

- Implement cancellable offline bounce using the same graph semantics, with explicit format, range, sample rate, bit depth, channels, and receipt.
- Add recording only after output playback is stable: input selection, monitoring, latency disclosure, pre-roll, take lifecycle, safe temporary files, atomic publication, and recovery.
- Keep unsupported multichannel/object layouts preserved and visible.

**Exit gate**

- Offline output is deterministic where plugin behavior permits and reports nondeterministic components honestly.
- Cancellation leaves no published partial artifact.
- Recording requires real-device evidence; simulation alone cannot enable the capability.

### Phase 7 - WinUI preview and opt-in rollout

**Work**

- Add Settings engine selector, device panel, buffer/sample-rate controls, capability level, diagnostics, restart, and fallback controls.
- Add Timeline engine state, device status, xruns, callback load, graph latency, and actionable error presentation.
- Gate JUCE behind an explicit preview setting and preserve AudioGraph as the default.
- Add telemetry/logging that contains no project media, credentials, plugin state blobs, or sensitive paths beyond established policy.

**Exit gate**

- Running-app navigation, repeated page entry, engine switching while stopped, backend restart, suspend/resume, shutdown, and project reopen pass.
- UI automation and XAML compilation pass.
- Users can always return to AudioGraph without editing project files.

### Phase 8 - Parity, soak, and default decision

**Work**

- Run the project corpus through both engines and classify intentional differences.
- Perform sustained playback, edit, loop, seek, plugin fault, device loss, suspend/resume, and memory/handle leak testing.
- Qualify packaged x64 deployment, native dependencies, host discovery, repair, upgrade, and rollback.
- Review licensing and redistribution obligations for JUCE and bundled native components before release.

**Exit gate**

JUCE may become the default only when:

- Timeline, mixer, automation, plugin, device, and recovery parity is accepted.
- Real-device continuity and underrun targets pass on the supported hardware matrix.
- Packaged install, upgrade, rollback, and clean-machine launch pass.
- AudioGraph remains available for at least one stable release unless a separately approved removal plan proves migration and rollback equivalence.

## 9. Validation matrix

| Area | Minimum evidence |
| --- | --- |
| Contracts | Serialization round-trip, version negotiation, unknown optional fields, rejected incompatible required fields |
| Lifecycle | Start/stop/restart, crash, hung host, stale event, duplicate command, WinUI shutdown |
| Transport | Exact sample start, pause/resume, seeks, loop boundaries, rapid commands, end-of-stream |
| Media | 44.1/48/96 kHz, mono/stereo, bit-depth variants, missing/corrupt source, resampling, long file |
| Mixer | Gain/pan, mute/solo, buses, sends, cycle rejection, channel negotiation, clipping |
| Automation | Boundary points, dense curves, ramps, snapshot replacement, target deletion |
| Plugins | Scan, load, process, state, latency, bypass, MIDI, crash, timeout, quarantine, restart |
| Devices | Shared/exclusive where supported, buffer changes, disconnect, default change, suspend/resume |
| Performance | Callback deadline, xruns, CPU, memory, handles, meter backpressure, sustained soak |
| Offline | Range accuracy, format, cancellation, atomic publication, receipt, realtime/offline comparison |
| Packaging | Fresh x64 build, native payload manifest, clean install, upgrade, repair, rollback, uninstall |
| Studio regressions | Project reopen, revision safety, undo/redo, Director/Reactive recovery, reviewed keyframes, render profiles, XAML build |

## 10. Initial measurable targets

Targets must be finalized from Phase 0 baseline data rather than invented from deterministic simulation. Initial engineering objectives are:

- Zero blocking operations and zero heap allocation in steady-state audio callbacks under the chosen JUCE path.
- No unexplained sample-position discontinuity across continuous playback.
- Bounded command, event, meter, and diagnostic queues with visible drop/overflow counters.
- No simultaneous AudioGraph and JUCE device ownership.
- No project mutation caused solely by selecting, starting, failing, or falling back from an engine.
- No published offline artifact after cancellation or failed validation.
- A sustained real-device soak with zero xruns on the declared supported configuration before default eligibility.

## 11. Proposed repository layout

Exact names may follow existing solution conventions after implementation discovery:

```text
native/
  edmg-juce-audio-host/
    CMakeLists.txt
    src/
    tests/

studio/edmg-studio-winui/
  src/EdmgStudio.Core/Audio/
    AudioEngineSelection.cs
    AudioEngineCapabilities.cs
    JuceAudioEngineProtocol.cs
    JuceAudioEngineClient.cs
  Services/
    JuceAudioEngineService.cs
  tests/EdmgStudio.Core.Tests/
    JuceAudioEngineProtocolTests.cs
    JuceAudioEngineLifecycleTests.cs
```

Do not move or rename the existing example until repository consumers and documentation are audited. Do not merge the JUCE host with the existing VST3 helper executables without an explicit compatibility and isolation design.

## 12. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Two engines compete for the device | Single ownership state machine; stopped-only switching; callback-drain acknowledgement |
| IPC adds jitter or latency | Keep audio and graph processing in the host; IPC carries control snapshots and observations, not callback-paced audio |
| Plugin crashes destabilize playback | Scanner/host isolation, quarantine, bounded restart, project state retained in Core |
| Snapshot update blocks callback | Build off-thread, validate fully, atomically swap immutable snapshot |
| C#/C++ contract drift | Versioned schema, generated or centrally tested constants, compatibility fixtures in both languages |
| UI meter traffic overwhelms process | Fixed-rate bounded frames, sequence numbers, latest-value coalescing, drop counters |
| Device changes alter project timing | Keep project positions sample-based; negotiate runtime conversion without rewriting canonical Timeline |
| JUCE packaging breaks Store release | Explicit native payload manifest, license review, packaged-host discovery tests, clean-machine gate |
| New engine regresses accepted Studio flows | Preserve AudioGraph, use feature flag, run required regression set at every behavioral phase |
| Python work reaches callback | No backend client in host callback graph; asynchronous application through canonical revision-safe workflow |

## 13. Definition of completion

The JUCE Timeline engine is complete only when the native WinUI application can select it, negotiate a real device, load the canonical Timeline and mixer state, play and seek continuously, process qualified plugins and automation, recover from host/plugin/device failure, bounce safely, preserve project and workflow semantics, and return to AudioGraph without data loss. All claimed capabilities require matching real-runtime evidence and packaged x64 qualification.

Until that gate is accepted, JUCE remains an optional preview engine and `juce_example` remains only a backend-connectivity sample.
