# Architecture

## Goals
- EDMG Studio provides a desktop UI (Electron) backed by a local FastAPI service.
- The backend exposes a stable JSON API envelope: `{ "ok": true|false, ... }`.
- Errors intended for users follow a structured `UserFacingError` format.

## High-level components
### Desktop App (Node/TS)
- Package root: `studio/edmg-studio/`
- Package manager: `pnpm@10.33.0` via `packageManager`
- Typecheck: `pnpm run typecheck`
- Dev: `pnpm run dev`

### Native Windows App (WinUI 3 / MSIX)
- Package root: `studio/edmg-studio-winui/`
- Target: `net10.0-windows10.0.26100.0`, Windows App SDK 2.3.1, x64
- The native client uses the same authenticated localhost API and Python/CUDA backend as Electron.
- It does not implement inference, rendering, ASR, or model lifecycle in DirectX.

### Python Backend (FastAPI)
- Toolchain: Python 3.12 and uv 0.11.28 with committed `uv.lock`
- Run: `uv run --project studio/edmg-studio/python_backend --frozen --extra cpu --extra core --extra audio python -m edmg_studio_backend serve --host 127.0.0.1 --port 7863`
- `edmg_studio_backend/app.py` sets up routes + exception handlers
- `edmg_studio_backend/errors.py` defines user-facing error model
- Logging via `enhanced_deforum_music_generator/utils/logging_utils.py`

## Data flow
1. UI triggers an action (generate / render / process).
2. UI calls backend endpoint.
3. Backend validates input, runs the job, logs progress.
4. Backend returns `{ ok: true, ... }` or `{ ok: false, error: {...} }`.

## Native Windows preview data flow

```text
authenticated ResponseHeadersRead callback
                │
                ▼
Windows image decoder ──► owned CPU BGRA/RGBA frame
                                 │
                        capacity-one mailbox
                                 │
                                 ▼
dedicated renderer worker ──► reusable D3D11 upload texture
                                 │
                                 ▼
       D2D aspect-fit draw over DXGI composition swap chain
                                 │
                                 ▼
                  WinUI 3 SwapChainPanel / VSync Present
```

- The composition swap chain has two `B8G8R8A8_UNorm` flip-model buffers and no depth buffer.
  It relies on DXGI's default per-swap-chain maximum frame latency of one; explicitly setting that
  value requires a frame-latency waitable-object swap-chain flag that this renderer does not use.
- Hardware adapters are enumerated by high-performance preference; software adapters are skipped.
  WARP is a degraded fallback. Diagnostics retain the adapter description and exact DXGI LUID for
  future CUDA-device matching.
- Decoded frame dimensions, checked byte sizes, explicit pixel format, stride, row padding, and
  top-down/bottom-up orientation are validated before upload. Decoded memory is bounded to 512 MiB.
- The renderer preserves source aspect ratio, centers the image with letterboxing, and sizes the
  swap chain in physical pixels using `RasterizationScale`.
- Decode, conversion, upload, draw, resize, and Present work stays off the UI thread. Only panel
  attachment/detachment and UI state cross the dispatcher.
- Stale frames are disposed by a capacity-one mailbox. At most one latest CPU frame is retained to
  redraw after bounded D3D11/DXGI/D2D device-loss recovery.
- Shutdown cancels acquisition, stops accepting frames, completes the mailbox, detaches the swap
  chain on the UI thread, waits for the renderer worker, releases COM resources, then disposes the
  backend supervisor and HTTP client.
- Today this is a CPU image-transfer path. `IFrameUploader` is the stable boundary for future
  CUDA-D3D11 shared-texture interop; CUDA inference and backend semantics remain unchanged.
- Images use Windows decoding with orientation and sRGB handling. Video preview is deliberately
  unsupported until a pinned, packaged, and qualified decoder is available.

## Conventions
### API envelope
- Success: `{ "ok": true, "data": ... }` or `{ "ok": true, ... }`
- Failure: `{ "ok": false, "error": { "message": "...", "hint": "...", "code": "..." } }`

### Errors
- Prefer raising `UserFacingError(message, hint, code, status_code)`
- Unknown exceptions map to `{ ok:false, error:{ code:"INTERNAL" } }`

### Logging
- Use the project logger helper to keep formatting consistent
- Avoid printing secrets/tokens/API keys

## Testing
- Check the backend lock before synchronization: `uv lock --project studio/edmg-studio/python_backend --check`.
- Combined Python scope from the repo root: `uv run --project studio/edmg-studio/python_backend --frozen --extra cpu --extra core --extra audio --group test python scripts/run_pytest_scopes.py`.
- CI, cloud bootstraps, and release builds consume the same frozen project; see
  [`PYTHON_TOOLCHAIN.md`](PYTHON_TOOLCHAIN.md).
- Node/TS: Vitest + jsdom smoke tests under `studio/edmg-studio/src/test`
