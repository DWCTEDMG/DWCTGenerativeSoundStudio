param(
  [string]$KitSdkRoot = $env:OMNI_KIT_SDK_ROOT,
  [string]$BackendUrl = "http://127.0.0.1:8000",
  [switch]$ListExtensions
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$kitRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$appConfig = Resolve-Path (Join-Path $kitRoot "apps\edmg.nvidia.studio.kit")
$extensionsRoot = Resolve-Path (Join-Path $kitRoot "extensions")
$sampleStage = Resolve-Path (Join-Path $kitRoot "sample_projects\audio_reactive_stage\stage.usda")
$sampleScenePlan = Resolve-Path (Join-Path $kitRoot "sample_projects\audio_reactive_stage\scene_plan.json")

if ([string]::IsNullOrWhiteSpace($KitSdkRoot)) {
  throw "KitSdkRoot was not provided. Pass -KitSdkRoot or set OMNI_KIT_SDK_ROOT."
}

$resolvedSdkRoot = Resolve-Path -LiteralPath $KitSdkRoot
$kitExe = Join-Path $resolvedSdkRoot "kit.exe"
if (-not (Test-Path -LiteralPath $kitExe)) {
  throw "kit.exe was not found at $kitExe"
}

$args = @(
  $appConfig.Path,
  "--ext-folder",
  $extensionsRoot.Path,
  "--/edmg/nvidia/backend_url=$BackendUrl",
  "--/edmg/nvidia/sample_stage=$($sampleStage.Path)",
  "--/edmg/nvidia/sample_scene_plan=$($sampleScenePlan.Path)"
)

if ($ListExtensions) {
  $args += "--list-exts"
}

Write-Host "[edmg-kit] SDK: $resolvedSdkRoot"
Write-Host "[edmg-kit] App: $($appConfig.Path)"
Write-Host "[edmg-kit] Backend: $BackendUrl"
Write-Host "[edmg-kit] Sample stage: $($sampleStage.Path)"

& $kitExe @args
