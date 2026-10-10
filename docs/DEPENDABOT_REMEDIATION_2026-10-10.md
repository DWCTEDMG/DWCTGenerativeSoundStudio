# Dependency security remediation — 2026-10-10

Baseline: 22 open Dependabot alerts on default branch `codex/Unified` at `5ff6fb7775cad021ab79237d070708f9b3846e77`, retrieved through the authenticated GitHub API. The initial fixes addressed 15 baseline alerts, subsequently confirmed fixed by GitHub. The follow-up below upgrades another three alert resolutions and applies the actual upstream NLTK source fix. None were dismissed or hidden. GitHub's asynchronous alert state must be checked after publication.

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

## Follow-up: tested security overrides and unreleased NLTK fix

The follow-up starts from `1100375628853eabcaa266e608d9d7b8dfaee8ec` and preserves the newer default-branch Director changes at `a67b5316adc5a2f9e9a53dcee97604280c42d4c9`. It pins NeMo to the inspected 2.7.3 release and overrides only its stale Hydra/fsspec requirements with Hydra 1.3.7 and fsspec 2026.6.0. The latter stays within datasets 5.0.1's declared supported range. This is a project-maintained compatibility exception, not upstream NeMo support for these versions.

The overrides passed actual Hydra target and logging-factory escape tests, fsspec reference-template containment and benign file access, and a synthetic NeMo CTC model CUDA forward/save/restore check on an RTX A6000. The restored model parameters exactly matched the originals. This is real GPU execution with random weights, not pretrained Parakeet transcription or ASR accuracy qualification. The tests used an isolated package overlay over the existing Python environment; the active backend environment was not synchronized. Reusable checks are in `tests/test_nemo_security_cohort.py`.

NLTK now resolves from the immutable upstream archive at `cbc98458b43de5f792f0382583c16df39e5c5117`, with its SHA-256 in `uv.lock`. That revision contains the advisory's maxent, transition-parser and perceptron fixes (`2a92b71`, `a44a7af`, `cbc9845`). Its version remains 3.10.3, so a version-only vulnerability scanner may continue to flag it even though the affected APIs have been fixed. Do not replace this source with the PyPI wheel just because their versions match, and do not dismiss the advisory to hide the remaining version-based signal.

NLTK validation: 249 focused upstream tests passed, 90 optional/platform cases skipped; four upstream maxent-save tests passed. Repository model-path rejection/allowed-roundtrip/TextBlob sentiment checks plus dependency contracts passed 26 tests, with 18 optional virtualenv cases skipped. A first broad upstream invocation omitted its conftest and was invalid; the focused runs include the upstream sandbox fixtures. An unrelated extension-opcode negative-control failure in the broader pickle suite is not qualified by the focused checks. Logs: `remaining-security-candidate/nltk-security.log`, `nltk-maxent.log`, `repository-security.log`, `cohort-tests.log`, `datasets-filesystem-tests.log`, `datasets-clean-tests.log`, and `packaging-tests.log` under the machine-local audit directory. The dataset filesystem roundtrip passed with an explicit fingerprint; an initial overlay test using automatic fingerprinting hit an Arrow/dill MonthDayNano pickling error. A separate clean isolated dataset/fsspec run passed two tests. The overlay also emitted an ignored multiprocess ResourceTracker shutdown exception; the test process still exited 0. PyInstaller support regression checks passed all nine tests. These do not prove a newly built packaged executable.

## Remaining constraints and rejected upgrade candidates

| Alerts | Dependency | Reason and next action |
|---|---|---|
| 281, 132 | hydra-core | Upgraded to 1.3.7 through the tested narrow NeMo override above. |
| 189 | lightning | Still unresolved. An actual 2.6.6 import with both NeMo 2.7.3 and 3.0.0 fails in nv-one-logger 2.3.1: `OneLoggerPTLTrainer.save_checkpoint` declares `weights_only: bool`, incompatible with the newer trainer's `Optional[bool]`. The failing override was excluded. |
| 277 | fsspec | Upgraded to 2026.6.0 through the tested narrow NeMo override above. |
| 261, 135 | transformers | Still unresolved. Transformers 5.19.0/Hub 1.33.0 resolves only with additional cohort changes and an unsupported Optimum constraint override. Actual DirectML pipeline imports then fail because Optimum ONNX 0.1.0 imports removed `CLIPFeatureExtractor`. The failing major-version migration was excluded. |
| 139 | nltk | Actual upstream source fixes applied and tested; the immutable revision still identifies as 3.10.3, so the version-based alert may remain open. No patched PyPI release exists. |

Disposable resolver checks originally confirmed that patched fsspec, Hydra, and Lightning constraints were unsatisfiable with unmodified NeMo metadata. The follow-up qualifies only the narrow Hydra/fsspec exception described above. No active GPU environment was synchronized, and the failing Lightning/Transformers overrides were not introduced. Candidate failure logs are `hydra-fsspec-nemo.log`, `nemo3-import.log`, and `modern-import.log`; the first also records the successful narrow import after retaining the compatible Lightning version.

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
