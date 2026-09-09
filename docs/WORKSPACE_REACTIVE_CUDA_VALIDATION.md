# Workspace / Reactive Lab CUDA validation

The native reactive contracts accept omitted or explicitly null custom settings,
mapping lists, and saved preset collections. Missing values receive the existing
preset defaults. Supplied values, extension fields, keyframe timing, and locks are
preserved. Normalization happens in the Core models used by Reactive Lab.

## Preserve the selected runtime during regression checks

From the repository root, run:

```powershell
uv run --project studio/edmg-studio/python_backend --frozen --no-sync --extra cuda --extra core --extra audio --group test python scripts/run_pytest_scopes.py --accelerator-profile cuda
```

The scope runner passes the chosen profile to both its frozen sync and its test
subprocesses. `--accelerator-profile` overrides `EDMG_BACKEND_ACCELERATOR_PROFILE`.
If neither is specified, the runner retains its CPU default for ordinary CI.
Unknown profiles fail before any environment changes. The sync uses `--inexact`
to retain already installed ASR and model capability packages.

Passing `--extra cuda` only to the outer `uv run` does not select a profile for
the script: use the script flag or the environment variable as shown above.

Run native regression checks and the packaged Release build from
`studio/edmg-studio-winui`:

```powershell
dotnet test tests/EdmgStudio.Core.Tests/EdmgStudio.Core.Tests.csproj -p:Platform=x64 -p:Configuration=Release
dotnet build EdmgStudio.WinUI.csproj -p:Platform=x64 -p:Configuration=Release
```

From `studio/edmg-studio`, run `pnpm run test:ui --maxWorkers=1`,
`pnpm run lint`, and `pnpm run typecheck`. Limiting workers avoids excessive
process startup on large Windows hosts.

## Distinguish runtime readiness from workflow completion

Before a GPU validation run, verify the actual Python environment with a CUDA
tensor operation, then check the selected backend's `/v1/hardware` response.
The driver being installed, a CUDA wheel being present, or TensorRT importing
does not establish that a particular transcription or render job ran on GPU.

Launch through the project's packaged launch profile or its bundled `winapp`
CLI, preserving package identity. Diagnostic launch arguments can explicitly
select `--accelerator-profile cuda` and the validation backend address. A healthy
backend and a responsive native window establish startup only.

For the requested end-to-end qualification, use `3 Find a Cielin'.wav` in an
isolated project and record:

1. The exact input path, analysis completion, and actual inference device.
2. Generated scenes, cues, and reactive keyframes in the shared Workspace draft.
3. The same draft visible in Overview/Director and Reactive Lab without a load error.
4. Review/apply and save/reopen preserving accepted refinements.
5. Manual and locked edits surviving regeneration and application.
6. A stale draft rejected without changing the live timeline.

The backend Workspace tests substitute audio analysis/transcription while
exercising real routes, persistence, revisions, and application. Their success
does not replace the requested WAV test or native interaction verification.
Likewise, a CUDA runtime probe does not qualify a TensorRT render or certify
that ASR avoided its configured CPU fallback. Inspect the individual job result.
