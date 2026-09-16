param(
  [string]$UvExe = "uv",
  [string]$NodeExe = "node",
  [string]$PnpmExe = "pnpm"
)

$ErrorActionPreference = "Stop"
$PinnedUvVersion = "0.11.28"

function Assert-Command($name) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    throw "Missing required command: $name"
  }
}

function Assert-PinnedUv($UvCommand) {
  $output = & $UvCommand --version
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to query uv version using: $UvCommand"
  }
  if ($output -notmatch '^uv\s+(\d+\.\d+\.\d+)') {
    throw "Could not parse uv version output: $output"
  }
  if ($Matches[1] -ne $PinnedUvVersion) {
    throw "Studio release builds require uv $PinnedUvVersion; found $($Matches[1])."
  }
  Write-Host ("[info] uv version OK: " + $Matches[1]) -ForegroundColor Cyan
}

function Invoke-Checked($label, [scriptblock]$action) {
  & $action
  if ($LASTEXITCODE -ne 0) {
    throw ($label + " failed with exit code " + $LASTEXITCODE)
  }
}

function Resolve-BackendPackageDir($PyBackendDir) {
  $candidates = @(
    (Join-Path $PyBackendDir "edmg_studio_backend"),
    (Join-Path $PyBackendDir "src\edmg_studio_backend")
  )

  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }

  $checked = $candidates -join ", "
  throw "Backend package folder not found. Checked: $checked"
}

function Get-BundledFfmpegPath($StudioDir) {
  return Join-Path $StudioDir "electron-resources\bin\ffmpeg.exe"
}

function Ensure-BundledFfmpeg($StudioDir) {
  $bundled = Get-BundledFfmpegPath $StudioDir
  $bundledFfprobe = Join-Path $StudioDir "electron-resources\bin\ffprobe.exe"
  if ((Test-Path $bundled) -and (Test-Path $bundledFfprobe)) {
    Write-Host ("[info] Bundled FFmpeg/FFprobe ready: " + $bundled) -ForegroundColor Cyan
    return $bundled
  }

  $script = Join-Path $StudioDir "packaging\windows\get_ffmpeg.ps1"
  if (-not (Test-Path $script)) {
    throw "Missing FFmpeg staging script: $script"
  }

  Write-Host "[info] Pinned FFmpeg/FFprobe pair missing; staging it now..." -ForegroundColor Yellow
  Invoke-Checked "stage bundled FFmpeg and FFprobe" {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $script -OutDir "./electron-resources/bin"
  }

  if (-not (Test-Path $bundled) -or -not (Test-Path $bundledFfprobe)) {
    throw "Bundled FFmpeg/FFprobe staging failed: $bundled; $bundledFfprobe"
  }

  Write-Host ("[info] Bundled FFmpeg/FFprobe staged: " + $bundled) -ForegroundColor Green
  return $bundled
}

function Check-Port($port, $label) {
  Write-Host ("Port " + $port + " (" + $label + "):") -NoNewline
  $found = $false

  if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
    try {
      $conns = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
      if ($conns) {
        Write-Host " LISTENING" -ForegroundColor Yellow
        foreach ($c in $conns) {
          $pid = $c.OwningProcess
          $pname = ""
          try { $pname = (Get-Process -Id $pid -ErrorAction SilentlyContinue).ProcessName } catch {}
          Write-Host ("  " + $c.LocalAddress + ":" + $c.LocalPort + "  pid=" + $pid + "  " + $pname)
        }
        $found = $true
      }
    } catch {}
  }

  if (-not $found) {
    try {
      $lines = & netstat -ano | Select-String (":$port\s")
      if ($lines) {
        Write-Host " IN USE" -ForegroundColor Yellow
        foreach ($l in $lines) {
          $parts = ($l.ToString() -split "\s+") | Where-Object { $_ -ne "" }
          $pid = $parts[-1]
          $pname = ""
          try { $pname = (Get-Process -Id $pid -ErrorAction SilentlyContinue).ProcessName } catch {}
          Write-Host ("  " + $l.ToString().Trim() + "  proc=" + $pname)
        }
        $found = $true
      }
    } catch {}
  }

  if (-not $found) {
    Write-Host " free" -ForegroundColor Green
  }
}

