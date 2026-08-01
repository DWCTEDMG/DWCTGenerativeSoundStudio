# Studio Security and Release Audit — 2026-07-31

## Executive summary

The local Studio source is materially closer to release: the frozen CUDA runtime is healthy, the complete backend and frontend test suites pass, and GitHub CodeQL has no open security-severity findings after evidence-based triage. One real hosted-render path-confinement defect and one production call-signature defect were fixed together and covered by regression tests.

This revision is not yet a signed public release. CI, CodeQL, and Dependabot must scan the committed revision, and a trusted Authenticode signature plus clean-machine installer smoke test remain release gates.

## Findings

### SEC-001 — Hosted assembly trusted a legacy absolute audio path (fixed locally)

- Severity: High
- Affected code: `studio/edmg-studio/python_backend/edmg_studio_backend/app.py:565`, `:8593`, and `:8831`; Firefly and ImagineArt assembly routes.
- Impact: persisted project metadata could select an existing absolute local file and pass it to FFmpeg as an audio input. This was not shell command injection because FFmpeg is invoked with a shell-free argument list, but it violated project filesystem confinement and could expose local file contents in a rendered artifact.
- Fix: both routes now resolve audio through `_project_audio_path()`, which accepts only the current project's `assets/audio` filename and enforces containment with `safe_join()`. A fixed project-local `audio.wav` remains the compatibility fallback.
- Verification: `studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_imagineart_platform.py:230` plants an external file in legacy metadata and fails if either hosted route reaches the mux function with it. The positive test at `:153` also proves that a normal `assets/audio` upload and the project-local legacy fallback are still muxed by both routes.

### REL-001 — Hosted slideshow assembly used the wrong keyword (fixed locally)

- Severity: High reliability defect
- Affected code: `studio/edmg-studio/python_backend/edmg_studio_backend/app.py:8641` and `:8874`.
- Impact: production called `assemble_slideshow(..., out_path=...)`, but the service contract is `out_mp4`. A permissive test mock hid the resulting production `TypeError`.
- Fix: both calls now use `out_mp4`; the mock matches the production signature. Audio mux failures are logged with tracebacks instead of being silently discarded.

### REL-002 — Windows release signing hook was a no-op (fixed; identity still required)

- Impact: the previous `sign_release.ps1` printed `Would sign` and exited successfully without changing any artifact, so a build could appear release-ready while every executable remained unsigned.
- Fix: Windows packaging now supports a local PFX/P12 or certificate-store SHA1 thumbprint, maps credentials into electron-builder native signing, enables `forceCodeSigning`, signs owned backend/helper executables before packing, signs the custom Inno setup after compilation, and verifies shipped executables with both `Get-AuthenticodeSignature` and Windows SDK SignTool.
- Evidence: each pass records `release/evidence/windows-signatures.json`, and checksum evidence is generated after the final signature operation. `EDMG_REQUIRE_CODE_SIGNING=1` fails closed when credentials or a valid signature are absent.
- Current constraint: this workstation has SignTool but no trusted Code Signing certificate/private key or Azure Trusted Signing identity. The real installer can be built here, but it must remain explicitly unsigned until a release identity is supplied; a self-signed certificate is not acceptable public-release proof.

### SEC-002 — CodeQL path and command-injection findings (triaged)

- Result: zero open CodeQL findings with a security severity after triage.
- Command-injection alerts were false positives: FFmpeg and FFprobe use explicit argument arrays and the default `shell=False` behavior.
- Project path alerts were false positives where inputs pass through `ProjectStore`, `safe_join`, `_safe_project_path`, basename normalization, fixed filenames, or sanitized stems.
- The bind-all-interfaces alert was a false positive: the launcher performs a transient bindability probe and immediately closes the socket; it never listens or accepts connections.
- Important distinction: SEC-001 was retained as a genuine confinement finding and repaired even though the related CodeQL rule classified the sink as command injection.

### DEP-001 — Legacy Electron advisories (fixed locally; scan pending)

