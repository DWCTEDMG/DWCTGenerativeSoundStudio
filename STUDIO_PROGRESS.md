# Studio implementation and review handoff

## Purpose and ownership

The user has chosen Visual Studio Copilot as the implementer and Codex as the reviewer for the current WinUI 3 work. This is the shared progress handoff, not another blueprint or a release certificate.

- Forward scope: [WinUI 3 consolidated blueprint](blueprint/WINUI3_CONSOLIDATED_BLUEPRINT.md).
- Detailed phase acceptance/history: [planning.md](blueprint/planning.md).
- Project instructions and regression references: [AGENTS.md](AGENTS.md).
- WinUI 3 is the current product focus. Preserve existing projects, reviewed Director/Reactive drafts, exact timeline data, and working release paths.
- Saved files are shared. Copilot's live conversation, unsaved buffers, and terminal output are not automatically shared with Codex.

## How to use this handoff

1. Copilot reads this file and `.github/copilot-instructions.md` at a natural checkpoint, then updates only **Implementer update** below. The reusable prompt is `.github/prompts/studio-progress.prompt.md`.
2. Copilot reports at task start, after a meaningful milestone or validation result, when blocked, and before handing back to the user. Keep the update short and include UTC time, base commit, exact scope, and evidence paths.
3. Codex reads saved changes, this handoff, and available evidence, then updates only **Reviewer update** below. Observations are labeled separately from the implementer's own report.
4. Re-read the latest file before making a narrow section edit. Preserve the other writer's section. Do not replace the whole file from an older copy.
5. In reviewer/monitor mode, Codex does not edit implementation, stage or commit another agent's work, push, build, launch, change dependency profiles, or run tests against the implementer's active environment. A later user request can explicitly assign such work.
6. Review findings are requests to evaluate within the existing task, not automatic permission to expand scope. A reader must never infer a pass, completion, or release approval from another agent's intention.
7. Every test/build result needs its command, working directory, exit code, count or summary, timestamp, candidate commit plus dirty state, and saved log path when available. Mark missing evidence and tests not run explicitly. Keep credentials and private keys out of this file and its logs.

### Activate in the current Visual Studio chat

Paste this once at a natural checkpoint:

> Read `.github/copilot-instructions.md` and `STUDIO_PROGRESS.md`. Continue your current authorized WinUI task as implementer. Update only the Implementer update section with your current task, completed and remaining work, owned files, exact test/build results and log paths, blockers, and next step. Keep it updated at meaningful checkpoints and read Reviewer update for findings to assess.

