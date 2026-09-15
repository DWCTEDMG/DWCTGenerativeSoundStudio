# MSIX lifecycle qualification

Run only on a disposable Windows VM using trusted, retained packages. The operator must provide Appx PowerShell cmdlets, a certificate trusted by the VM, an interactive desktop for launch checks, and two correctly versioned MSIX files for upgrade/rollback. The harness never creates or bypasses a signature.

Preview without changing package registration:

```powershell
.\invoke_msix_lifecycle.ps1 -Scenario Full -MsixPath C:\packages\old.msix -UpgradeMsixPath C:\packages\new.msix -PreviousMsixPath C:\packages\old.msix -PlanOnly
```

Remove `-PlanOnly` only on the disposable qualification machine. `Full` performs clean uninstall, install, registration/integrity and launch checks, upgrade, repair/re-register, explicit rollback, uninstall, and registration/locator residue checks. Use `-SkipLaunch` only when documenting that interactive launch was not exercised. Evidence is written to `qualification-evidence\msix-lifecycle.json`.
