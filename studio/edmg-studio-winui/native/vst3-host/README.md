# EDMG Studio native VST3 scanner and host

These x64 helpers load third-party VST3 code outside the WinUI process. They use the official Steinberg VST3 SDK 3.8.1 pinned to commit `3cdf9ca5d1f5b1b21e0a86832aa4abe55607bd96`.

Configure and build from a Visual Studio Developer PowerShell. CMake fetches only the pinned SDK submodules required to compile the helpers; `VST3_SDK_ROOT` may point at an existing checkout for offline builds.

```powershell
cmake -S . -B build -A x64
cmake --build build --config Release --target EdmgStudio.Vst3Scanner EdmgStudio.Vst3Host
```

`EdmgStudio.Vst3Scanner.exe --scan-module` emits the bounded JSON v1 discovery contract and explicitly distinguishes supported effects from valid modules that expose no supported audio-effect classes. The managed scanner launches one process per module, enforces a timeout, supports cancellation, and terminates the process tree after a crash or hang.

`EdmgStudio.Vst3Host.exe --qualify` executes a complete component/controller lifecycle and a float32 process block. `--worker` runs one persistent plug-in instance behind paired named pipes; it supports repeated float32 stereo processing, MIDI note input, normalized parameter changes with rich metadata, component state capture/restore, latency reporting, clean shutdown, and test-only crash/hang probes. The scanner binary cannot launch workers, and the host binary does not accept scan operations. Studio treats a crashed or timed-out worker as a sticky deterministic bypass.

Windows AudioGraph file playback bridges decoded per-track float32 quantum buffers through `MixerProcessor` and its ordered VST3 inserts before submitting the processed master frame to WASAPI. The worker is process-isolated, but synchronous named-pipe transport and per-quantum managed allocations make this a functional preview path rather than a hard-realtime guarantee. Real-device audible playback, underrun behavior, and sustained low-latency performance require separate qualification.
