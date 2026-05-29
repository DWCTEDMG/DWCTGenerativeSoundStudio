param(
  [string]$EnvFile = "deployment/nvidia/.env.local",
  [string]$Registry = "nvcr.io"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Read-EnvFileValue {
  param(
    [string]$Path,
    [string]$Name
  )
  if (-not (Test-Path -LiteralPath $Path)) {
    return ""
  }
  $pattern = "^\s*$([regex]::Escape($Name))\s*=\s*(.*)\s*$"
  foreach ($line in Get-Content -LiteralPath $Path) {
    if ($line -match $pattern) {
      return ($Matches[1].Trim().Trim('"').Trim("'"))
    }
  }
  return ""
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repoRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw "docker was not found on PATH. Install/start Docker Desktop first."
}

$key = [string]$env:NGC_API_KEY
if ([string]::IsNullOrWhiteSpace($key)) {
  $key = Read-EnvFileValue -Path $EnvFile -Name "NGC_API_KEY"
}

if ([string]::IsNullOrWhiteSpace($key)) {
  throw "NGC_API_KEY is not configured. Put it in $EnvFile or set `$env:NGC_API_KEY for this shell."
}

Write-Host "[nvidia-ngc] Logging in to $Registry with masked NGC_API_KEY"
$key | docker login $Registry -u '$oauthtoken' --password-stdin
Write-Host "[nvidia-ngc] Login complete"
