# Audio fixtures

`short_tone_1s.wav` is the preferred fast fixture (1 second, 22.05 kHz mono).
Use it for import, probe, and short analysis smoke tests.

`LANDR-Walkin' In That Rundown Town-Warm-Medium-REV_V1.wav` is a committed
real-audio fixture for deeper analyzer regression. It intentionally lives under
`tests/fixtures/audio/` so it is not treated as a Studio project upload or user
project asset.

Keep tests that use the long LANDR file bounded with short analysis durations
unless the test is specifically validating long-form behavior.

See `tests/fixtures/README.md` for the full fixture inventory.
