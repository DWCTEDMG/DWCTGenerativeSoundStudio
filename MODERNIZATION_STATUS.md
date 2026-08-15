# DWCT Generative Sound Studio Release-Convergence Status

Current review date: 2026-08-06
Canonical product: WinUI Windows client plus the shared Studio backend in `studio/edmg-studio`
Canonical Python lock: `studio/edmg-studio/python_backend/uv.lock`

This document now separates **current verified truth** from the historical seven-day implementation
ledger. The day-by-day tables later in this file are retained as planning history from 2026-07-14;
their individual `Partial` and `Not started` labels are not current implementation claims.

A capability is release-complete only when implementation, Studio UI, contracts, tests,
documentation, packaged behavior, and required external evidence all agree. Code that exists but
lacks clean-machine, signing, upgrade, GPU, or platform evidence remains release-incomplete.

The canonical internal renderer remains
`studio/edmg-studio/python_backend/edmg_studio_backend/services/internal_video.py`. Modernization
must extract bounded services around that behavior and preserve golden outputs; it must not create
a second canonical render loop.

## Current release baseline

This table identifies the canonical gate and the evidence still required from the exact candidate.
It does not preserve a branch name, commit snapshot, or test count as if that were current release
proof. Refresh every command-derived row after the final candidate commit and artifact build.

| Gate | Candidate requirement | Status |
|---|---|---|
| Git scope | Record the final candidate commit and a clean, reviewed release scope immediately before packaging | Refresh at release |
| Python toolchain | Python 3.12, uv 0.11.28, and the canonical frozen lock select exactly one CPU/DirectML/CUDA profile | Implemented; revalidate |
| Repository suite | Run the canonical frozen repository scopes and evaluate the current skip/warning set | Refresh at release |
| Backend suite | Run the canonical frozen CPU/core/audio backend suite from the committed lock | Refresh at release |
| Backend lint | Run focused changed-file checks and record the current full-tree Ruff baseline separately; do not present focused lint as full-tree lint or a security scan | Cleanup and refresh required |
| Frontend lint | Run the canonical Studio ESLint gate on the final source candidate | Refresh at release |
| Frontend type contract | Verify the browser and Electron adapters against the current typecheck and runtime suites | Refresh at release |
| Frontend UI suite | Run the complete current UI suite, including Studio Forge coverage | Refresh at release |
| Release tooling | Run the complete release-toolchain suite and evaluate only its current platform skips | Refresh at release |
| Desktop runtime | Run the backend/build-identity/window runtime suites on the final source candidate | Refresh at release |
| Frontend production build | Produce a fresh Vite build from the final source candidate | Refresh at release |
| DirectML backend bundle provenance | Regenerate staging only from committed, clean dependency inputs and require the staged manifest to match the candidate lock, source, platform, profile, and binary | Rebuild required |
| JavaScript dependency audit | Run production and complete development/build audits against the final lockfile and retain their current reports | Refresh at release |
| Production signing gate | Configure the authorized signing identity and require the fail-closed production gate; do not infer credential or signature state from this document | Credential evidence required |
| Installed baseline | EDMG Studio 1.1.0 CUDA onedir installation with a schema-5 backend manifest | Available for read-only upgrade evidence |
| Installed CUDA runtime | Python 3.12.10, PyTorch 2.11.0+cu130, TensorRT 10.15.1.29, Torch-TensorRT, CUDA Python 13.0.3 | Present |
| Candidate signatures | Verify Authenticode signatures and timestamps on every freshly built shipped executable and installer | Release blocker until evidenced |
| Active Studio Home legacy TensorRT engines | Four safe root-level engines detected read-only (4,636,659,776 bytes); canonical bundle absent; E: has sufficient copy capacity | Eligible for explicit copy; not executed |
| D: capacity | Windows reports zero free bytes; Triton and external model folders on D: remain read-only and excluded | Operational blocker for any D: write/build/cache |

Update this table whenever a named gate is rerun. Do not infer a green release from an older build
directory or from unit tests alone.

## Current implementation truth

The repository contains substantially more implementation than the historical ledger recorded:

