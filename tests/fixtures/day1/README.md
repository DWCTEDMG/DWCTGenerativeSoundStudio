# Redistributable Day 1 fixtures

This directory is the small, clean-clone fixture set used by contract, project, media, and baseline
tests. Every payload file is under 64 KiB, has a SHA-256 entry in `goldens/manifest.json`, and is
covered by `tests/test_day1_fixture_inventory.py`.

| File | Purpose | Expected properties |
|---|---|---|
| `audio/tiny_pulse.wav` | Deterministic audio-analysis input | PCM16 mono, 8 kHz, 8,000 frames, 1 second, four pulses |
| `media/reference_frame.svg` | Image/reference-media input | Standalone 64 x 64 SVG with no external resources |
| `project/project.json` | Current legacy project compatibility input | References the audio and media fixtures and adapts to `edmg.project` v1 |

Regenerate and verify the WAV from the repository root:

```powershell
py -3.12 scripts/generate_day1_fixtures.py
py -3.12 scripts/generate_day1_fixtures.py --check
```

See `LICENSE.md` for redistribution terms. The 73 MB real-audio fixture in the adjacent `audio/`
directory remains an integration fixture and is not part of this small redistributable inventory.