function Doctor($RepoRoot, $StudioDir, $PyBackendDir, $BackendPkgDir, $BundledFfmpegPath) {
  Write-Host "== Preflight Doctor ==" -ForegroundColor Cyan
  $repoPath = $RepoRoot.Path
  Write-Host ("RepoRoot: " + $repoPath)
  Write-Host ("Path length: " + $repoPath.Length)
  if ($repoPath.Length -gt 160) {
    Write-Host "[warn] Repo path is long. Consider a shorter folder on any drive with sufficient space." -ForegroundColor Yellow
  }

  try {
    $uvv = & $UvExe --version
    Write-Host ("uv: " + $uvv.Trim())
    Write-Host "Python: pinned by repository .python-version and acquired by uv during the frozen release sync"
  } catch {
    Write-Host "[fail] pinned uv is not runnable." -ForegroundColor Red
  }

  try {
    $nv = & $NodeExe --version
    Write-Host ("Node: " + $nv.Trim())
  } catch {
    Write-Host "[warn] node not runnable (UI build will fail)." -ForegroundColor Yellow
  }

  try {
    $pnpmv = & $PnpmExe --version
    Write-Host ("pnpm: " + $pnpmv.Trim())
  } catch {}

  $ff = $env:EDMG_FFMPEG_PATH
  if (-not $ff -and (Test-Path $BundledFfmpegPath)) {
    $ff = $BundledFfmpegPath
  }
  if (-not $ff) { $ff = "ffmpeg" }
  try {
    $ffv = & $ff -version
    Write-Host ("FFmpeg: " + ($ffv | Select-Object -First 1))
  } catch {
    Write-Host "[warn] FFmpeg not found. Internal rendering will rely on PATH or a bundled binary." -ForegroundColor Yellow
  }

  try {
    $driveLetter = $repoPath.Substring(0,1)
    $drive = Get-PSDrive -Name $driveLetter
    $gb = [math]::Round($drive.Free / 1GB, 2)
    Write-Host ("Disk free on " + $driveLetter + ": " + $gb + " GB")
    if ($gb -lt 20) {
      Write-Host "[warn] Low disk space. Video renders + node_modules can be large." -ForegroundColor Yellow
    }
  } catch {}

  Write-Host "== Port checks ==" -ForegroundColor Cyan
  Check-Port 7863 "Studio backend"
  Check-Port 8188 "ComfyUI"
  Check-Port 11434 "Ollama"
  Write-Host "================" -ForegroundColor Cyan
  Write-Host ("Backend package: " + $BackendPkgDir) -ForegroundColor Cyan
}

Assert-Command $PnpmExe
Assert-Command $UvExe
Assert-PinnedUv $UvExe
$env:EDMG_UV = (Get-Command $UvExe).Source

$StudioDir = Resolve-Path (Join-Path $PSScriptRoot "../..")
$RepoRoot = Resolve-Path (Join-Path $StudioDir "../..")
$PyBackendDir = Join-Path $StudioDir "python_backend"

if (-not (Test-Path $StudioDir)) {
  throw "Studio directory not found: $StudioDir"
}
if (-not (Test-Path $PyBackendDir)) {
  throw "Python backend directory not found: $PyBackendDir"
}

$BackendPkgDir = Resolve-BackendPackageDir $PyBackendDir
$BundledFfmpegPath = Get-BundledFfmpegPath $StudioDir
Doctor $RepoRoot $StudioDir $PyBackendDir $BackendPkgDir $BundledFfmpegPath
Write-Host "[info] Release packaging is read-only with respect to project and legacy data. Run migrations explicitly from Studio." -ForegroundColor Cyan
$BundledFfmpegPath = Ensure-BundledFfmpeg $StudioDir

Write-Host "[1/2] Installing UI dependencies from the frozen pnpm lock..."
Push-Location $StudioDir
if (-not (Test-Path "pnpm-lock.yaml")) {
  throw "pnpm-lock.yaml is required for release builds."
}
Invoke-Checked "pnpm install --frozen-lockfile" {
  & $PnpmExe install --frozen-lockfile
}

