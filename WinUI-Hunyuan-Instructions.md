# WinUI CTD and HunyuanVideo-1.5 Continuation Instructions

## Objective

Continue enabling HunyuanVideo-1.5 for EDMG Studio through WSL2, but keep it unavailable for normal rendering until the complete Linux runtime, all required assets, and a real inference smoke test pass. Preserve the WinUI crash fix and expose all runtime controls through the Studio Models UI.

## Repository state

- Branch: `codex/Unified`
- Last implementation commit: `9070bd4` (`Enable Hunyuan runtime setup in Studio`)
- Commit is pushed to `origin/codex/Unified`.
- Do not commit ChatLog files.
- `studio/edmg-studio-winui/ChatLog3.md` and `ChatLog4.md` were intentionally left untracked.
- This instruction file is a new repository-root file and is not committed yet.

## Completed WinUI CTD fix

The repeatable Timeline crash-to-desktop was caused by WinUI assigning interdependent `Slider` properties in an unsafe generated-XAML order. `ZoomSlider` intended to use a range of 12-360 with an initial value of 80, but WinUI could assign `Minimum` or `Value` while the control still had its default maximum of 1.

The fix is in:

- `studio/edmg-studio-winui/Pages/TimelinePage.xaml`
- `studio/edmg-studio-winui/Pages/TimelinePage.xaml.cs`

The range/value attributes were removed from XAML. Immediately after `InitializeComponent()`, code now assigns `Maximum`, then `Minimum`, then `Value` in a valid order. Debug and Release x64 builds succeeded, and navigating to Timeline no longer crashes the process.

Do not move these interdependent values back into XAML.

## Completed Hunyuan Studio integration

Commit `9070bd4` added:

- Durable, allowlisted Hunyuan runtime configuration in `launcher_env.json`.
- Atomic configuration writes that preserve unrelated launcher settings.
- Backend endpoints:
  - `GET /v1/runtimes/hunyuan-video15/config`
  - `POST /v1/runtimes/hunyuan-video15/config`
  - `POST /v1/runtimes/hunyuan-video15/probe`
- Core client methods for those endpoints.
- A WinUI Models-page card for:
  - WSL2 or external Linux mode
  - WSL distribution
  - Linux Python executable
  - official source checkout
  - timeout
  - Qwen/LLM assets
  - ByT5 assets
  - Glyph-SDXL-v2 assets
  - FLUX/SigLIP vision assets
  - saving settings and probing readiness
- Backend tests for persistence, allowlisting, validation, and preservation of unrelated settings.

Targeted backend tests passed, backend lint passed, and Debug/Release x64 WinUI builds passed.

## Runtime gating that must remain

The catalogue entry is `hf_hunyuan_video15_internal`.

It must remain fail-closed until real qualification:

- `installable=False`
- tag includes `unverified`
- `render_modes=[]`

Do not add `internal_video_model` to its render modes merely because WSL, Python, imports, or CUDA work. Only enable normal renderer selection after the complete package and companion assets are installed and a real Level-5 inference smoke test produces valid video and writes a matching runtime validation receipt.

## Current machine and WSL state

WSL was repaired and upgraded successfully:

- WSL version: `2.7.13.0`
- Kernel: `6.18.33.2-2`
- Ubuntu was converted from WSL1 to WSL2.
- Distribution: `Ubuntu`
- Linux user/home: `gulle`, `/home/gulle`
- WSL filesystem has approximately 955 GiB free.
- Host memory visible to WSL: approximately 58 GiB plus 15 GiB swap.

GPU passthrough works in WSL2:

- 2 x NVIDIA RTX A6000
- Approximately 49,140 MiB VRAM each
- NVIDIA driver reported as 597.06
- `nvidia-smi` is available at `/usr/lib/wsl/lib/nvidia-smi`.

System `/usr/bin/python3` is Python 3.14.4 and must not be used for this runtime.

## Installed isolated Hunyuan environment

`uv` was installed in WSL at the user level, and Python 3.12.14 was installed with it.

The official source repository was cloned to:

```text
/home/gulle/edmg/HunyuanVideo-1.5
```

Current source commit at the time of setup:

```text
60783e704160023913bee78f0b47036d393d4dfa
```

The Hugging Face model snapshot remains pinned independently in Studio to:

```text
Repository: tencent/HunyuanVideo-1.5
Revision: 9b49404b3f5df2a8f0b31df27a0c7ab872e7b038
```

The isolated environment is:

```text
/home/gulle/edmg/HunyuanVideo-1.5/.venv/bin/python
```

It was created with Python 3.12 and populated from the official `requirements.txt`. Important installed versions include:

- `torch==2.6.0+cu124`
- `torchaudio==2.6.0`
- `torchvision==0.21.0`
- `diffusers==0.35.0`
- `transformers==4.57.1`
- `peft==0.17.0`
- `einops==0.8.0`
- `imageio==2.37.0`
- `huggingface-hub==0.34.0`
- `modelscope==1.40.0`

Validated from this environment:

- `torch`, `hyvideo`, `imageio`, and `einops` import successfully.
- `HunyuanVideo_1_5_Pipeline` imports successfully.
- `torch.cuda.is_available()` is `True`.
- PyTorch sees both RTX A6000 GPUs.
- The official pipeline exposes the `get_transformer_version` and `create_pipeline` APIs expected by Studio's worker.

