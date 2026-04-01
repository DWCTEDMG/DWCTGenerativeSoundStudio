param(
  [switch]$IncludeComfy,
  [string]$ComfyUrl = "http://127.0.0.1:8188"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path

$env:EDMG_ENABLE_LIVE_STILL_SMOKE = "1"
if ($IncludeComfy) {
  $env:EDMG_ENABLE_LIVE_COMFY_STILL_SMOKE = "1"
  $env:EDMG_LIVE_COMFYUI_URL = $ComfyUrl
} else {
  Remove-Item Env:EDMG_ENABLE_LIVE_COMFY_STILL_SMOKE -ErrorAction SilentlyContinue
  Remove-Item Env:EDMG_LIVE_COMFYUI_URL -ErrorAction SilentlyContinue
}

Push-Location $repoRoot
try {
  pytest -q tests/test_studio_live_still_smoke.py
} finally {
  Pop-Location
}
