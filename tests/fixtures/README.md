# Test fixture inventory

Small redistributable fixtures for CI and local verification. These are not user
project uploads; they live under `tests/fixtures/` so Studio storage never
treats them as live project data.

| Path | Kind | Purpose |
| --- | --- | --- |
| `audio/short_tone_1s.wav` | Audio (44 KB) | Fast import/analyze/assembly smoke tests |
| `audio/LANDR-Walkin' In That Rundown Town-Warm-Medium-REV_V1.wav` | Audio (~70 MB) | Real-song analyzer regression (keep duration-bounded) |
| `projects/starter_project.golden.json` | Project golden | Baseline `project.json` shape + starter timeline meta |
| `analysis/beat_grid.golden.json` | Analysis golden | Deterministic beat-grid contract |
| `analysis/sections.golden.json` | Analysis golden | Section/arc contract |
| `schedules/zoom_schedule.golden.json` | Schedule golden | Deforum schedule formatting contract |
| `media/frame_probe.golden.json` | Media golden | Expected probe/assembly metadata for short fixtures |

`tests/test_fixture_inventory.py` fails if any required fixture is missing or if
golden files drift from the locked expectations they encode.

## Optional Studio-wide TensorRT capability

EDMG Studio supports optional TensorRT acceleration through the shared backend runtime manager. Studio settings provide the global switch; native Render controls can override the preference, precision, and fallback for an individual internal render. Turning TensorRT off preserves the original runtime and does not require TensorRT to be installed.

This area retains its existing runtime and workflow; the shared Studio policy applies only to eligible internal inference components. The SD1.5 VAE decoder has an adapter; other model components remain on their existing runtimes until separately converted and validated. Hosted providers, audio processing, compositing, and exports do not acquire a TensorRT dependency. See the [Studio-wide TensorRT blueprint](../../EDMG_TensorRT_Full_Studio_Wide_Blueprint.md) for component admission and validation requirements.
