# Linux Packaging Notes

EDMG Studio already ships Linux-aware runtime branches in the Electron shell, Setup Wizard, desktop artifact helpers, and packaged smoke validation. The Linux packaged target is the Electron `AppImage`.

## Build on a Linux host

```bash
cd studio/edmg-studio
corepack enable
pnpm install
pnpm run validate:release:linux
```

That flow:

- runs the frontend typecheck and UI tests
- stages the desktop app bundle
- validates the Electron bridge and packaged smoke path
- builds the Linux `AppImage`

If you only need the artifact build:

```bash
cd studio/edmg-studio
pnpm run dist:linux
```

## Runtime expectations

- FFmpeg can come from the packaged bundle or `EDMG_FFMPEG_PATH`
- Ollama is expected to be installed system-wide or provided via `EDMG_OLLAMA_PATH`
- ComfyUI is optional and should run as a separate Linux service when used
- the Windows-only managed 7-Zip and ComfyUI Portable installers do not apply on Linux

## First-run notes

1. Mark the AppImage executable if needed: `chmod +x EDMG-Studio*.AppImage`
2. Launch the app.
3. Open `Setup`.
4. Choose a `Studio Home` on the storage volume you want for models, cache, logs, and external tools.

## Validation scope

`validate:release:linux` intentionally skips the Windows-only packaged customer-flow, upgrade-proof, and zero-state managed-installer proofs. Those remain covered by the Windows release path.
