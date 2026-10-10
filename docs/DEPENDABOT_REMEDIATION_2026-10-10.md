# Dependency security remediation — 2026-10-10

Baseline: 22 open Dependabot alerts on default branch `codex/Unified` at `5ff6fb7775cad021ab79237d070708f9b3846e77`, retrieved through the authenticated GitHub API. Dependency fixes below address 15 baseline alerts. Seven baseline alerts remain unresolved; none were dismissed or hidden. GitHub's asynchronous alert state must be checked after publication.

## Remediated baseline alerts

| Alerts | Dependency / manifest | Change |
|---|---|---|
| 276 | shell-quote / Studio pnpm lock | Enforce 1.11.0 |
| 275 | sprintf-js / Studio pnpm lock | Remove the unpatched dependency chain by upgrading optional global-agent 3 to 4.1.3, which no longer pulls roarr 2 / sprintf-js |
| 274, 268 | source-map-js / both pnpm locks | Enforce 1.2.2 |
| 273 | joi / Studio pnpm lock | Enforce 18.2.9 |
| 272 | postcss-selector-parser / Studio pnpm lock | Enforce 7.1.6 |
| 269 | @modelcontextprotocol/sdk / Director pnpm lock | Require >=1.31.0; resolves 1.32.1 |
| 267 | proxy-addr / Director pnpm lock | Enforce 2.0.8 |
| 280 | Werkzeug / backend uv lock | Enforce >=3.1.9; resolves 3.1.9 |
| 279 | Mako / backend uv lock | Enforce >=1.4.2; resolves 1.4.3 |
| 278 | multidict / backend uv lock | Enforce >=6.9.1; resolves 6.9.1 |
| 283, 282, 271, 270 | torch / four Space requirement files | Pin patched torch 2.13.0 with matching torchvision 0.28.0 |

Hugging Face explicitly lists torch 2.13.0 as supported by [ZeroGPU](https://huggingface.co/docs/hub/spaces-zerogpu). All four updated requirement files resolve on Python 3.12/Linux. The Hunyuan inference handler only uses the video pipeline and does not import torchaudio; its unused torchaudio 2.10.0 requirement was removed because it forces torch 2.10.0 and no torchaudio 2.13.0 release exists. No local Studio CUDA/TensorRT runtime was upgraded. Space manifest validation does not prove hosted deployment or real-model inference with the new runtime; deployment and inference remain separate qualification steps.

## Unresolved baseline alerts

| Alerts | Dependency | Reason and next action |
|---|---|---|
| 281, 132 | hydra-core | NeMo 2.7.3 ASR requires >1.3,<=1.3.2; patched Hydra requires >=1.3.6. NeMo 3.0.0 still declares the older ASR constraint. Requires an upstream-compatible NeMo release or a separately qualified ASR integration migration. |
| 189 | lightning | NeMo 2.7.3 ASR requires >2.2.1,<=2.4.0; patched Lightning requires >=2.6.6. NeMo 3.0.0 retains the older ASR constraint. Do not override metadata and claim supported Parakeet operation. |
| 277 | fsspec | NeMo 2.7.3 pins 2024.12.0; patched versions require >=2026.6.0. A NeMo 3 migration could relax this constraint, but its major-version ASR compatibility has not been qualified. |
| 261, 135 | transformers | The backend's current model integrations and NeMo/Optimum requirements retain Transformers 4.x. One advisory requires >=5.10.0; the custom-generation advisory publishes no patched version. A backend-wide 5.x/Hub migration requires separate model qualification and would not by itself justify claiming both advisories fixed. |
| 139 | nltk | Latest published NLTK remains 3.10.3 and the advisory publishes no patched version. NLTK/TextBlob resources are required by the current sentiment/packaging path. Do not remove the feature or dismiss the alert to clear a count. |

Disposable resolver checks independently confirmed that patched fsspec, Hydra, and Lightning constraints are unsatisfiable with `nemo-toolkit[asr]==2.7.3`. No active GPU environment was synchronized, and no incompatible dependency override was introduced.

References: [Hydra logging vulnerability](https://github.com/advisories/GHSA-c3wx-c55w-pxjq), [Transformers tokenizer traversal](https://github.com/advisories/GHSA-xrqw-3rrv-vx5w), [Transformers custom-generation consent](https://github.com/advisories/GHSA-x9r9-c232-4q39), [NLTK model-artifact sandbox bypass](https://github.com/advisories/GHSA-8mgp-746c-j5xp), [NeMo 2.7.3 metadata](https://pypi.org/pypi/nemo-toolkit/2.7.3/json), [NeMo 3.0.0 metadata](https://pypi.org/pypi/nemo-toolkit/3.0.0/json).

## Additional finding

The refreshed Studio npm audit reports an additional high-severity `braces<=3.0.3` nesting denial of service, [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm), with no published patched version. It was not one of the original 22 alerts and remains open. Director's npm audit reports zero vulnerabilities. Studio's npm audit is therefore not clean even after the eight original npm alerts are remediated.

## Validation and boundaries

- Frozen pnpm installs succeeded for Studio and Director, using pinned pnpm 10.33.0.
- Backend `uv lock --check` succeeded without changing the active inference environment.
- All four Space requirements resolved for Python 3.12/Linux.
- Dependency security regression checks: 18 passed; 18 pre-existing optional virtualenv runtime cases skipped because virtualenv is absent. Checks enforce patched backend/npm resolutions, absence of sprintf-js, and the four patched Space torch pins.
- Isolated patched Werkzeug/Mako/multidict request/template/multi-value-map smoke checks passed.
- Director TypeScript check, production widget build, and all 13 Director tests passed.
- Studio TypeScript check and production build passed. Release-toolchain tests: 110 passed, one platform skip. Focused frontend API/Director tests: 14 passed with the threads pool. Full frontend attempts with forks and threads did not complete before interruption; the full suite is not qualified by this change.
- Electron's installed downloader dependencies successfully bootstrapped the updated optional global-agent proxy implementation.
- Existing virtualenv runtime tests may skip when the optional development package is absent; this change does not claim new virtualenv runtime qualification.

Machine-local command logs and baseline/final API snapshots are under `C:\Users\user\Documents\NVIDIA-Studio-Audit-20261009`. Logs are outside Git. A lower alert count is not proof that an active service or already-deployed Space has installed the updated dependencies.
