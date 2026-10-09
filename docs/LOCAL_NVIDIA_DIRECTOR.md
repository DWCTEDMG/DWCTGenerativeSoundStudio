# Local NVIDIA Director in WSL

The native Studio Settings page can select **Use local NVIDIA models in WSL**.
This selects local Nemotron BF16 and Cosmos connections. Save AI Director settings
after selecting them. Generated direction still passes through review and apply.
The Hugging Face Spaces MCP connections remain available independently.

The runtime stores the pinned model snapshots in
`~/edmg/models/director-nvidia` inside WSL and uses a separate Python environment,
`~/.venvs/studio-nvidia`. It does not synchronize the Windows rendering environment.
Nemotron uses CUDA devices 1 and 2, requiring 40 GiB free on each; Cosmos uses device 0,
requiring 24 GiB free. These defaults target the three-RTX-A6000 workstation.
CPU and disk model offload are rejected. Requests are serialized, and each model
is released after its request so video rendering can use the GPUs afterward.

From WSL, run the setup script with an existing Hugging Face token file for gated
Cosmos access. Do not put the token itself on the command line:

```bash
bash /mnt/c/path/to/Studio/scripts/setup_local_nvidia_director.sh \
  --token-file /mnt/c/Users/your-user/.cache/huggingface/token
```

From PowerShell in the Studio checkout, start the service:

```powershell
.\scripts\Start-LocalNvidiaDirector.ps1 -Distribution Ubuntu
```

The launcher uses the WSL user's home, writes logs under
`%LOCALAPPDATA%\EDMGStudio\logs`, and refuses to reuse an unrelated service.
The loopback-only API serves `/nemotron/v1` and `/cosmos/v1` on port 8011.
`/health` reports downloaded snapshots separately from service availability;
it does not prove inference success. Completed requests include CUDA placement,
model identity, token count and elapsed time in `studio_receipt`.

The first Nemotron load can download published CUDA kernel dependencies.
Its pinned RADIO Python code is downloaded during setup. Model weights and
generation remain local. The Studio connection currently sends analyzed audio
evidence and scene direction; it does not claim raw-audio-native inference.
Cosmos can accept images and videos through its local API, while the current
Director specialist adapter sends structured context.

Workstation verification on 2026-10-09: Nemotron generated text with all model
parameters on CUDA devices 1 and 2; Cosmos read text from an image on CUDA 0.
Two consecutive Cosmos requests also passed after the release fix, with GPU 0
returning to approximately 2.5 GiB total usage after each request. Initial library
imports, weight loading and CUDA kernel compilation can take several minutes.
These checks establish local inference and memory release, not full-film quality.
The full Director request completed, but returned no scene edits; its success
must not be presented as a creative improvement to the existing draft.
