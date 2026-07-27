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

Write-Host "== EDMG Studio clean-machine smoke checklist ==" -ForegroundColor Cyan
Write-Host ("Studio dir: " + $StudioDir)

$failures = 0
$stagedApp = Join-Path $StudioDir "release/staged-app/dist-web/index.html"
$backendManifest = Join-Path $StudioDir "electron-resources/backend/backend-bundle-manifest.json"
$evidenceIndex = Join-Path $StudioDir "release/evidence/release-evidence.json"
$bundleChecksum = Join-Path $StudioDir "release/evidence/bundle-artifacts.sha256.json"
$distDir = Join-Path $StudioDir "dist"

if (-not (Test-FileExists $backendManifest "Backend bundle manifest")) { $failures += 1 }
if (-not (Test-FileExists $stagedApp "Staged desktop UI")) { $failures += 1 }
if (-not (Test-FileExists $evidenceIndex "Release evidence index")) { $failures += 1 }
if (-not (Test-FileExists $bundleChecksum "Bundle checksum manifest")) { $failures += 1 }

if (Test-Path $distDir) {
  $installers = @(Get-ChildItem -Path $distDir -File | Where-Object { $_.Extension -in @(".exe", ".msi", ".appimage") })
  if ($installers.Count -gt 0) {
    Write-Host ("[ok] Installer artifacts: " + ($installers | ForEach-Object { $_.Name } | Sort-Object | Out-String).Trim()) -ForegroundColor Green
    $distChecksum = Join-Path $StudioDir "release/evidence/release-artifacts.sha256.json"
    if (-not (Test-FileExists $distChecksum "Release artifact checksum manifest")) { $failures += 1 }
  } else {
    Write-Host "[warn] dist/ exists but no installer artifacts were found yet. Run pnpm run dist:win on a build host first." -ForegroundColor Yellow
  }
} else {
  Write-Host "[warn] dist/ is missing. Installer-level smoke requires a completed dist:win build." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Manual clean-machine checklist:" -ForegroundColor Cyan
Write-Host "  1. Use a VM or PC without Python, uv, Node, or prior EDMG Studio installs."
Write-Host "  2. Copy the installer from studio/edmg-studio/dist/ plus release/evidence/."
Write-Host "  3. Install to a Studio Home on any chosen drive with sufficient free space."
Write-Host "  4. Run Full Setup, create a project, upload audio, analyze, plan, render, export."
Write-Host "  5. Verify release/evidence/release-artifacts.sha256.json matches shipped files."
Write-Host "  6. Optional signing pass: packaging/windows/sign_release.ps1 after setting EDMG_CODE_SIGN_CERT."

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
