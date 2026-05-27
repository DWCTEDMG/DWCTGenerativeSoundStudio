param(
  [string]$OutDir = "./electron-resources/bin"
)

$ErrorActionPreference = "Stop"

$StudioDir = Resolve-Path (Join-Path $PSScriptRoot "../..")
$OutDirAbs = Resolve-Path (Join-Path $StudioDir $OutDir) -ErrorAction SilentlyContinue
if (-not $OutDirAbs) {
  $OutDirAbs = Join-Path $StudioDir $OutDir
  New-Item -ItemType Directory -Force -Path $OutDirAbs | Out-Null
}

$zipUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
$tmpZip = Join-Path $env:TEMP "ffmpeg-release-essentials.zip"

$pathFfmpeg = Get-Command "ffmpeg.exe" -ErrorAction SilentlyContinue
if ($pathFfmpeg -and (Test-Path $pathFfmpeg.Source)) {
  Copy-Item -Force $pathFfmpeg.Source (Join-Path $OutDirAbs "ffmpeg.exe")
  Write-Host "OK: staged ffmpeg.exe from PATH into $OutDirAbs" -ForegroundColor Green
  exit 0
}

Write-Host "Downloading FFmpeg essentials from gyan.dev..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$downloaded = $false
for ($attempt = 1; $attempt -le 3; $attempt++) {
  try {
    Invoke-WebRequest -Uri $zipUrl -OutFile $tmpZip
    $downloaded = $true
    break
  } catch {
    if ($attempt -eq 3) {
      throw
    }
    Write-Host ("Download failed; retrying (" + $attempt + "/3): " + $_.Exception.Message) -ForegroundColor Yellow
    Start-Sleep -Seconds (2 * $attempt)
  }
}

if (-not $downloaded) {
  throw "FFmpeg download did not complete."
}

$tmpDir = Join-Path $env:TEMP "ffmpeg_essentials_extract"
if (Test-Path $tmpDir) { Remove-Item -Recurse -Force $tmpDir }
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null

Write-Host "Extracting..."
Expand-Archive -Path $tmpZip -DestinationPath $tmpDir -Force

$ffmpegExe = Get-ChildItem -Path $tmpDir -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
if (-not $ffmpegExe) { throw "ffmpeg.exe not found after extraction" }

Copy-Item -Force $ffmpegExe.FullName (Join-Path $OutDirAbs "ffmpeg.exe")
Write-Host "OK: staged ffmpeg.exe into $OutDirAbs" -ForegroundColor Green
