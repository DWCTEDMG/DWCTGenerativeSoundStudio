$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")
$manager = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot "manage_winui_package.ps1")
$lifecycle = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot "invoke_msix_lifecycle.ps1")
$finalizer = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot "build_all.ps1")
$stage = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot "stage_winui_msix.ps1")
$installer = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot "build_winui_installer.ps1")
$verifier = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot "verify_artifact_signatures.ps1")
$capabilities = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot "ui-automation-capabilities.json") | ConvertFrom-Json
$errors = [Collections.Generic.List[string]]::new()
if ($manager -notmatch 'ValidateSet\("Install", "Launch", "Repair", "Rollback", "Uninstall"\)') { $errors.Add("manager actions") }
if ($manager -notmatch 'Add-AppxPackage -Register') { $errors.Add("repair registration") }
if ($manager -notmatch 'ForceUpdateFromAnyVersion') { $errors.Add("rollback downgrade") }
if ($lifecycle -notmatch 'PlanOnly' -or $lifecycle -notmatch 'Invoke-InstallerUninstall' -or $lifecycle -notmatch 'candidate\.artifacts\.msix' -or $lifecycle -notmatch 'Get-CandidateOwnedProcesses') { $errors.Add("installer lifecycle qualification") }
if ($stage -match 'candidateScript attach' -or $installer -match 'sign_release\.ps1') { $errors.Add("intermediate stages must not finalize") }
if ($finalizer -notmatch 'windows-timestamps\.json' -or $finalizer -notmatch 'ArtifactPaths @\(\$msixPath, \$installerPath\)' -or $finalizer -notmatch '\-\-production') { $errors.Add("joint production finalization") }
if ($verifier -notmatch 'Get-AuthenticodeSignature' -or $verifier -notmatch '/tw' -or $verifier -notmatch 'X509Chain' -or $verifier -notmatch 'ExpectedSignerSubject') { $errors.Add("independent signature verifier") }
if ($capabilities.ciDefault -ne "capability-check-only" -or $capabilities.resultStates -notcontains "not-run-capability-missing") { $errors.Add("UI automation gating") }
Get-ChildItem -LiteralPath (Join-Path $root ".github\workflows") -File | ForEach-Object {
  $lineNumber = 0
  Get-Content -LiteralPath $_.FullName | ForEach-Object {
    $lineNumber++
    if ($_ -match 'uses:\s*[^\s]+@([^\s#]+)' -and $Matches[1] -notmatch '^[a-f0-9]{40}$') { $errors.Add("unpinned action $($_.Name):$lineNumber") }
  }
}
if ($errors.Count) { throw "Packaging foundation checks failed: $($errors -join ', ')" }
Write-Host "Packaging foundation static checks passed; no package operations were performed."
