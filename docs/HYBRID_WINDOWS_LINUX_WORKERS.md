# Windows coordinator, Linux video workers, and WSL backup

Local WinUI connects to the Windows coordinator over the existing authenticated
private Tailscale endpoint. Windows retains the project database, job leases,
shot checkpoints, media assembly, and publication. This implementation adds
remote Linux execution to internal video frame generation for SVD, AnimateDiff,
LTX-2.5, and HunyuanVideo 1.5; each runtime still needs separate qualification.
It does not distribute Director, Whisper, TensorRT optimization, or every
backend operation. It does not combine GPU memory across machines.

## Configure in native Settings

Open **Hybrid Windows and Linux video workers** on Settings. Save the SSH host,
port, username, private key path on the coordinator, Linux Python executable,
`python_backend` source directory, and models root. The worker checkout must
match the coordinator's worker source; the bounded probe verifies its hash.

The coordinator private key created in this chat is at
`C:\Users\user\VastAI-SSH\vast_ai_ed25519`. Register its public key on Vast.ai.
Verify the instance SSH host key through a trusted channel and connect once
with OpenSSH using `-o UserKnownHostsFile=C:\Users\user\VastAI-SSH\known_hosts`.
Worker SSH/SCP requires strict host-key checking and never auto-accepts keys.

Install the matching backend source and appropriate model dependencies on the
Linux node. Model paths retain their relative layout below the coordinator's
models directory, e.g. `internal/video/hf_hunyuan_video15_internal`. Weights
stay on the worker; source images and generated frames transfer per attempt.
Bring-your-own-model paths outside the coordinator's model root remain local.

For Hunyuan, independently configure the Linux node's `EDMG_HUNYUAN15_REPO`,
model/companion paths, and GPU indices. The transport sets its runner to
`external` and its Python executable to the configured Linux Python. Do not
copy Windows paths into a remote Linux launcher configuration.

## WSL on this VM

Observed on 2026-10-11: Ubuntu WSL2 running, three RTX A6000 devices visible,
and the existing Hunyuan Python wrapper passed the worker CUDA probe. Suggested
settings for its existing Hunyuan model lane:

| Field | Value |
| --- | --- |
| Distribution | `Ubuntu` |
| Python | `/home/gulleman/edmg/bin/hunyuan-python` |
| Backend root | `/mnt/c/Users/user/source/repos/DWCTGenerativeSoundStudio/studio/edmg-studio/python_backend` |
| Models root | `/home/gulleman/edmg/models` |

This probe is not a new inference receipt. The existing Hunyuan environment
does not automatically qualify SVD/AnimateDiff/LTX. Use the native model
checkboxes to restrict the route to qualified engines; the initial default
supports all four adapters, so enable only when the chosen environments are ready.
The JSON API is `/v1/execution/hybrid` (GET/PUT); bounded node checks are
`POST /v1/execution/hybrid/probe`. Configuration persists in the coordinator's
data root at `config/hybrid-video.json`. No worker is enabled by default.

## Execution and failure behavior

An automatic video request probes the remote node first, then WSL. The probe
requires matching worker source, CUDA, and the requested model folders. It does
not load or qualify model weights. If neither node passes, the existing local
route is used only when local fallback is enabled. Explicit per-job Windows or
WSL selection bypasses remote routing in the isolated render process.

After launch, worker errors or network loss fail that attempt. They never
silently launch a duplicate on the backup. Use the existing job retry/checkpoint
workflow to recover unfinished shots. Cancellation is polled by the
coordinator, sent to the worker attempt, and kills its process group; if the
coordinator disappears, the worker's bounded timeout remains the upper limit.
Each worker serializes its own attempts with a node lock.

Outputs return as lossless PNG frames. The coordinator checks the exact frame
inventory, dimensions, count, and request hash before handing frames back to
the existing render assembly/publication path. Node identity and preflight
fallback observations are recorded under the shot workspace's `.hybrid-video`
attempt folder. Job-level execution metadata still describes the coordinator
route; consult the shot receipt for the actual video node.

Native Windows and WSL share the VM's physical GPUs. Keep a single coordinator
for these jobs; independent render processes started outside it are not covered
by its admission slot. WSL is execution backup, not backup for Windows project
storage or coordinator availability.

## Qualification still required

On the actual Vast.ai node: establish SSH trust, deploy this source, configure
models and credentials, probe, and obtain a real render/output receipt. Then
exercise WinUI upload/review/render/download from the user's local machine.
Perform controlled unavailable-node, cancellation, and retry checks before
relying on failover. Tailscale/network setup and full deployment are separate
from the source/build/test evidence in this change.
