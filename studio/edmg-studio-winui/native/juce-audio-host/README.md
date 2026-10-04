# EDMG Studio JUCE audio host

`EdmgStudio.JuceAudioHost` is the isolated JUCE 8 preview process used by the native WinUI client. It
is a real integration target, separate from `juce_example`, but it is not yet the default production
Timeline engine. Windows AudioGraph remains the normal playback and rollback path.

## Build

From a Visual Studio Developer PowerShell:

```powershell
cmake -S . -B build -A x64
cmake --build build --config Release --target EdmgStudio.JuceAudioHost
cmake --install build --config Release --prefix out
```

Run those commands from this directory. By default CMake fetches JUCE 8.0.0; set `JUCE_ROOT` to an
existing compatible checkout for an offline build. Installation places the executable under `bin`
and copies JUCE's license text under `licenses`.

## Implemented contract

The host reads one bounded JSON protocol envelope per standard-input line and emits correlated events
on standard output. Protocol v1 negotiates architecture and lifecycle support before accepting device,
Timeline, render, or transport commands. The managed client owns authentication, process lifetime,
timeouts, cancellation, stale-message rejection, and diagnostics.

Current native behavior includes shared-mode output-device enumeration/configuration, device close,
transport configuration, immutable prepared-Timeline snapshots, monotonically increasing revisions,
play/stop/seek/loop commands, sample-position status, deterministic bounded render probes, and a
128-sample crossfade when a new snapshot is published at an audio callback boundary. Timeline sources
carry embedded stereo float32 PCM solely for deterministic proof and tests.

## Qualification boundary

Do not describe this host as complete production playback. Protocol messages are capped at 1 MiB, so
full songs require file-backed or memory-mapped prepared media. The native graph still needs canonical
mixer/bus/send/automation/VST3/latency/meter projection and shared preview/bounce behavior. WinUI
playhead, video, scrubbing, Reactive Lab, and render handoff must follow the JUCE sample clock when it
owns playback. Host crashes, device loss, plugin hangs, and rejected revisions need tested safe fallback
without simultaneous device ownership or project mutation.

Deterministic renders validate DSP behavior only. They do not establish WASAPI continuity, callback
deadlines, xruns, suspend/resume, device switching, or audible output. Release also requires a compatible
JUCE commercial license or AGPL compliance, complete third-party notices, MSVC runtime handling,
redistribution review, and clean-machine package qualification.
