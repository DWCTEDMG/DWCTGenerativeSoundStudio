param(
  [string]$OutDir = "./electron-resources/bin"
)

$ErrorActionPreference = "Stop"

$StudioDir = Resolve-Path (Join-Path $PSScriptRoot "../..")
if ([IO.Path]::IsPathRooted($OutDir)) {
  $OutDirAbs = [IO.Path]::GetFullPath($OutDir)
} else {
  $OutDirAbs = [IO.Path]::GetFullPath((Join-Path $StudioDir $OutDir))
}
New-Item -ItemType Directory -Force -Path $OutDirAbs | Out-Null

$Node = Get-Command "node.exe" -ErrorAction Stop
$StagingScript = Join-Path $StudioDir "scripts/stage-media-tools.mjs"
if (-not (Test-Path -LiteralPath $StagingScript -PathType Leaf)) {
  throw "Pinned media-tool staging script is missing: $StagingScript"
}

& $Node.Source $StagingScript --out-dir $OutDirAbs
if ($LASTEXITCODE -ne 0) {
  throw "Pinned FFmpeg/FFprobe staging failed with exit code $LASTEXITCODE"
}

foreach ($Binary in @("ffmpeg.exe", "ffprobe.exe")) {
  $BinaryPath = Join-Path $OutDirAbs $Binary
  if (-not (Test-Path -LiteralPath $BinaryPath -PathType Leaf)) {
    throw "Pinned media-tool staging did not produce $BinaryPath"
  }
}

Write-Host "OK: staged checksum-verified FFmpeg and FFprobe into $OutDirAbs" -ForegroundColor Green