- Affected manifest: `desktop/electron/package.json`.
- GitHub inventory: 16 alerts in the legacy `desktop/electron` manifest: 4 high, 9 medium, and 3 low.
- Fix: Electron was upgraded from `^29.4.6` to `^41.10.3`, matching the canonical Studio major and exceeding every reported patched floor (the highest is 41.1.0).
- Verification: the manifest parses and `electron@41.10.3` resolves from the npm registry.
- Remaining gate: GitHub will continue showing these alerts until the manifest change reaches the default branch and Dependabot rescans it.

### DEP-002 — Helper pytest advisory (fixed locally; scan pending)

- Alert: #103 / `GHSA-6w46-j5rx-g56g` (medium).
- Fix: the isolated HF Bucket helper now requires pytest `>=9.0.3,<10`; its frozen lock resolves pytest 9.1.1.
- Verification: a frozen helper sync succeeds and all 5 helper tests pass.

### DEP-003 — Compatibility-constrained advisories (formally accepted)

Four residual alerts are accepted as `tolerable_risk` with narrow exposure and upgrade constraints recorded in GitHub:

- #58 / `GHSA-3wqj-33cg-xc48` and #59 / `GHSA-55v6-g8pm-pw4c` (`rembg`, medium): Studio imports only the in-process `rembg.remove()` function for an in-memory PIL image. It never launches `rembg s`, exposes the vulnerable HTTP model-path/URL surface, or uses its CORS server. The patched rembg line requires NumPy 2.3+, while Studio core pins NumPy below 2; remediation requires an isolated helper or tested NumPy 2 migration.
- #64 / `GHSA-rrmf-rvhw-rf47` (`torch`, low): no tracked code calls `torch.jit.script`, and Studio does not compile untrusted Python. The patched Torch 2.13 line requires a coordinated Torch/TorchVision/TorchAudio/TensorRT accelerator-stack upgrade; Studio's tested profiles are frozen at 2.11.
- #83 / `GHSA-h35f-9h28-mq5c` (`setuptools`, medium): the advisory affects macOS sdist creation involving Unicode-colliding `MANIFEST.in` exclusions. This repository has no backend `MANIFEST.in`, and the release path is Windows PyInstaller/Electron rather than sdist publication. The patched setuptools 83 line conflicts with the current Torch 2.11 build constraint (`setuptools<82`).

The original 13 medium and 4 low inventory is therefore fully dispositioned: 12 Electron alerts and the pytest alert are fixed in manifests/locks, while the 3 medium and 1 low items above are formally accepted. No Transformers alert is part of this inventory.

## Validation evidence

- Backend: 339 passed; 6 deprecation warnings; 0 failures.
- Hosted assembly focus: 11 passed; changed test file passes Ruff.
- Frontend: 103 passed across 34 files; TypeScript and ESLint pass.
- Production web build: Vite build passes.
- Desktop release gate: `pnpm run validate:desktop` passes, including release-toolchain and runtime tests, frozen DirectML backend bundling, staged desktop metadata, Electron bridge validation, live desktop integration, and packaged-backend smoke testing.
- Runtime: frozen `cuda + core + audio + asr + internal-video + aws` dependency profile synchronizes cleanly; backend readiness reports Ready; an actual CUDA tensor operation succeeds on the NVIDIA RTX 4050 Laptop GPU.
- GitHub: no open critical, high, or medium CodeQL security findings after evidence-backed review.

## Remaining release gates

1. Review and commit only the intended source changes; preserve the pre-existing untracked root `uv.lock`.
2. Run CI and a fresh CodeQL scan on the committed changes; confirm the local fix is represented in the scanned revision.
3. Confirm Dependabot closes all 16 Electron alerts and the pytest alert after the manifests reach the default branch; confirm the four constrained alerts remain recorded as accepted rather than open.
4. Produce the platform installer, sign it, and perform install/launch/create-upload-analyze-plan-render smoke testing on a clean Windows GPU machine.
5. Verify upgrade and rollback behavior, installer provenance, checksums, and release notes before publication.
