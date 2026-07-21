# Video benchmarking

EDMG includes a multi-model benchmarking harness:

- `studio/edmg-studio/scripts/video_model_bench.py` (spawns one process per model)

It runs the same prompt across multiple Diffusers pipelines and writes:
- per-model MP4 outputs
- `bench_report.json` with timings and errors
- optional `bench_grid.png` (first-frame montage)

## Example

```bash
uv run --project studio/edmg-studio/python_backend --frozen \
  --extra cuda --extra core --extra audio --extra internal-video \
  python studio/edmg-studio/scripts/video_model_bench.py \
  --prompt "A macro shot of raindrops on neon glass, cinematic lighting" \
  --bench-name smoke \
  --quick
```

## Notes

- `bench_grid.png` requires the image/video dependencies declared in the locked
  internal-video capability and FFmpeg. Add missing packages to `pyproject.toml`
  and update `uv.lock`; do not patch a benchmark environment ad hoc.
- Large models (Wan 14B, LTX-2 19B) can require very large VRAM; use `--cpu-offload` to trade speed for memory.
