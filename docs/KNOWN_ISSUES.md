# EDMG Studio 1.2.0 Candidate: Known Issues and Release Blockers

Last reviewed: 2026-08-06

This page describes the current source candidate. It does not turn an older build directory or the
installed 1.1.0 application into a 1.2.0 release artifact. Public promotion remains blocked until
every item in the first section has reproducible evidence attached to the fresh candidate.

## Must be completed before public release

1. **Build fresh artifacts.** Review and commit the canonical dependency inputs, then build a new
   signed DirectML candidate from the clean 1.2.0 source. Treat any pre-existing
   `release/staged-app`, `dist/win-unpacked`, backend bundle, installed application, or
   `release/evidence` content as historical until the current gate regenerates it and proves its
   lock, source, profile, binary, and artifact hashes. If CPU or CUDA are public SKUs, build, sign,
   inspect, and qualify each one separately; the current
   `validate:release:production` command exercises the default DirectML lane only. Do not rename or
   reuse an older payload or its evidence.
2. **Sign and timestamp every shipped executable.** Do not infer signature status from an older
   installation or build directory. Configure `EDMG_CODE_SIGN_CERT` on the authorized signing host
   and require the current `pnpm run validate:release:production` result plus independent signature
   evidence for the desktop, backend/helper executables, installer, and uninstaller.
3. **Run clean-machine acceptance.** Install the signed candidate on a supported Windows machine
   without repository tools, Python, Node.js, uv, or globally installed helper applications. Prove
   first launch, setup, project creation, analysis, planning, proxy rendering, export, restart, and
   uninstall data retention.
4. **Run the real 1.1.0 to 1.2.0 upgrade.** Use the existing installation only through the read-only
   `--installed-app-dir` baseline interface. The candidate must be a separate executable with a
   strictly newer file version. Preserve baseline hashes before and after the proof.
5. **Record named-hardware render evidence.** Exercise the supported CUDA/TensorRT and fallback
   paths with model/version, GPU, driver, VRAM, quality, timing, cancellation, and recovery data.
6. **Complete release governance.** Attach checksums, CycloneDX SBOM, signature verification,
   known-issues acceptance, rollback instructions, and protected-branch/CI evidence to the exact
   candidate being promoted.

## Known technical limitations

- **Packaged Git identity:** the backend manifest fingerprints the exact backend source set, binary,
  and frozen lock, and the Settings UI exposes those hashes. It does not yet record an archive-safe
  Git commit and dirty-worktree marker.
- **CUDA package size:** CUDA/TensorRT packaging includes a substantial builder/compiler payload.
  Measure the fresh candidate rather than carrying forward an older installation size. Splitting
  builder resources into an optional developer add-on may save space, but no files should be
  removed until packaged TensorRT loading passes on the supported GPU matrix.
- **Legacy TensorRT model layout:** Models now offers an explicit verify-and-copy workflow for the
  four recognized root-level engines under the active Studio Home. It preserves the originals,
  SHA-256 verifies the copied bytes, and publishes a versioned canonical bundle atomically. That
  engine-only copy remains intentionally not installed and not renderer-ready until its complete
  manifest-listed ONNX inventory, compiled integer profile, and matching SD 1.5 Hub model ID plus
  immutable revision are explicitly verified. Execution paths are resolved server-side from stable
  model IDs; clients never submit absolute model paths. Arbitrary external folders remain explicit
  compatibility inputs and are not auto-discovered. They pass the same fail-closed contract and
  cannot outrank a valid canonical bundle merely because an environment path exists.
- **Legacy TensorRT Deforum semantics:** the current Studio UI no longer calls the old
  `/render/tensorrt-deforum` endpoint, and the simulated renderer behind it has been removed. The
  endpoint and old `tensorrt_deforum` jobs remain read-compatible for older clients and persisted
  queues, but now execute the canonical TensorRT plan/keyframe video path and explicitly report
  `legacy_deforum_schedule_applied: false`. Zoom, angle, translation, and strength schedules from
  that old path are not translated in 1.2.0; use the canonical Render plan and timeline controls.
- **Triton prototype:** `D:\triton-setup` is an external research prototype, not an EDMG Studio
  release dependency or provider. Studio must remain fully functional without it. See
  [TRITON_PROVIDER_READINESS.md](TRITON_PROVIDER_READINESS.md).
- **D: is full:** the current workstation reports zero free bytes on `D:`. Do not build, cache,
  migrate, or run a write-producing model service there. `D:\triton-setup` and
  `D:\my_tensorrt_models` remain read-only until storage is deliberately reclaimed or moved.
- **Large composition modules:** the backend application module and several Studio pages remain
  oversized. Continue extracting tested domain services and UI panels, but preserve the canonical
  renderer, persisted project formats, and compatibility routes during that work.
- **Python lint baseline:** focused changed-file Ruff checks and the full backend lint baseline are
  different signals. The required import-after-CUDA-bootstrap pattern in `app.py` and `cli.py` has
  a narrow documented Ruff exception; remaining import, typing, exception-chaining, and
  compatibility cleanup must be measured from the current tree. Full Ruff is not yet a release
  gate and must not be represented as green or as a security scan.
- **Accessibility and visual-safety proof:** keyboard coverage, scaling, reduced motion, contrast,
  and flash-safety acceptance remain incomplete even where individual controls already support
  them.

## Deferred major upgrades

The 1.2.0 candidate takes compatible updates within the current dependency majors. The following
live-registry upgrades are deliberately deferred because each crosses a framework, runtime, or
tooling compatibility boundary and needs its own isolated change set plus packaged proof:

- React and React DOM 18 to 19, together with their type packages and React Compiler behavior;
- Electron 41 to 43, including preload/IPC, Windows packaging, signing, and clean-machine smoke;
- Tailwind CSS 3 to 4 and the corresponding stylesheet/configuration migration;
- TypeScript 5 to 7 and Node type definitions 22 to 26;
- Vite React plugin 5 to 6, jsdom 29 to 30, and Lucide React 0.x to 1.x.

The frozen Python lock is intentionally held at the selected 1.2.0 candidate dependency stack;
that selection still requires fresh packaged proof. In particular, NumPy 2, Transformers 5,
OpenCV 5, Hugging Face Hub 1.x, and the coordinated
Torch/TorchVision/Torch-TensorRT 2.13 plus TensorRT 11 transition require model, PyInstaller,
DirectML/CUDA, and named-GPU evidence. FastAPI/Uvicorn and optional-provider refreshes should land
separately so contract or packaging regressions can be isolated.

Do not combine those migrations with the signed 1.2.0 promotion. Land them independently, require
the full frontend/runtime/package gates for each, and preserve a rollback point.

## Operator rules for this candidate

- Do not point `EDMG_STUDIO_PACKAGED_APP` at the installed 1.1.0 baseline.
- Do not write release evidence into the installed application directory.
- Do not treat bundled TensorRT libraries as proof that a compatible model engine is installed.
- Do not enable Triton discovery or routing for this release.
- Do not publish an unsigned artifact produced by the signing-optional local candidate gate.
- Do not claim a release from source-test success alone; use the ordered gates in
  [RELEASE.md](../RELEASE.md).
