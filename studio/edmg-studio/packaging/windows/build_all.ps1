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
  if (Test-Path $bundled) {
    Write-Host ("[info] Bundled FFmpeg ready: " + $bundled) -ForegroundColor Cyan
    return $bundled
  }

  $script = Join-Path $StudioDir "packaging\windows\get_ffmpeg.ps1"
  if (-not (Test-Path $script)) {
    throw "Missing FFmpeg staging script: $script"
  }

  Write-Host "[info] Bundled FFmpeg missing; downloading/staging it now..." -ForegroundColor Yellow
  Invoke-Checked "stage bundled FFmpeg" {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $script -OutDir "./electron-resources/bin"
  }

  if (-not (Test-Path $bundled)) {
    throw "Bundled FFmpeg staging failed: $bundled"
  }

  Write-Host ("[info] Bundled FFmpeg staged: " + $bundled) -ForegroundColor Green
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

function Move-ExistingFolder($SourceDir, $DestRoot, $Label) {
  if (-not (Test-Path $SourceDir)) {
    return
  }

  New-Item -ItemType Directory -Force -Path $DestRoot | Out-Null
  $ts = Get-Date -Format "yyyyMMdd_HHmmss"
  $backup = Join-Path $DestRoot ($Label + "_" + $ts)
  Move-Item -Force $SourceDir $backup
  Write-Host ("[info] Moved " + $SourceDir + " -> " + $backup) -ForegroundColor Yellow
}

function Test-ReparsePoint($Path) {
  if (-not (Test-Path $Path)) {
    return $false
  }
  $item = Get-Item -Force $Path
  return (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)
}

function Migrate-LegacyData($RepoRoot, $StudioDir, $PyBackendDir) {
  $DestData = Join-Path $StudioDir "data"
  $MigrationsDir = Join-Path $StudioDir "_legacy_migrations"
  New-Item -ItemType Directory -Force -Path $DestData | Out-Null
  New-Item -ItemType Directory -Force -Path $MigrationsDir | Out-Null

  $LegacyBackendData = Join-Path $PyBackendDir "data"
  if (Test-Path $LegacyBackendData) {
    Write-Host "[info] Found legacy python_backend/data. Migrating into studio/data." -ForegroundColor Yellow
    Copy-Item -Recurse -Force (Join-Path $LegacyBackendData "*") $DestData -ErrorAction SilentlyContinue
    Move-ExistingFolder $LegacyBackendData $MigrationsDir "python_backend_data"
  }

  $LegacyRootData = Join-Path $RepoRoot "data"
  if (Test-Path $LegacyRootData) {
    if (Test-ReparsePoint $LegacyRootData) {
      Write-Host "[info] Repo-root data/ is already a link; leaving it in place." -ForegroundColor Cyan
      return
    }
    Write-Host "[info] Found legacy repo-root data/. Migrating into studio/data." -ForegroundColor Yellow
    Copy-Item -Recurse -Force (Join-Path $LegacyRootData "*") $DestData -ErrorAction SilentlyContinue
    Move-ExistingFolder $LegacyRootData $MigrationsDir "repo_root_data"
    try {
      cmd /c "mklink /J `"$LegacyRootData`" `"$DestData`"" | Out-Null
      Write-Host "[info] Recreated repo-root data/ as a junction to studio/data." -ForegroundColor Yellow
    } catch {
      Write-Host ("[warn] Could not recreate repo-root data junction: " + $_.Exception.Message) -ForegroundColor Yellow
    }
  }
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
Migrate-LegacyData $RepoRoot $StudioDir $PyBackendDir
$BundledFfmpegPath = Ensure-BundledFfmpeg $StudioDir

Write-Host "[1/2] Installing UI dependencies from the frozen pnpm lock..."
Push-Location $StudioDir
if (-not (Test-Path "pnpm-lock.yaml")) {
  throw "pnpm-lock.yaml is required for release builds."
}
Invoke-Checked "pnpm install --frozen-lockfile" {
  & $PnpmExe install --frozen-lockfile
}

Write-Host "[2/2] Building locked DirectML backend and Windows installer..."
Invoke-Checked "pnpm run check:tooling" {
  & $PnpmExe run check:tooling
}
Invoke-Checked "pnpm run dist:win" {
  & $PnpmExe run dist:win
}
Pop-Location

Write-Host "[post] Authenticode signing and verification (credential/requirement gated)..." -ForegroundColor Cyan
$signScript = Join-Path $StudioDir "packaging/windows/sign_release.ps1"
if (Test-Path $signScript) {
  & powershell -NoProfile -ExecutionPolicy Bypass -File $signScript -StudioDir $StudioDir -VerifyOnly
  if ($LASTEXITCODE -ne 0) {
    throw "sign_release.ps1 failed with exit code $LASTEXITCODE"
  }
}

Write-Host "[post] Clean-machine smoke checklist..." -ForegroundColor Cyan
$smokeScript = Join-Path $StudioDir "packaging/windows/smoke_clean_machine.ps1"
if (Test-Path $smokeScript) {
  & powershell -NoProfile -ExecutionPolicy Bypass -File $smokeScript -StudioDir $StudioDir -SkipLaunchProbe
  if ($LASTEXITCODE -ne 0) {
    throw "smoke_clean_machine.ps1 failed with exit code $LASTEXITCODE"
  }
}

Write-Host "Done. Final installer artifacts: studio/edmg-studio/dist/" -ForegroundColor Green
Write-Host "Staged desktop app: studio/edmg-studio/release/staged-app/" -ForegroundColor Cyan
