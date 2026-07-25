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