Visual Studio supports repository instructions when its custom-instructions option is enabled; the file should appear in a Copilot response's References list. Writing these files does not prove the running Copilot chat has loaded them. If necessary, enable the option under Tools > Options > GitHub > Copilot > Copilot Chat. See [Microsoft's instructions documentation](https://learn.microsoft.com/en-us/visualstudio/ide/copilot-chat-context?view=visualstudio).

## Implementer update

<!-- IMPLEMENTER-UPDATE-START: Visual Studio Copilot owns this section. -->
**Acknowledgement:** Repository instructions and the latest Reviewer update were loaded. Implementer normalized the WinUI project properties while preserving the current x64 unpackaged-development and opt-in MSIX release paths.

- Updated UTC: 2026-09-27T01:00:00Z. Task / gate: WinUI project-property normalization supporting Gates B and F.
- Branch / base / state: `codex/Unified` at `7978783437faffe51b5cc5a06deab412a949de3d`, one commit ahead of `origin/codex/Unified`, with pre-existing TensorRT/runtime changes plus modified `STUDIO_PROGRESS.md` and `studio/edmg-studio-winui/EdmgStudio.WinUI.csproj`.
- Owned paths: `studio/edmg-studio-winui/EdmgStudio.WinUI.csproj` and this Implementer section. Existing backend/runtime work remains untouched; no dependency or accelerator-profile changes occurred.
- Completed: removed accidental WebView2 projection, WPF, WinForms, startup-object, unconditional MSIX, documentation/signing metadata, Debug optimization, and warnings-as-errors overrides. Retained .NET 10 WinUI 3, x64, conditional MSIX validation, nullable/unsafe, and stability-first untrimmed/non-ReadyToRun publishing.
- Validation: from repository root, `dotnet build studio\edmg-studio-winui\EdmgStudio.WinUI.csproj --configuration Release --runtime win-x64 --no-restore --nologo` exited 0 with 0 warnings and 0 errors. Log: `%TEMP%\edmg-winui-project-properties-build.log`. Visual Studio project build also succeeded. `git diff --check` exited 0; line-ending conversion warnings reflect the existing mixed-ending working copy.
- Remaining / blockers: none for project-property normalization. Packaged launch, signing, Store acceptance, and interactive UI qualification remain separate Gate F evidence.<!-- IMPLEMENTER-UPDATE-END -->

## Reviewer update

<!-- REVIEWER-UPDATE-START: Codex owns this section. -->

**Observed UTC:** 2026-09-28. The user supplied `LANDR-The End-Balanced-Low-REV_V3.wav` to close the opt-in real-audio planning gate after production SD1.5 qualification.

**Baseline and findings:** the two supplied pasted files have identical SHA-256 content and do not conflict. `codex/Unified` is one local commit ahead of `origin/codex/Unified` at `7978783` (`Execute PyTorch and prebuilt TensorRT routes`). That commit completed worker branches omitted by the earlier partial checkpoint, but route status could claim `torch_compile_tensorrt` while the worker actually invoked `torch_tensorrt.compile`; Diffusers pipeline roots were not classified through their component subfolders; and raw `.pt/.pth` routing did not load the classified checkpoint.

**Repairs:** installed pinned Hub revision `451f4fe16113bff5a5d2269ed5ad43b0592e9a14` of `stable-diffusion-v1-5/stable-diffusion-v1-5` as managed model `hf_sd15_internal` using complete default safetensors. Production execution exposed and repaired frontend-specific Torch-TensorRT 2.11 precision options, policy-aware numerical validation, exported-program cache loading, multi-GPU safe-mode binding, and truthful ONNX/TensorRT fallback/status for a direct Torch-TensorRT-unsupported UNet. Added repeatable production-model validation tooling. Preserved Copilot's Implementer update and WinUI project cleanup.

**Fresh evidence (repository root; exact dirty candidate; no dependency sync):**

| Gate | Result |
| --- | --- |
| Managed model | 15 pinned files/5.5 GB; complete default safetensors; full local `StableDiffusionPipeline` load succeeded in FP16 |
| Focused TensorRT/component/model-load backend tests | Exit 0; 132 passed; final status regression 43 passed |
| Real-audio Workspace flow | Exit 0; 329.995s/59.84 BPM; editable Director draft, camera/motion schedules, Apply-to-Timeline persistence, and reopen passed using source SHA-256 `E6E47C1ADCF7FE4F64EEE0A3C57670D5AE7DFB319429DB2985D4FFA71ADF1C28` |
| Full backend package suite with `STUDIO_TEST_AUDIO` | Exit 0; 1204 passed/1 skipped destructive real-model inference case |
| WinUI Core Release suite | Exit 0; 575 passed/3 skipped external native-worker cases |
| WinUI Release x64/XAML build | Exit 0; 0 warnings/0 errors |
| Live Torch-TensorRT worker | Exit 0 on RTX A6000 GPU 0; compiled, validated with max_abs 0.0, executed, serialized, and reloaded in a new worker with `allow_build=false`; engine `ebab16568a89a1bc46758fb5c98b875795c00df20b5228313a47c4a824eb2f7e` |
| Production SD1.5 VAE | Direct `huggingface_torch_tensorrt`; FP16 512x512; six validation metrics passed; exported-program reload passed; engine `a022af73f79aaea4340073ae1c6e80097b91fdf0ae2af6effb0139a8b6601eea` |
| Production SD1.5 UNet | Direct Torch-TensorRT failed closed as not fully supported; `huggingface_onnx_tensorrt` built at 64x64 latent with dynamic 32-128 profiles and batch 1-2; fixed-seed validation, cache reload, and execution passed; engine `70ec69eaadbc586e52368e6a46c6e977b35168224c8e2c0cabda40050bc0fb2c`; measured 0.0576s TRT vs 0.1343s PyTorch |
| Studio readiness | TensorRT diagnostics `ready`; healthy and compatible; VAE and UNet both `validated` and optimization-eligible with actual admitted routes serialized truthfully |
| Patch hygiene | `git diff --check` clean; branch remains one unpushed commit ahead |

**Acceptance limits:** production-size SD1.5 model installation and both registered TensorRT components are now qualified on RTX A6000 GPU 0. The text encoder intentionally remains on the existing PyTorch runtime. Full end-to-end image/video render receipt, execution on GPUs 1-2, packaged launch, signing/Store acceptance, and interactive WinUI traversal remain separate gates. The earlier transcript's native-build blocker and missing-model blocker are stale for this candidate.

<!-- REVIEWER-UPDATE-END -->
