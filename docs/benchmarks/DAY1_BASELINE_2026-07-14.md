# Day 1 baseline - Windows - 2026-07-14

Machine-readable evidence: [day1-baseline-windows-2026-07-14.json](day1-baseline-windows-2026-07-14.json)

## Named hardware and software

- HP Victus by HP Gaming Laptop 15-fa2xxx
- Intel Core i5-13420H, 8 physical cores / 12 logical processors
- 15.6 GiB usable RAM
- NVIDIA GeForce RTX 4050 Laptop GPU, 6,141 MiB, driver 610.62
- Windows 11 Pro for Workstations build 26200
- Python 3.12.10, uv 0.11.28, Node 24.16.0, pnpm 10.33.0
- FFmpeg 8.1.1 local developer binary
- Clean source commit `b004cc2397da79e27cb9beb2f980e70fd53621c7`

## Recorded timings

| Probe | Result | Scope |
|---|---:|---|
| Backend launch to `/health` | 13,383.724 ms median, 3 runs | Source backend process, isolated Studio home |
| Project open | 0.149 ms median, 25 runs | ProjectStore disk read plus legacy-to-v1 adapter |
| Reactive timeline merge | 20.390 ms median, 25 runs | 240-second timeline, 240 cues, 480 camera keyframes |
| Local audio analysis | 7,436.471 ms cold; 78.844 ms median | Full librosa pass, cache disabled, one-second WAV |
| Electron shell launch | 3,855.898 ms | Strict instrumented shell probe with mock backend |
| Python test scopes | 83,133.219 ms | 87 repo tests passed, 4 opt-in live-smoke skips; 193 backend tests passed |

These are evidence baselines, not approved budgets. The Electron probe is a real test-mode shell
launch rather than an installed production build. Project and timeline probes measure backend work,
not browser paint latency. Model render quality/performance, installed-app launch, cancellation, and
recovery remain later evidence gates.

The strict Electron run also verified that the test shell uses its ephemeral mock backend instead of
stale launcher state. Both synchronous and asynchronous bridge URL checks passed.