Optional acceleration packages such as Flash Attention, Flex-Block-Attention, SageAttention, and SGL-Kernel have not been installed. They are not prerequisites for the initial correctness qualification.

## Required companion asset layout

Use this base directory:

```text
/home/gulle/edmg/HunyuanVideo-1.5/ckpts
```

Configure Studio with these exact Linux paths:

```text
Runner: wsl
WSL distribution: Ubuntu
Linux Python: /home/gulle/edmg/HunyuanVideo-1.5/.venv/bin/python
Hunyuan checkout: /home/gulle/edmg/HunyuanVideo-1.5
Qwen/LLM assets: /home/gulle/edmg/HunyuanVideo-1.5/ckpts/text_encoder/llm
ByT5 assets: /home/gulle/edmg/HunyuanVideo-1.5/ckpts/text_encoder/byt5-small
Glyph assets: /home/gulle/edmg/HunyuanVideo-1.5/ckpts/text_encoder/Glyph-SDXL-v2
Vision assets: /home/gulle/edmg/HunyuanVideo-1.5/ckpts/vision_encoder/siglip
Timeout: 3600 seconds initially
```

Studio's probe requires at least:

- Qwen path: `config.json`
- ByT5 path: `config.json`
- Glyph path:
  - `assets/color_idx.json`
  - `assets/multilingual_10-lang_idx.json`
  - `checkpoints/byt5_model.pt`
- Vision path:
  - `image_encoder/config.json`
  - `feature_extractor/preprocessor_config.json`

## Authentication blocker

The Windows Hugging Face token stored at `%USERPROFILE%\.cache\huggingface\token` is expired. It returned HTTP 401. A temporary copy was removed from WSL after validation failed.

Do not print, commit, or store a replacement token in `launcher_env.json` or source control.

The public repositories are reachable without authentication:

- `tencent/HunyuanVideo-1.5` at the pinned revision; full repository is approximately 346.24 GiB, so download only the selective files defined by Studio's package manifest.
- `Qwen/Qwen2.5-VL-7B-Instruct`; approximately 15.46 GiB.
- `google/byt5-small`; approximately 3.35 GiB.

The required vision model is gated:

```text
black-forest-labs/FLUX.1-Redux-dev
```

The user must accept its Hugging Face terms and perform a fresh WSL login using an authorized token. Treat missing authorization as an explicit readiness blocker; do not bypass it or substitute unverified assets.

Recommended interactive command, run by the user so the token is not exposed in logs:

```bash
wsl.exe --distribution Ubuntu -- /home/gulle/edmg/HunyuanVideo-1.5/.venv/bin/hf auth login
```

## Next execution steps

1. Persist the paths above through the Studio Models UI, or call the already implemented backend configuration endpoint. Prefer the UI.
2. Run the Studio Hunyuan probe. It should confirm Python/CUDA/source imports and report only missing asset files until downloads complete.
3. Verify fresh Hugging Face authentication and gated FLUX.1-Redux-dev access.
4. Download only the selective Tencent files from `engine_package_manifests.json`, not the complete 346 GiB repository.
5. Download Qwen2.5-VL-7B-Instruct to `ckpts/text_encoder/llm`.
6. Download `google/byt5-small` to `ckpts/text_encoder/byt5-small`.
7. Download Glyph-SDXL-v2 through ModelScope to `ckpts/text_encoder/Glyph-SDXL-v2`.
8. Download authorized FLUX.1-Redux-dev content to `ckpts/vision_encoder/siglip`.
9. Re-run the non-inference Studio probe and resolve every reported issue.
10. Install/validate the selective managed Hunyuan package through Studio.
11. Run the real runtime smoke test from the Models UI. Confirm valid video output and a matching runtime-validation receipt.
12. Only after successful real inference, update renderer availability and automatic fallback behavior projectwide.
13. Rebuild/test backend, Core, and WinUI scopes.
14. Commit and push intended changes, excluding all ChatLog files and machine-local `launcher_env.json`.

## Useful validation commands

Verify WSL and GPU:

```powershell
wsl.exe --list --verbose
wsl.exe --distribution Ubuntu -- nvidia-smi
```

Verify the isolated environment:

```powershell
wsl.exe --distribution Ubuntu -- bash -lc 'cd "$HOME/edmg/HunyuanVideo-1.5" && .venv/bin/python -c "import torch,hyvideo,imageio,einops; print(torch.__version__, torch.cuda.is_available(), torch.cuda.device_count())"'
```

Build WinUI:

```powershell
dotnet build studio\edmg-studio-winui\EdmgStudio.WinUI.csproj -c Debug -p:Platform=x64
dotnet build studio\edmg-studio-winui\EdmgStudio.WinUI.csproj -c Release -p:Platform=x64
```

Run targeted backend tests:

```powershell
Set-Location studio\edmg-studio\python_backend
uv run --frozen --extra cpu --extra core --extra audio --group test python -m pytest edmg_studio_backend\tests\test_internal_video_models.py -q
```

## Safety and correctness constraints

- Never commit tokens, credentials, `launcher_env.json`, downloaded model assets, or ChatLog files.
- Do not claim Hunyuan is operational until a real inference smoke test succeeds.
- Do not use the WSL system Python 3.14 runtime.
- Do not download the full Tencent model repository when the selective manifest is sufficient.
- Do not silently ignore probe or download errors.
- Preserve unrelated machine-local launcher settings when updating Hunyuan configuration.
- Keep native Windows execution unsupported; use WSL2 or a qualified external Linux host.
