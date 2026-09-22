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

## Optional Studio-wide TensorRT capability

EDMG Studio supports optional TensorRT acceleration through the shared backend runtime manager. Studio settings provide the global switch; native Render controls can override the preference, precision, and fallback for an individual internal render. Turning TensorRT off preserves the original runtime and does not require TensorRT to be installed.

This area retains its existing runtime and workflow; the shared Studio policy applies only to eligible internal inference components. The SD1.5 VAE decoder has an adapter; other model components remain on their existing runtimes until separately converted and validated. Hosted providers, audio processing, compositing, and exports do not acquire a TensorRT dependency. See the [Studio-wide TensorRT blueprint](../../../EDMG_TensorRT_Full_Studio_Wide_Blueprint.md) for component admission and validation requirements.
