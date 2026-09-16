# MSIX lifecycle qualification

Run only on a disposable Windows VM using trusted, retained packages. The operator must provide Appx PowerShell cmdlets, a certificate trusted by the VM, an interactive desktop for launch checks, and two correctly versioned MSIX files for upgrade/rollback. The harness never creates or bypasses a signature.

Preview without changing package registration:

```powershell
.\invoke_msix_lifecycle.ps1 -Scenario Full -MsixPath C:\packages\old.msix -UpgradeMsixPath C:\packages\new.msix -PreviousMsixPath C:\packages\old.msix -PlanOnly
```

Remove `-PlanOnly` only on the disposable qualification machine. `Full` performs clean uninstall, install, registration/integrity and launch checks, upgrade, repair/re-register, explicit rollback, uninstall, and registration/locator residue checks. Use `-SkipLaunch` only when documenting that interactive launch was not exercised. Evidence is written to `qualification-evidence\msix-lifecycle.json`.

## Evidence contract

The harness writes schema v3 evidence bound to a canonical candidate ID and x64 package identity. Eight receipts are mandatory: clean install, first-run canonical native workflow, project persistence/data retention, autosave recovery, upgrade, repair, rollback, and uninstall. Harness-observable package operations are recorded directly. Interactive workflow/persistence/recovery results must be supplied as retained real observations through `-ReceiptInput`; each import must bind the candidate ID, tested MSIX SHA256, exact identity/version, execution timestamp, and a retained immutable evidence file plus SHA256; absent observations remain `not-run`, making the overall result `incomplete`. `-DataPolicy retain|remove` records and checks the selected uninstall outcome.

Real execution requires signed trusted packages and a disposable Windows machine. `-PlanOnly` documents intent only and cannot qualify a candidate. Validate with `node scripts/validate-lifecycle-evidence.mjs <file> --require-passed --candidate-id <id>`.


Bind each tested package before execution (the identity JSON contains `name`, `publisher`, and four-part `version`):

```powershell
node scripts/release-candidate.mjs attach-lifecycle --manifest release/candidate/release-candidate.json --role install --artifact C:\packages\old.msix --identity C:\evidence\old-identity.json
node scripts/release-candidate.mjs attach-lifecycle --manifest release/candidate/release-candidate.json --role upgrade --artifact C:\packages\new.msix --identity C:\evidence\new-identity.json
node scripts/release-candidate.mjs attach-lifecycle --manifest release/candidate/release-candidate.json --role rollback --artifact C:\packages\old.msix --identity C:\evidence\old-identity.json
```

`-ReceiptInput` uses `{ "provenance": { "candidateId", "testedPackageSha256", "packageIdentity", "executedAt", "evidenceReference", "evidenceSha256" }, "receipts": { ... } }`. The evidence reference is resolved beside the receipt file and must exist with the declared hash. Receipts older than 30 days, future-dated receipts, handwritten assertions without immutable evidence, or candidate/package identity/hash mismatches are rejected.
