# Video benchmarking

## Day 1 product baseline

The modernization baseline records source-backend launch, project open plus compatibility adaptation,
reactive-timeline merge, local audio analysis, an instrumented Electron smoke launch, and the full
Python test-scope wall time on named hardware. It does not run model downloads or infer render
quality from CPU timings.

From the repository root:

```powershell
py -3.12 scripts/benchmark_day1_baseline.py `
  --include-electron `
  --include-tests `
  --output docs/benchmarks/day1-baseline-windows-2026-07-14.json
```

The JSON result includes exact hardware/software identity, commit, methodology, samples, summary
statistics, command results, and explicit limitations. Day 7 performance evidence should compare
the same probes on equivalent hardware and add installed-build UI, cancel, and recovery timings.

The Electron figure is a real shell process launch using the repository's instrumented integration
page and mock backend; it is not presented as an installed production-build launch time. Likewise,
project and timeline figures are backend-operation baselines rather than browser paint latency.

## Model rendering harness

EDMG includes a multi-model benchmarking harness:

- `studio/edmg-studio/scripts/video_model_bench.py` (spawns one process per model)

It runs the same prompt across multiple Diffusers pipelines and writes:
- per-model MP4 outputs
- `bench_report.json` with timings and errors
- optional `bench_grid.png` (first-frame montage)

## Example

```bash
python studio/edmg-studio/scripts/video_model_bench.py \
  --prompt "A macro shot of raindrops on neon glass, cinematic lighting" \
  --bench-name smoke \
  --quick
```

## Notes

- `bench_grid.png` requires `imageio` + ffmpeg support (`pip install imageio imageio-ffmpeg`).
- Large models (Wan 14B, LTX-2 19B) can require very large VRAM; use `--cpu-offload` to trade speed for memory.
