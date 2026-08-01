param(
  [string]$StudioDir = "",
  [switch]$SkipLaunchProbe
)

$ErrorActionPreference = "Stop"

if (-not $StudioDir) {
  $StudioDir = Resolve-Path (Join-Path $PSScriptRoot "../..")
}

function Test-FileExists($Path, [string]$Label) {
  if (Test-Path $Path) {
    Write-Host ("[ok] " + $Label + ": " + $Path) -ForegroundColor Green
    return $true
  }
  Write-Host ("[fail] " + $Label + " missing: " + $Path) -ForegroundColor Red
  return $false
}

function ConvertTo-BooleanSetting($Value, [string]$Name) {
  $normalized = ([string]$Value).Trim().ToLowerInvariant()
  if ($normalized -in @("1", "true", "yes", "on")) { return $true }
  if ($normalized -in @("", "0", "false", "no", "off")) { return $false }
  throw "$Name must be one of 1/0, true/false, yes/no, or on/off."
}

Write-Host "== EDMG Studio clean-machine smoke checklist ==" -ForegroundColor Cyan
Write-Host ("Studio dir: " + $StudioDir)

$failures = 0
$stagedApp = Join-Path $StudioDir "release/staged-app/dist-web/index.html"
$backendManifest = Join-Path $StudioDir "electron-resources/backend/backend-bundle-manifest.json"
$evidenceIndex = Join-Path $StudioDir "release/evidence/release-evidence.json"
$bundleChecksum = Join-Path $StudioDir "release/evidence/bundle-artifacts.sha256.json"
$signatureEvidence = Join-Path $StudioDir "release/evidence/windows-signatures.json"
$requireSigning = ConvertTo-BooleanSetting $env:EDMG_REQUIRE_CODE_SIGNING "EDMG_REQUIRE_CODE_SIGNING"

if (-not (Test-FileExists $backendManifest "Backend bundle manifest")) { $failures += 1 }
if (-not (Test-FileExists $stagedApp "Staged desktop UI")) { $failures += 1 }
if (-not (Test-FileExists $evidenceIndex "Release evidence index")) { $failures += 1 }
if (-not (Test-FileExists $bundleChecksum "Bundle checksum manifest")) { $failures += 1 }

$installerSets = @(
  [pscustomobject]@{ Name = "NSIS"; Directory = (Join-Path $StudioDir "dist"); Payload = "" },
  [pscustomobject]@{ Name = "Inno"; Directory = (Join-Path $StudioDir "dist-inno"); Payload = "payload\win-unpacked.7z" },
  [pscustomobject]@{ Name = "CUDA Inno"; Directory = (Join-Path $StudioDir "dist-inno-cuda"); Payload = "payload\win-unpacked.7z" }
)
$installers = @()
foreach ($set in $installerSets) {
  if (-not (Test-Path -LiteralPath $set.Directory -PathType Container)) { continue }
  $setInstallers = @(
    Get-ChildItem -LiteralPath $set.Directory -File |
      Where-Object { $_.Extension.ToLowerInvariant() -in @(".exe", ".msi") }
  )
  if ($setInstallers.Count -eq 0) { continue }
  $installers += $setInstallers
  Write-Host ("[ok] " + $set.Name + " installer set: " + ($setInstallers.Name -join ", ")) -ForegroundColor Green
  if ($set.Payload) {
    $payloadPath = Join-Path $set.Directory $set.Payload
    if (-not (Test-FileExists $payloadPath ($set.Name + " external payload"))) { $failures += 1 }
  }
}

if ($installers.Count -gt 0) {
  $distChecksum = Join-Path $StudioDir "release/evidence/release-artifacts.sha256.json"
  if (-not (Test-FileExists $distChecksum "Release artifact checksum manifest")) { $failures += 1 }
  foreach ($installer in $installers) {
    $signature = Get-AuthenticodeSignature -LiteralPath $installer.FullName
    if ($signature.Status -eq "Valid") {
      Write-Host ("[ok] Authenticode signature: " + $installer.Name) -ForegroundColor Green
    } elseif ($requireSigning) {
      Write-Host ("[fail] Required Authenticode signature is not valid: " + $installer.Name + " (" + $signature.Status + ")") -ForegroundColor Red
      $failures += 1
    } else {
      Write-Host ("[warn] Installer is not Authenticode-valid: " + $installer.Name + " (" + $signature.Status + ")") -ForegroundColor Yellow
    }
  }
  if ($requireSigning -and -not (Test-FileExists $signatureEvidence "Windows signature evidence")) {
    $failures += 1
  }
} else {
  Write-Host "[warn] No installer artifacts were found. Run pnpm run dist:win or pnpm run dist:win:cuda first." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Manual clean-machine checklist:" -ForegroundColor Cyan
Write-Host "  1. Use a VM or PC without Python, uv, Node, or prior EDMG Studio installs."
Write-Host "  2. Copy the installer set from dist/, dist-inno/, or dist-inno-cuda/ plus release/evidence/."
Write-Host "  3. Install to a Studio Home on any chosen drive with sufficient free space."
Write-Host "  4. Run Full Setup, create a project, upload audio, analyze, plan, render, export."
Write-Host "  5. Verify release/evidence/release-artifacts.sha256.json matches shipped files."
Write-Host "  6. Verify Authenticode evidence in release/evidence/windows-signatures.json."

if (-not $SkipLaunchProbe) {
  Write-Host ""
  Write-Host "Running automated staged-app launch probe..." -ForegroundColor Cyan
  Push-Location $StudioDir
  try {
    & pnpm run validate:packaged-desktop-smoke
    if ($LASTEXITCODE -ne 0) {
      throw "validate:packaged-desktop-smoke failed with exit code $LASTEXITCODE"
    }
    Write-Host "[ok] Staged desktop launch probe passed." -ForegroundColor Green
  } catch {
    Write-Host ("[fail] Staged desktop launch probe failed: " + $_.Exception.Message) -ForegroundColor Red
    $failures += 1
  } finally {
    Pop-Location
  }
}

Write-Host ""
if ($failures -gt 0) {
  Write-Host ("Clean-machine smoke failed with " + $failures + " blocking issue(s).") -ForegroundColor Red
  exit 1
}

Write-Host "Clean-machine smoke checklist passed for available local artifacts." -ForegroundColor Green
exit 0
