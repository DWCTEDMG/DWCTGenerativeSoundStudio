# JUCE Backend Client Example

This small C++ console application uses JUCE networking to call the canonical
EDMG Studio backend over HTTP. Keeping Python and ML work behind HTTP avoids
running it on a real-time audio thread and makes the client portable across
Windows, macOS, and Linux.

The example currently performs `GET /health`; it is a connectivity example, not
a complete audio plugin.

## Requirements

- CMake 3.20 or newer
- A C++ toolchain: MSVC, Xcode, GCC, or Clang
- Internet access during configure because CMake FetchContent downloads JUCE

## Build

From this directory:

```bash
cmake -S . -B build
cmake --build build --config Release -j
```

## Run

Start the Studio backend from the repository root with the pinned Python 3.12/uv environment:

```bash
uv run --project studio/edmg-studio/python_backend --frozen --no-sync \
  python -m edmg_studio_backend serve --host 127.0.0.1 --port 7863
```

This reuses the selected accelerator environment. Provisioning CPU is an explicit opt-in, not a
connectivity-test prerequisite.

Then run the client on Linux/macOS:

```bash
./build/edmg_juce_client http://127.0.0.1:7863
```

For a multi-config Windows generator, the executable is commonly under
`build\Release\edmg_juce_client.exe`:

```powershell
.\build\Release\edmg_juce_client.exe http://127.0.0.1:7863
```

If no URL is passed, the client defaults to `http://127.0.0.1:7863`.

## Optional Studio-wide TensorRT capability

EDMG Studio supports optional TensorRT acceleration through the shared backend runtime manager. Studio settings provide the global switch; native Render controls can override the preference, precision, and fallback for an individual internal render. Turning TensorRT off preserves the original runtime and does not require TensorRT to be installed.

This area retains its existing runtime and workflow; the shared Studio policy applies only to eligible internal inference components. The SD1.5 VAE decoder has an adapter; other model components remain on their existing runtimes until separately converted and validated. Hosted providers, audio processing, compositing, and exports do not acquire a TensorRT dependency. See the [Studio-wide TensorRT blueprint](../EDMG_TensorRT_Full_Studio_Wide_Blueprint.md) for component admission and validation requirements.
