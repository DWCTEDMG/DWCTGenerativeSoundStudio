# EDMG Studio Microsoft Store Submission Blueprint

Prepared: 2026-09-16 UTC  
Target: WinUI 3, Windows x64, Microsoft Store MSIX submission  
Status: Planning document; upload readiness is not yet established  
Signing: User reports existing Azure code signing; service type and integration remain unverified

## 1. Outcome and Release Boundaries

Prepare a reproducible Store upload candidate, validate the packaged customer experience, and submit it through Partner Center. A same-day submission is a target, conditional on the gates below. Microsoft certification and public availability have no same-day commitment.

Track these milestones separately:

| Milestone | Completion evidence |
| --- | --- |
| Package staged | Fresh Store-identity `.msixupload` containing the validated backend |
| Upload ready | Candidate-bound package checks, applicable local certification checks, customer-flow evidence, and submission details complete |
| Uploaded | Partner Center accepts the specific package; upload receipt recorded |
| Submitted | All submission sections complete and Partner Center confirms submission for certification |
| Certified | Microsoft returns a passing certification result for that submission |
| Publicly released | Approved package is available under the selected publication settings and Store installation is checked |

Certification must remain pending before Microsoft returns a result. Never invent a passing result to satisfy a local release gate.

This blueprint supplements Gate F in [the consolidated WinUI blueprint](blueprint/WINUI3_CONSOLIDATED_BLUEPRINT.md). It does not replace the product roadmap or authorize implementation, signing, uploads, or changes to another agent's work. Coordinate execution through [STUDIO_PROGRESS.md](STUDIO_PROGRESS.md).

## 2. Observed Starting Point

These observations come from files inspected on 2026-09-16. Recheck them before execution.

| Area | Evidence and implication |
| --- | --- |
| Existing package | `studio/edmg-studio/release/winui-msix/winui-msix.json`, dated 2026-09-15, reports `releaseMode: developer`, `distributable: false`, and `backend: null`. It is not the upload candidate. |
| Package identity | The source manifest and existing package record use publisher `CN=AppPublisher`. Store staging must supply the exact Partner Center identity. |
| Build/test history | The handoff records a successful WinUI Release/XAML build, 511 core tests, and passing Python suites. These are recorded baseline results, not tests executed for this blueprint or proof of a packaged release. |
| Runtime acceptance | The handoff explicitly leaves real model inference, installer lifecycle, and Store qualification unverified. |
| Azure signing | Available according to the user. No Azure account, certificate profile, permission, or signed artifact was inspected. |
| Store tooling | An existing staging script accepts `-ReleaseMode store`, `-StoreIdentityFile`, and `-IncludeProductionBackend`. |
| Command mismatch | The `stage:winui:msix` package script hardcodes developer mode. The README's Store example does not supply the required Store mode. Use the direct script invocation in section 6. |
| Signing integration | The inspected local signing helper accepts PFX/P12 files or certificate-store thumbprints. Azure service signing support must be verified or implemented before claiming integration. |
| Artifact finalization | The staging script explicitly describes its output as intermediate and not candidate-bound or distributable until finalization. An emitted upload file alone does not satisfy release gates. |

## 3. Gate A: Partner Center and Product Scope

Owner: Product/account owner, with implementer support.

- [ ] Verify the developer account is active and has access to the intended app.
- [ ] Confirm the reserved app name and product ID.
- [ ] Obtain exact identity name, publisher distinguished name, publisher ID, display name, and publisher display name from Partner Center.
- [ ] Choose a valid increasing package version with a zero fourth component, checked against prior submissions.
- [ ] Limit this release to x64 unless another architecture has equivalent qualification evidence.
- [ ] Define supported Windows versions, GPU/runtime requirements, and the features advertised in this release.
- [ ] Confirm which models are optional downloads and which workflow is available immediately after setup.
- [ ] Prepare the external Store metadata document using `StoreSubmission.example.json` and `StoreSubmission.schema.json` under `studio/edmg-studio-winui`.

