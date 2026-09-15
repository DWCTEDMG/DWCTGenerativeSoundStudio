$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")
$manager = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot "manage_winui_package.ps1")
$lifecycle = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot "invoke_msix_lifecycle.ps1")
$capabilities = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot "ui-automation-capabilities.json") | ConvertFrom-Json
$errors = [Collections.Generic.List[string]]::new()
if ($manager -notmatch 'ValidateSet\("Install", "Launch", "Repair", "Rollback", "Uninstall"\)') { $errors.Add("manager actions") }
if ($manager -notmatch 'Add-AppxPackage -Register') { $errors.Add("repair registration") }
if ($manager -notmatch 'ForceUpdateFromAnyVersion') { $errors.Add("rollback downgrade") }
if ($lifecycle -notmatch 'PlanOnly' -or $lifecycle -notmatch 'Assert-NoRegistrationResidue') { $errors.Add("safe lifecycle plan/residue") }
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
