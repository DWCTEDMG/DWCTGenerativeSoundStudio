# Hybrid WSL2 execution plane

EDMG Studio keeps one authoritative backend and makes Linux an optional worker environment. WinUI and Electron always connect to one backend URL and observe the same projects, jobs, attempts, cancellation, and published outputs.

## Supported profiles

| Profile | Backend | Workers | Use |
| --- | --- | --- | --- |
| Standard | Windows | Windows-native; WSL disabled | Default packaged experience |
| Hybrid GPU | Windows | Windows plus managed WSL2 | Recommended AI workstation profile |
| External Linux | Linux server/workstation | Server-owned workers | Render nodes, studios, and cloud systems |

The Windows backend owns project state, settings, revisions, authentication, job state, cancellation, VRAM scheduling, validation, and publication. A WSL worker receives an immutable, attempt-scoped manifest. It writes only inside its staging directory. The backend admits only contained, hash-matched artifacts for the active attempt.

## Storage

- Keep authoritative projects and final outputs on Windows-owned storage.
- Keep large Linux models and caches in the WSL ext4 filesystem.
- Use `.job-staging/<job>/attempt-N` as the only worker exchange boundary.
- Do not let a worker mutate `project.json`, the jobs database, or published output folders directly.

## Read-only diagnostics

```powershell
wsl --status
wsl --list --verbose
nvidia-smi --query-gpu=index,name,uuid,pci.bus_id,memory.total --format=csv,noheader,nounits
wsl --distribution <Distro> --exec nvidia-smi --query-gpu=index,name,uuid,pci.bus_id,memory.total --format=csv,noheader,nounits
curl.exe http://127.0.0.1:7863/health
curl.exe http://127.0.0.1:7863/v1/execution/profile
curl.exe http://127.0.0.1:7863/v1/execution/inventory
```

Use the authenticated `POST /v1/execution/wsl/probe` action from Settings or Models to perform the bounded worker probe. It does not download models, synchronize dependencies, or run inference. A successful probe proves launchability, not generation or final-output qualification.

Readiness is deliberately layered: WSL installed, distribution running, worker environment present, GPU visible, model installed, worker launchable, generation started, artifact validated, and runtime qualified. Do not collapse these into a single “ready” flag.

## Recovery

- **Stopped WSL or missing distro:** start or install it outside Studio, select the correct distro, then re-probe. Standard remains usable.
- **Invalid Linux model path:** correct the path in Models; do not validate it as a Windows path.
- **Ambiguous GPU mapping:** compare UUID first and PCI bus identity second. Never copy Windows numeric indices into WSL configuration.
- **Stale lease:** confirm no worker owns the GPU. OS advisory locks recover after process exit; stale JSON is diagnostic only.
- **Worker timeout or WSL shutdown:** retry the job. The retry creates a new attempt and resolves live capability again.
- **Late obsolete result:** retain it only for diagnostics; active-attempt guards prevent admission or publication.
- **Disk pressure:** remove disposable expired attempt staging and worker caches, never authoritative projects or receipts needed for qualification.

## Security and privacy

Worker transport is local and argument-based; no shell command construction is used. Backend mutation routes use the configured bearer authentication. Manifests must not contain secrets. Status output redacts private model paths and environment variables. External Linux mode is a separate backend connection, not a child worker masquerading as local execution.

## Migration

Existing users require no change: an absent profile resolves to Standard. Existing Hunyuan WSL configuration is consumed by Hybrid GPU without moving projects. Disabling Hybrid GPU stops new WSL dispatches but does not delete Linux models, caches, logs, or settings.