Store identity must match Partner Center exactly. Do not substitute the Azure signing certificate subject for the Store publisher. Microsoft documents the identity and signing requirements in its [MSIX package requirements](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/app-package-requirements).

Keep credentials, signing keys, and access tokens out of source and evidence. The ignored `StoreIdentity.json` path can hold the completed submission metadata expected by the staging script; verify the ignore rule before placing account-specific data there.

Exit criterion: Real account identity and submission scope are recorded, with no placeholders represented as completed evidence.

## 4. Gate B: Azure Signing and Distribution Paths

Owner: Signing/account owner and packaging implementer.

First identify the existing Azure service. If it is Azure Artifact Signing, formerly Trusted Signing, use its supported signing integration. If it is a certificate held in Azure Key Vault or another service, use that service's actual supported integration. An Azure subscription or certificate record alone is not a successful signing test.

### Store MSIX path

The Store re-signs MSIX/AppX packages after certification; a purchased CA certificate is not required for this upload. The current staging script rejects `-RequireSigning` when a Store identity file is supplied. Preserve that behavior for the upload container. [Microsoft signing requirements](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/app-package-requirements)

### Azure-signed test and direct-distribution path

- [ ] Verify the service, account, endpoint, certificate profile, validated publisher, and signer access.
- [ ] Confirm a public-trust profile is appropriate for public distribution.
- [ ] For Artifact Signing, integrate the supported SignTool/DLL or CI action workflow; do not pretend a service profile is a local certificate thumbprint.
- [ ] Preserve existing PFX/thumbprint support while adding any required provider selection.
- [ ] Sign the intended binaries and package in the correct order, then generate hashes from final bytes.
- [ ] Verify signatures, certificate chains, timestamps, and artifact hashes independently; signing-request success alone is insufficient.
- [ ] For a locally signed MSIX, ensure its manifest publisher matches the actual signing certificate subject.
- [ ] Record the relationship between the locally installable test package and Store candidate. Different identity/signature bytes mean different artifact hashes.

