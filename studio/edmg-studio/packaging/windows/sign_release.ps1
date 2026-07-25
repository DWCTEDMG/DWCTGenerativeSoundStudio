param(
  [string]$StudioDir = "",
  [string[]]$ArtifactPaths = @()
)

$ErrorActionPreference = "Stop"

if (-not $StudioDir) {
  $StudioDir = Resolve-Path (Join-Path $PSScriptRoot "../..")
}

function Resolve-SignableArtifacts($Root, $ExplicitPaths) {
  if ($ExplicitPaths -and $ExplicitPaths.Count -gt 0) {
    return @($ExplicitPaths | ForEach-Object { Resolve-Path $_ })
  }

  $distDir = Join-Path $Root "dist"
  if (-not (Test-Path $distDir)) {
    return @()
  }

  return @(
    Get-ChildItem -Path $distDir -File |
      Where-Object { $_.Extension -in @(".exe", ".msi", ".appimage") } |
      ForEach-Object { $_.FullName }
  )
}

$cert = [string]$env:EDMG_CODE_SIGN_CERT
$password = [string]$env:EDMG_CODE_SIGN_PASSWORD
$timestampUrl = if ($env:EDMG_CODE_SIGN_TIMESTAMP_URL) { $env:EDMG_CODE_SIGN_TIMESTAMP_URL } else { "http://timestamp.digicert.com" }
$artifacts = Resolve-SignableArtifacts $StudioDir $ArtifactPaths

if (-not $cert) {
  Write-Host "[sign_release] Skipping code signing because EDMG_CODE_SIGN_CERT is not set." -ForegroundColor Yellow
  Write-Host "[sign_release] Configure a Windows certificate thumbprint or PFX path to enable signing." -ForegroundColor Yellow
  exit 0
}

if ($artifacts.Count -eq 0) {
  Write-Host "[sign_release] No installer artifacts found under studio/edmg-studio/dist/." -ForegroundColor Yellow
  exit 0
}

$signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if (-not $signtool) {
  Write-Host "[sign_release] signtool.exe is not on PATH. Install the Windows SDK signing tools or run this on a signing host." -ForegroundColor Red
  exit 2
}

Write-Host "[sign_release] Signing hook enabled for certificate: $cert" -ForegroundColor Cyan
Write-Host "[sign_release] Timestamp URL: $timestampUrl" -ForegroundColor Cyan

foreach ($artifact in $artifacts) {
  Write-Host "[sign_release] Would sign: $artifact" -ForegroundColor Yellow
}

Write-Host "[sign_release] Stub only: no files were modified in this repository slice." -ForegroundColor Yellow
Write-Host "[sign_release] Replace this script with signtool.exe invocations once signing credentials are available." -ForegroundColor Yellow

if ($password) {
  Write-Host "[sign_release] EDMG_CODE_SIGN_PASSWORD is configured." -ForegroundColor Cyan
}

exit 0