- versioned project manifests, validation, migrations, backups, and atomic writes;
- SQLite/WAL jobs and events with leases, retries, idempotency, and recovery coverage;
- autosave/recovery journals and project-health paths;
- typed v1 domain contracts and compatibility adapters;
- timeline commands with undo/redo foundations;
- Music Graph v1, corrections/reverts, Director modes, Visual DNA, motion grammar, and stem
  modulation;
- Render Plan v1, continuity validation, variant review, provider/model lanes, and promotion paths;
- live cues/assets, world adapters, template packages, and performer workflow foundations;
- frozen uv accelerator profiles and release-bundle provenance;
- CycloneDX/checksum generation and fail-closed Windows signing hooks;
- packaged customer-flow, migration, upgrade, and zero-state proof harnesses;
- read-only installed-baseline inspection with strict newer-candidate and path-confinement rules;
- in-app packaged build identity with source, binary, and dependency-lock fingerprints; and
- a source-preserving legacy TensorRT engine migration with conservative readiness plus exact,
  server-resolved bundle-path handoffs for dedicated video and SVD/AnimateDiff anchors;
- retirement of the simulated TensorRT Deforum renderer, with the deprecated route/job contract
  preserved only as a tested adapter into the canonical internal renderer; and
- private TensorRT filesystem paths resolved only at execution and removed from public preflight
  evidence and newly persisted TensorRT job payloads.

These areas are still structurally or evidentially incomplete:

- `edmg_studio_backend/app.py` remains an oversized composition and route module;
- Render, Timeline, Settings, and several workbench pages remain multi-thousand-line feature
  monoliths;
- HTTP and Electron/browser contracts are not yet generated and enforced from one authority;
- not every task uses one uniform durable job state machine and recovery UI;
- model manifests and provider adapters do not yet enforce every license, checksum, revision,
  resource, cancellation, provenance, and fallback field;
- accessibility, reduced-motion, scaling, keyboard, and flash-safety evidence is incomplete;
- named-hardware render quality/performance/cancel/recovery evidence is incomplete; and
- packaged provenance fingerprints exact source, binary, and lock content but does not yet record
  an archive-safe Git commit/dirty identity;
- signed installers, clean-machine install, real previous-version upgrade, rollback, and publication
  evidence remain required.

## Canonical and compatibility paths

The detailed retirement policy and removal gates live in `docs/COMPATIBILITY_MATRIX.md`.

| Path | Classification | Rule |
|---|---|---|
| `studio/edmg-studio-winui` | Primary Windows frontend | Native Studio workflows use the shared authenticated API; do not duplicate inference or rendering |
| `studio/edmg-studio` | Canonical backend and Linux/compatibility client | Own shared backend, project contracts, Electron/React compatibility, and the currently qualified packaging lanes |
| Repository root | Active workspace/orchestration | Keep cross-scope tests, docs, deployment, and compatibility launchers; do not create a second app |
| `studio/edmg-studio/python_backend/edmg_studio_backend` | Canonical Studio backend | Extract by domain while preserving routes and persisted formats |
| `studio/edmg-studio/python_backend/enhanced_deforum_music_generator` | Canonical bundled engine package | Access through stable facades and tests |
| Root `enhanced_deforum_music_generator`, `utils`, `config`, `core`, and `edmg` wrappers | Compatibility | No new imports; retain only while existing consumers are inventoried and tested |
| Root `librosa` package | Source/test compatibility shadow | Namespace and retire before a future Python upgrade |
| `desktop/electron` | Legacy shell | Freeze; remove after supported migration and launch evidence |
| `chatgpt-apps/edmg-director` | Optional sidecar | Share backend contracts; never own separate canonical project state |
| ComfyUI | Optional provider | Capability-gated adapter, not a parallel product architecture |
| Triton Inference Server | Research-only optional provider | Excluded from 1.2.0 release requirements; see `docs/TRITON_PROVIDER_READINESS.md` |

## Release blockers in execution order

1. Review and commit the current implementation, including the changed backend dependency inputs,
   then record immutable source, lock, package, and installed-baseline evidence for the candidate.
2. Run complete source gates and contract-drift checks on Windows and Ubuntu.
3. Build and qualify a fresh signed DirectML candidate from the frozen lock; if CPU or CUDA are
   public SKUs, build, sign, inspect, and qualify each separately. The default production command
   is not a three-profile matrix gate, and stale bundles/evidence must not be reused.