Artifact Signing uses account/profile metadata and a supported signing client. Timestamping is required for durable signature validation with its short-lived certificates. See [Azure signing integration](https://learn.microsoft.com/en-us/azure/artifact-signing/how-to-signing-integrations) and [verification guidance](https://learn.microsoft.com/en-us/azure/artifact-signing/faq).

Do not sign the `.msixupload` ZIP container as if it were an executable. Do not hold the Store upload solely for an optional direct-download Setup.exe unless the chosen release policy requires that deliverable. Existing project requirements for shipped executable signatures still need appropriate evidence.

Exit criterion: The Store signing path is understood and any Azure signing required for local acceptance or shipped binaries is demonstrated on the actual candidate artifacts.

## 5. Gate C: Freeze and Build the Candidate

Owner: Packaging implementer; reviewer checks recorded evidence.

- [ ] Select a reviewed source commit and record its SHA, branch, clean/dirty state, toolchain, and accelerator profile.
- [ ] Resolve intended source changes through normal review. Do not discard concurrent work to obtain a clean tree. The current Store candidate builder requires a clean Git tree, so this blueprint must also be included in the chosen reviewed commit or kept outside the isolated build checkout.
- [ ] Use pinned project tools: Python 3.12, uv 0.11.28, and the frontend package-manager version specified in `package.json`.
- [ ] Build a fresh complete PyInstaller `onedir` backend using the existing release pipeline and selected supported accelerator profile.
- [ ] Validate the backend manifest, frozen dependency inputs, helper binaries, and complete payload before embedding it under the package's `backend` directory.
- [ ] Build the x64 WinUI Release package with its required Windows App SDK deployment.
- [ ] Record applicable build/test logs against this candidate. Re-run checks when the source or packaged payload changes.
- [ ] Preserve checksums, SBOM, dependency/model notices, and signing evidence for the final shipped bytes.

Use [the WinUI packaging documentation](studio/edmg-studio-winui/README.md), [Windows packaging instructions](studio/edmg-studio/packaging/windows/README.md), and [the release runbook](docs/STUDIO_RELEASE_RUNBOOK.md). Resolve discrepancies against current code and explicit release requirements before building.

The backend must not depend on this workstation's repository, `.venv`, global Python/Node/uv installation, Hugging Face token, model cache, or hardcoded runtime path. Keep GPU-first behavior and preserve existing GPU environments.

Exit criterion: A fresh validated backend and WinUI build share a recorded candidate and supported hardware profile.

## 6. Gate D: Stage and Finalize the Store Package

Owner: Packaging implementer.

The following is a future execution command, not a command run while writing this blueprint. It assumes a clean reviewed candidate, validated production backend, and completed external metadata. Run from the Studio directory shown below.

```powershell
Set-Location 'C:\Users\user\source\repos\DWCTGenerativeSoundStudio\studio\edmg-studio'

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\packaging\windows\stage_winui_msix.ps1 `
  -ReleaseMode store `
  -StoreIdentityFile ..\edmg-studio-winui\StoreIdentity.json `
  -IncludeProductionBackend
```

Do not append `-RequireSigning` to this Store command. Do not use `pnpm run stage:winui:msix` as a Store command while it hardcodes developer mode.

The current metadata validator requires `certification`, `knownIssues`, and `rollback` objects, each with a status and evidence reference. Initial submission should truthfully record certification as not yet submitted or pending and reference a real preparation/status record explaining that no Microsoft result exists. The ordinary validator does not require certification to have passed; its production option does. Check every downstream gate so an initial upload is not incorrectly blocked on its own future certification. Never fabricate evidence or turn off validation to bypass this distinction.

- [ ] Validate the generated manifest identity, version, architecture, declared capabilities, assets, and runtime dependencies.
- [ ] Inspect the upload archive and confirm the complete intended backend is present.
- [ ] Complete or implement the Store-specific artifact finalization path. The staging script currently emits intermediate metadata; do not merely flip `distributable` or `storeSubmissionReady` flags.
- [ ] Bind final upload filename, size, SHA-256, source candidate, backend manifest, and acceptance evidence together.
- [ ] Keep upload-ready status distinct from public-distribution approval and returned Store certification.
- [ ] Test that pending certification can proceed to initial submission, while public release still requires returned certification and applicable acceptance evidence.

Exit criterion: A verified Store upload artifact is bound to its actual inputs and acceptance results. Any tooling gap above is an implementation blocker, not a completed step.

## 7. Gate E: Packaged Customer Acceptance

Owner: Release tester; reviewer checks logs and outputs.

Use a disposable supported Windows machine without repository tooling or developer caches. Record OS, hardware, GPU/driver, package identity/version, artifact hashes, timestamps, and outcomes. Launch through registered package identity.

| Check | Required outcome |
| --- | --- |
| Installation and launch | Package installs and launches; backend starts; missing prerequisites have actionable UI errors. |
| First-run setup | A new user completes setup without developer tokens, manual source commands, or workstation-only paths. |
| Model setup | Required model/runtime downloads, progress, license acknowledgement, verification, cancellation, and retry work through WinUI. |
| Main workflow | Create project, import audio, analyze, plan, review timeline, render using an advertised supported model, and export a playable result. |
| Honest readiness | Installed, configured, reachable, model-loaded, and smoke-qualified states reflect actual evidence. A model download is not inference proof. |
| Persistence and recovery | Reopen the project and preserve edits; autosave/recovery works after an interrupted session. |
| Failure behavior | Network interruption, missing GPU support, insufficient storage, and unavailable models produce recoverable, accurate UI states. |
| Accessibility | Main workflow works with keyboard navigation and supported display scaling; review contrast and motion/flash behavior. |
| Lifecycle | Validate applicable upgrade, repair, recovery, uninstall/data retention, and rollback procedures on disposable test systems. |
| Certification preflight | Run the applicable Windows App Certification Kit checks and investigate failures for this exact package. |

For a first Store release with no prior Store version, record that upgrade baseline as not applicable with a reason. Existing sideload installations may use a different identity: test or document migration instead of assuming an in-place upgrade. Do not promise a routine lower-version MSIX reinstall; define and verify a recovery or forward-fix procedure that respects package identity, version rules, and project data.

Only advertise hardware/model capabilities supported by recorded tests. Large model weights can remain optional downloads; all internal models do not need to be embedded in the MSIX. Review each distributed component's license and required notices before release.

Exit criterion: The advertised packaged workflow succeeds, outputs are inspected, and failures or limitations are resolved or explicitly accepted within the release scope.

## 8. Gate F: Listing, Upload, and Certification

Owner: Product/account owner, supported by release engineering.

- [ ] Complete name, description, category, pricing/availability, and supported languages.
- [ ] Supply screenshots and artwork of the actual WinUI product.
- [ ] Complete age ratings and applicable privacy/support information.
- [ ] State GPU/VRAM expectations, required downloads and disk space, network requirements, and third-party account requirements accurately.
- [ ] Explain any declared restricted capabilities and provide reviewer instructions for setup and a reproducible successful workflow.
- [ ] Review known issues against the advertised features and choose publication timing.
- [ ] Upload the exact reviewed `.msixupload`; retain its hash and Partner Center acceptance/validation results.
- [ ] Submit for certification and record product/submission IDs, version, UTC time, and submission status.
- [ ] Address Microsoft feedback with a newly tracked candidate when package bytes change.
- [ ] Record returned certification and verify Store installation before announcing public availability.

Microsoft's [MSIX submission guide](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/create-app-submission) describes the account, package, listing, and submission stages. Upload acceptance alone is not certification.

## 9. Same-Day Decision

Proceed toward submission today only when Gates A through F are complete through the submission step. Certification and public availability remain external subsequent milestones.

| Finding | Decision |
| --- | --- |
| Correct Store identity, fresh backend-inclusive candidate, passing packaged workflow, complete listing | Upload and submit the approved candidate. |
| Package exists but is still developer-only, lacks backend, or is not finalized | Continue packaging; no upload-ready claim. |
| Azure signing is unintegrated | Determine whether it blocks required test/shipped artifacts; implement and verify that integration where needed. |
| Core generation/setup fails on a clean customer system | Fix and retest; do not submit it as a working advertised feature. |
| Partner Center account or identity is unavailable | Prepare local artifacts and listing materials; submission is externally blocked. |
| Upload accepted but certification pending | Report submitted/pending, not approved or publicly released. |

Suggested execution order: account identity and scope, candidate freeze/backend build, required Azure signing integration, Store staging/finalization, clean-machine acceptance, listing/upload/submission. Listing preparation can proceed while builds and acceptance are underway.

## 10. Evidence and Handoff Template

Keep evidence in the existing release evidence structure, scoped to the candidate. Record paths and hashes rather than embedding credentials or private signing configuration.

```text
Candidate/source commit:
Git dirty state and UTC:
WinUI/backend versions and accelerator profile:
Store identity and version:
Final upload file, byte count, SHA-256:
Backend manifest and payload hash:
Azure signing service/profile and verification references:
Build/test logs and exit results:
Clean-machine OS/hardware and workflow receipts:
Model/runtime inference receipts and inspected output:
WACK report:
Lifecycle/migration/recovery evidence:
SBOM/checksums/notices:
Known issues and release decision:
Partner Center product/submission references:
Upload accepted / submitted / certification / publication status:
Outstanding blockers, owner, and next action:
```

Implementers update their assigned section of `STUDIO_PROGRESS.md`; reviewers distinguish saved results from newly verified evidence. Creating this document does not complete any unchecked gate or change the ongoing model installation task.
