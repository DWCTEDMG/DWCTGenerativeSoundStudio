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

Start the Studio backend from `studio/edmg-studio/python_backend/`:

```bash
python3 -m edmg_studio_backend serve --host 127.0.0.1 --port 7863
```

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