Write-Host "[2/2] Building and finalizing one candidate-bound Windows release..."
Invoke-Checked "prepare locked DirectML release bundle" { & $PnpmExe run prepare:release-bundle:directml }
Invoke-Checked "release metadata checks" { & $PnpmExe run check:release-metadata }
$stageScript = Join-Path $StudioDir "packaging\windows\stage_winui_msix.ps1"
& powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $stageScript -ReleaseMode production -IncludeProductionBackend -RequireSigning
if ($LASTEXITCODE -ne 0) { throw "Intermediate MSIX staging failed with exit code $LASTEXITCODE" }
$msixMetadataPath = Join-Path $StudioDir "release\winui-msix\winui-msix.json"
$msixMetadata = Get-Content -Raw -LiteralPath $msixMetadataPath | ConvertFrom-Json
$msixPath = Join-Path (Split-Path -Parent $msixMetadataPath) ([string]$msixMetadata.package.fileName)
$candidatePath = Join-Path $StudioDir "release\candidate\release-candidate.json"
$signScript = Join-Path $StudioDir "packaging\windows\sign_release.ps1"
& powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $signScript -StudioDir $StudioDir -ArtifactPaths $msixPath -RequireSigning -CandidateManifest $candidatePath
if ($LASTEXITCODE -ne 0) { throw "MSIX signing failed with exit code $LASTEXITCODE" }
$msixMetadata.package.sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $msixPath).Hash.ToLowerInvariant()
$msixMetadata.distributable = $false
[IO.File]::WriteAllText($msixMetadataPath, (($msixMetadata | ConvertTo-Json -Depth 8) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
$installerScript = Join-Path $StudioDir "packaging\windows\build_winui_installer.ps1"
& powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $installerScript
if ($LASTEXITCODE -ne 0) { throw "Intermediate installer build failed with exit code $LASTEXITCODE" }
$installerMetadataPath = Join-Path $StudioDir "dist-winui\winui-installer.json"
$installerMetadata = Get-Content -Raw -LiteralPath $installerMetadataPath | ConvertFrom-Json
$installerPath = Join-Path (Split-Path -Parent $installerMetadataPath) ([string]$installerMetadata.fileName)
& $signScript -StudioDir $StudioDir -ArtifactPaths @($msixPath, $installerPath) -RequireSigning -CandidateManifest $candidatePath
if ($LASTEXITCODE -ne 0) { throw "Joint final signing and verification failed with exit code $LASTEXITCODE" }
$candidateScript = Join-Path $StudioDir "scripts\release-candidate.mjs"
& $NodeExe $candidateScript attach --manifest $candidatePath --kind msix --artifact $msixPath
if ($LASTEXITCODE -ne 0) { throw "Final MSIX candidate binding failed." }
& $NodeExe $candidateScript attach --manifest $candidatePath --kind installer --artifact $installerPath
if ($LASTEXITCODE -ne 0) { throw "Final installer candidate binding failed." }
$msixMetadata.package.sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $msixPath).Hash.ToLowerInvariant(); $msixMetadata.distributable = $true
$installerMetadata.sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $installerPath).Hash.ToLowerInvariant(); $installerMetadata.msixSha256 = $msixMetadata.package.sha256
[IO.File]::WriteAllText($msixMetadataPath, (($msixMetadata | ConvertTo-Json -Depth 8) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText($installerMetadataPath, (($installerMetadata | ConvertTo-Json -Depth 8) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
& $NodeExe $candidateScript verify-package --manifest $candidatePath --msix-metadata $msixMetadataPath --installer-metadata $installerMetadataPath
if ($LASTEXITCODE -ne 0) { throw "Final package contract validation failed." }
$signatureEvidence = Join-Path $StudioDir "release\evidence\windows-signatures.json"
$timestampEvidence = Join-Path $StudioDir "release\evidence\windows-timestamps.json"
& $NodeExe $candidateScript attach-evidence --manifest $candidatePath --kind signing --reference $signatureEvidence
if ($LASTEXITCODE -ne 0) { throw "Signature evidence binding failed." }
& $NodeExe $candidateScript attach-evidence --manifest $candidatePath --kind timestamp --reference $timestampEvidence
if ($LASTEXITCODE -ne 0) { throw "Timestamp evidence binding failed." }
& $NodeExe $candidateScript verify --manifest $candidatePath --msix $msixPath --installer $installerPath --signing-evidence $signatureEvidence --timestamp-evidence $timestampEvidence --production
if ($LASTEXITCODE -ne 0) { throw "Independent production verification failed." }
Pop-Location

Write-Host "[post] Clean-machine smoke checklist..." -ForegroundColor Cyan
$smokeScript = Join-Path $StudioDir "packaging/windows/smoke_clean_machine.ps1"
if (Test-Path $smokeScript) {
  & powershell -NoProfile -ExecutionPolicy Bypass -File $smokeScript -StudioDir $StudioDir -SkipLaunchProbe
  if ($LASTEXITCODE -ne 0) {
    throw "smoke_clean_machine.ps1 failed with exit code $LASTEXITCODE"
  }
}

Write-Host "Done. Primary WinUI installer: studio/edmg-studio/dist-winui/" -ForegroundColor Green
Write-Host "Staged WinUI package: studio/edmg-studio/release/winui-msix/" -ForegroundColor Cyan