4. Sign the desktop executable, backend/helper executables, installer, and uninstaller, then verify
   signatures and timestamps independently.
5. Run zero-state install and customer flow on a clean supported Windows machine.
6. Run a real upgrade from a separately identified installed baseline; never treat the candidate as
   its own previous version and never mutate the baseline during inspection.
7. Prove custom install directory, custom Studio Home, migration, restart recovery, cancellation,
   uninstall data retention, and rollback. Include legacy TensorRT partial/unsafe/disk rejection,
   cancellation cleanup, unchanged source hashes, atomic publication, and the engine-only
   canonical bundle's explicit not-ready state.
8. Produce named-hardware CUDA/TensorRT model, quality, VRAM, latency, cancellation, and recovery
   evidence. Prove the completed bundle becomes ready only with all required assets/metadata, both
   render flows receive the exact server-resolved bundle path, base/temporal paths remain distinct,
   and a client filesystem path supplied as `model_id` is rejected.
9. Complete security, accessibility, known-issues, and branch-protection evidence before public
    promotion.

## Historical seven-day ledger

The following material records the July 14 planning checkpoint. It is useful for package IDs and
original acceptance criteria only. Consult the current sections above and live tests before using a
historical status label.

### Historical recorded baseline

- GitHub Actions run [29313230364](https://github.com/DWCTEDMG/DWCTGenerativeSoundStudio/actions/runs/29313230364)
  recorded the then-configured Studio workflow on Windows and Ubuntu, including FFmpeg discovery,
  Python/frontend gates, and the Windows Electron smoke path. It is historical, not current proof.
- The historical Studio and Director dependency baselines recorded frozen installs, audits,
  typecheck/lint/build gates, and their then-current test suites without failures. Re-run the
  current suites instead of carrying their old totals forward.
- The historical local Python baseline recorded clean repository and backend suite results with
  documented opt-in live-smoke skips. Its exact totals are intentionally omitted because the suite
  has since changed.
- Historical local dependency audits and remote alert/branch settings are not release evidence for
  the current candidate. Reinspect both the final lockfile and live repository governance before
  promotion; do not infer current default-branch or protection state from this ledger.
- The public repository currently reports no detected license. License intent therefore needs to be
  made explicit without implying an unapproved open-source grant.

## Status legend

- `Complete`: acceptance criteria and evidence are satisfied.
- `In progress`: implementation or evidence work is actively underway.
- `Partial`: useful implementation exists, but the blueprint contract is incomplete.
- `Not started`: no qualifying implementation exists yet.
- `Blocked evidence`: an external credential, hardware target, repository setting, or release action
  is required for the final proof.

## Day 1 - Freeze contracts and turn the baseline green

| ID | Status | Dependencies | Files owned | Tests / evidence | Blockers or remaining work |
|---|---|---|---|---|---|
| P0-01 | Complete | None | `.github/workflows/studio.yml`; `scripts/run_pytest_scopes.py`; FFmpeg tests | GitHub run 29313230364 passed Windows and Ubuntu | None |
| P0-02 | Blocked evidence | Repository admin approval | `docs/BRANCH_POLICY.md`; `CONTRIBUTING.md`; `RELEASE.md` | Policy documents name `main`, `next`, required checks, promotion, and rollback | Live default-branch, protection, and required-check settings must be reinspected and any mutation requires explicit approval |
| P0-03 | Complete | None | `.gitignore`; `.env.example`; `LICENSE`; `SECURITY.md`; `CHANGELOG.md` | Root `.env` is untracked/ignored; placeholder scan and documentation checks | All-rights-reserved notice preserves the repository's existing no-license-grant posture; owner may approve a different license later |
| P0-04 | In progress | W1-01 | readiness service/contracts; `/v1/system/readiness`; Studio System/Setup UI | Backend contract/failure tests; UI state tests; typecheck/lint/build | Unified typed disk, writable-path, runtime, GPU, FFmpeg, and model-completeness report still needed |
| P0-05 | Complete | W1-01 | `tests/fixtures/day1/**`; `scripts/generate_day1_fixtures.py`; `tests/test_day1_fixture_inventory.py`; `docs/TEST_FIXTURES.md` | Determinism, SHA-256, size, WAV, SVG, and legacy-project adapter tests | Existing 73 MB real-audio fixture is retained but excluded from the redistributable manifest until separate provenance is recorded |
| P0-06 | Complete | P0-05, W1-01 | `scripts/benchmark_day1_baseline.py`; benchmark tests; `docs/BENCHMARKING.md`; `docs/benchmarks/day1-baseline-windows-2026-07-14.json` | The dated benchmark artifact records backend launch, project open, timeline, analysis, and strict Electron launch on named HP Victus hardware | Installed production-build launch, browser paint, render, cancel, and recovery timings remain explicitly later P5-02/W7-04 evidence |
| W1-01 | Complete | None | `edmg_studio_backend/contracts/**`; `src/contracts/v1.ts`; contract tests; `docs/CONTRACTS_V1.md` | Python/frontend contract coverage and the Studio typecheck were recorded at the checkpoint; rerun their current forms | Full gates remain part of the Day 1 integration gate; current stores/render paths are unchanged |
| UV-01 | In progress | Toolchain inventory | `.python-version`; uv pin/config; backend `pyproject.toml`; supported setup/build/CI paths; uv docs/tests | Windows parity tests and CI/static entry-point checks | Ubuntu parity after edits requires CI; lockfile and frozen project commands are explicitly UV-02/UV-03 work |

## Day 2 - Make projects, jobs, and artifacts durable

| ID | Status | Dependencies | Files owned | Tests / evidence | Blockers or remaining work |
|---|---|---|---|---|---|
| P1-01 | Partial | W1-01 | project schemas/migrations; `store/projects.py` | Current/legacy round trips; failed-migration recovery; backup proof | Atomic writes exist; version validation, migration registry, and backup-before-migrate are missing |
| P1-02 | Not started | W1-01 | SQLite job/event store; scheduler/worker | FIFO/priority, competing-worker, lease, retry, restart tests | Current JSON/process-local store lacks durable claim and recovery semantics |
| P1-03 | Partial | W1-01, P1-01 | artifact contract/writer; render call sites | Manifest validation, hashes, lineage | Sidecar provenance exists only on some paths |
| P1-04 | Not started | P1-01, P1-03 | asset index/service; Project Health UI | Missing/changed/duplicate media; cleanup safety | No index, relink, collection, or reference-count workflow |
| P1-05 | Not started | P1-01 | autosave journal; recovery API/UI | Forced-termination recovery | No crash-recovery journal |
| P1-06 | Partial | W1-01 | generated API client; Electron IPC contracts | Client drift and malformed-IPC tests; bridge e2e | Pydantic and allowlisted IPC exist; generated/validated boundaries do not |
| UV-02 | Not started | UV-01 | `pyproject.toml`; `uv.lock`; accelerator groups/sources | Frozen CPU, DirectML, and CUDA syncs | Day 2 work |
| UV-03 | Not started | UV-02 | launchers, setup wizard, pytest runner, CI, backend scripts | Clean-machine frozen entry-point matrix | Day 2 work |

## Day 3 - Reshape the studio without changing behavior

| ID | Status | Dependencies | Files owned | Tests / evidence | Blockers or remaining work |
|---|---|---|---|---|---|
| P2-01 | Not started | W1-01, P1-06 | domain routers/services; `app.py` | Route inventory and OpenAPI compatibility | `app.py` remains a large monolith |
| P2-02 | Partial | W1-01, P1-01 | Timeline command/store modules | Per-command undo/redo and history persistence | Editing exists; command abstraction/history do not |
| P2-03 | Not started | P1-06, P2-01, P2-02 | `src/features/**`; Render/Timeline/Settings pages | UI parity, typecheck, lint, build | Large page-local systems remain |
| P2-04 | Partial | P1-02, P1-06 | job API/store; Render Queue UI | State-machine contracts and every UI transition | Pause and uniform blocked/recovery states are missing |
| P2-05 | Partial | W1-01, P3-01 | analysis APIs; Understand feature | Correction persistence/invalidation; keyboard UI | Existing views are distributed and not uniformly editable |
| P2-06 | Partial | P0-04, P0-05, P1-01, P1-02 | starter project; first-run UI/e2e | Clean-machine supported-render e2e | No bundled guided starter proof |

## Day 4 - Install the music-aware intelligence layer

| ID | Status | Dependencies | Files owned | Tests / evidence | Blockers or remaining work |
|---|---|---|---|---|---|
| P3-01 | Partial | W1-01, P1-01 | Music Graph schema/service; audio-analysis consumers | Golden graphs; cache invalidation; consumer contracts | Analysis exists but is not a versioned graph with algorithm/content identity |
| P3-02 | Partial | P3-01, P5-01 | ASR/CLAP services; learned-result cache/UI | Offline, multilingual, cache, confidence fixtures | ASR exists; CLAP and formal confidence/offline policy are incomplete |
| P3-03 | Partial | W1-01, P3-01 | planner contracts/services; Creative Direction UI | Deterministic proposal and edit/apply fixtures | Six formal Director modes are missing |
| P3-04 | Partial | P3-01 | Visual DNA services/routes/workspace UI | Persistence, feedback, inspect/edit/approve e2e | Backend memory is strong; dedicated editable workspace is missing |
| P3-05 | Partial | P2-02, P3-01 | motion grammar compiler/contracts | Phrase-to-schedule goldens and lane parity | Formal Prepare/Accent/Travel/Settle/Contrast grammar is missing |
| P3-06 | Partial | P2-02, P3-01, P3-05 | modulation matrix/store/API | Bounds, undo, bake, keyboard accessibility | Current aggregate reactive controls are not a stem-aware matrix |

## Day 5 - Complete the adaptive Render Conductor

| ID | Status | Dependencies | Files owned | Tests / evidence | Blockers or remaining work |
|---|---|---|---|---|---|
| P4-01 | Partial | W1-01, P1-02, P1-03, P3-01, P3-03, P3-04 | Render Plan DAG/contracts/planner | DAG validation, immutability, cache keys, compatibility | Current plan is advisory rather than an immutable task DAG |
| P4-02 | Partial | W1-01, P4-01 | capability broker and provider adapters | Shared adapter conformance suite | Existing capability protocol is not one executable multi-lane contract |
| P4-03 | Partial | P1-03, P4-01, P4-02 | lane-promotion contract | Cross-lane timing/framing/control/lineage goldens | Production-lane equivalence evidence is missing |
| P4-04 | Partial | P4-01, P4-02, P5-02 | budget controller and explanation UI | Deterministic time/memory/cost allocation fixtures | Hero heuristic exists without named-task reallocation |
| P4-05 | Partial | P1-03, P3-04, P4-01 | Variant Review contracts/UI | Variant lifecycle and synchronized compare e2e | Approval/cherry-pick/locks/notes/review provenance incomplete |
| P4-06 | Partial | P3-04, P4-01, P4-05 | continuity validators/UI warnings | Per-validator fixtures and false-positive review | Scalar risk exists; typed continuity conflict checks do not |

## Day 6 - Finish model lanes and music-to-world expansion

| ID | Status | Dependencies | Files owned | Tests / evidence | Blockers or remaining work |
|---|---|---|---|---|---|
| P5-01 | Partial | W1-01, P0-04 | model manifest/catalog/manager/UI | Schema, checksum/revision, legacy-adapter tests | Required revision/checksum/runtime/storage/fallback fields are not enforced |
| P5-02 | Partial | P0-06, P4-02, P5-01 | benchmark harness/result schema | Repeatable CPU/GPU benchmark fixtures | Install/quality/resources/cancel/recovery/determinism evidence incomplete |
| P5-03 | Partial | P5-01, P5-02 | catalog lanes, promotion policy, Models UI | Lane visibility and promotion-policy tests | Five formal evidence-gated lanes are missing |
| P5-04 | Partial | P4-02, P5-01, P5-02, P5-03 | candidate adapters/catalog entries | Install, smoke, failure, provenance per candidate | Candidate versions and GPU evidence remain incomplete |
| W6-01 | Partial | W1-01, P3-01, P3-06 | live cue protocol/compiler | OSC/MIDI/WebSocket protocol goldens/simulators | Existing Unreal preview is not a stable live protocol |
| W6-02 | Partial | P4-02, W6-01 | TouchDesigner and Unreal adapters | Simulator-driven adapter contracts | Unreal preview exists; TouchDesigner and live execution do not |
| W6-03 | Not started | P1-03, W6-01, W6-02 | bounded live asset runtime | Latency budget and slow-provider isolation | No precomputed live-pack runtime |
| W6-04 | Partial | W1-01, P5-01 | template package schema/installer/UI | Install, upgrade, compatibility tests | Static preview templates are not versioned installable packages |
| W6-05 | Not started | P1-03, P4-02, P5-04, W6-01 | performer workflow/provider selection | Mock/high-end selection, fallback, cancel, provenance | No complete audio-driven external/high-end workflow |

## Day 7 - Prove, package, document, and release the beta candidate

| ID | Status | Dependencies | Files owned | Tests / evidence | Blockers or remaining work |
|---|---|---|---|---|---|
| P5-05 | Partial | P0-02, P0-03, UV-04, W7-01 | packaging/release workflows/scripts | Clean-machine artifact, signature, SBOM, checksum, update/rollback e2e | Signing credentials may block evidence; updater/SBOM pipeline incomplete |
| P5-06 | Partial | All completed packages | creator/project/security/migration/known-issues docs | Link check and clean-user walkthrough | Dedicated documentation set incomplete |
| UV-04 | Not started | UV-02, UV-03 | `prepare-release-bundle.mjs`; release provenance | Frozen CPU/DirectML/CUDA packaging | Day 7 work |
| W7-01 | Partial | All implementation packages | full test matrix/workflows | Unit, contract, FFmpeg, SQLite, IPC, Electron, media, migration, recovery | Several named suites do not exist yet |
| W7-02 | Blocked evidence | P5-02, P5-04 | immutable benchmark artifacts | Published Windows/Ubuntu/GPU results and failures | Required hardware and artifact publication |
| W7-03 | Partial | P2 UI extraction, W6 live UI | accessibility/safety implementation and reports | Keyboard, contrast, scaling, reduced motion, flash, consent | Formal audit and several controls are missing |
| W7-04 | Not started | P0-06 and final implementations | performance evidence | Named-hardware launch/open/timeline/analysis/planning/cancel/recovery | Final-system measurements cannot precede implementation |
| W7-05 | Partial | P5-05, P5-06, UV-04, W7-01-W7-04 | release manifest/changelog/blockers/rollback | Signed beta handoff where credentials exist | Depends on all release evidence; signing can remain an explicit blocker |

## Safest parallel merge order

1. Keep the Dependabot remediation isolated, then freeze W1-01 contracts and compatibility fixtures.
2. Merge independent Day 1 lanes after the contract freeze: P0-03 policy/hygiene, P0-05 fixtures,
   P0-06 measurements, and UV-01. Merge P0-04 after W1-01 so readiness uses the frozen contract.
   Treat P0-02 remote settings as a separate evidence gate.
3. Merge durability sequentially: P1-01, P1-02, P1-03, then P1-04/P1-05, then P1-06.
   UV-02 must precede UV-03.
4. Merge behavior-preserving structural work only after contract tests: P2-01/P2-02, then
   P2-03/P2-04, then P2-05/P2-06.
5. Merge P3-01 before its consumers; then P3-02/P3-03/P3-04 in parallel, followed by P3-05 and
   P3-06.
6. Merge Render Plan before its consumers: P4-01, P4-02, P4-03/P4-04, P4-05, then P4-06.
7. Merge model evidence in order P5-01, P5-02, P5-03, P5-04. Merge live work in order W6-01,
   W6-02, W6-03, with W6-04 parallel and W6-05 last.
8. Close with UV-04, the W7 evidence gates, P5-05/P5-06, and W7-05.

## Day 1 integration gate

The gate passes when:

1. the remote default baseline remains green and the candidate source passes every supported full
   gate;
2. each implementation lane compiles against W1-01 versioned contracts;
3. legacy project and existing render-path compatibility tests pass;
4. the canonical internal renderer remains unchanged; and
5. external evidence that cannot be produced without a push, repository-admin action, unavailable
   hardware, or credentials is named here rather than silently waived.
