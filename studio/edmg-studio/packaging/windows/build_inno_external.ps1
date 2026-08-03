param(
  [switch]$SkipElectronDirBuild,
  [string]$PnpmExe = "pnpm",
  [string]$IsccExe = "",
  [string]$SevenZipExe = "",
  [string]$OutDir = "dist-inno",
  [switch]$ReusePayloadArchive
)

$ErrorActionPreference = "Stop"

function Invoke-Checked($Label, [scriptblock]$Action) {
  & $Action
  if ($LASTEXITCODE -ne 0) {
    throw ($Label + " failed with exit code " + $LASTEXITCODE)
  }
}

function Invoke-WindowsSigning($StudioRoot, $Artifacts, $Phase) {
  $signScript = Join-Path $StudioRoot "packaging\windows\sign_release.ps1"
  if (-not (Test-Path -LiteralPath $signScript -PathType Leaf)) {
    throw "Windows signing script not found: $signScript"
  }
  foreach ($artifact in @($Artifacts)) {
    if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) { continue }
    Write-Host ("[sign] " + $Phase + ": " + $artifact) -ForegroundColor Cyan
    & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $signScript `
      -StudioDir $StudioRoot -ArtifactPaths $artifact
    if ($LASTEXITCODE -ne 0) {
      throw "$Phase signing failed with exit code $LASTEXITCODE"
    }
  }
}

function Get-FullPath($Path) {
  return [IO.Path]::GetFullPath($Path)
}

function Assert-ChildPath($Root, $Path, $Label) {
  $rootFull = Get-FullPath $Root
  $pathFull = Get-FullPath $Path
  if (-not $rootFull.EndsWith([IO.Path]::DirectorySeparatorChar)) {
    $rootFull = $rootFull + [IO.Path]::DirectorySeparatorChar
  }
  if (-not $pathFull.StartsWith($rootFull, [StringComparison]::OrdinalIgnoreCase)) {
    throw ($Label + " is outside expected directory. Root: " + $rootFull + " Path: " + $pathFull)
  }
}

function Remove-DirectoryIfExists($Path, $SafeRoot, $Label) {
  if (-not (Test-Path $Path)) {
    return
  }
  Assert-ChildPath $SafeRoot $Path $Label
  Remove-Item -Recurse -Force -LiteralPath $Path
}

function Resolve-Iscc($RequestedPath) {
  if ($RequestedPath) {
    if (Test-Path $RequestedPath) {
      return (Resolve-Path $RequestedPath).Path
    }
    throw "Inno Setup compiler not found: $RequestedPath"
  }

  $programRoots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}) |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
    Select-Object -Unique
  $preferredCandidates = @(
    $programRoots | ForEach-Object { Join-Path $_ "Inno Setup 7\ISCC.exe" }
    if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 7\ISCC.exe" }
  )
  foreach ($candidate in $preferredCandidates) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }

  $command = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
  if ($command) {
    return $command.Source
  }

  $legacyCandidates = @(
    $programRoots | ForEach-Object { Join-Path $_ "Inno Setup 6\ISCC.exe" }
    if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe" }
  )
  foreach ($candidate in $legacyCandidates) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }

  return ""
}

function Resolve-SevenZip($RequestedPath, $Root) {
  if ($RequestedPath) {
    if (Test-Path $RequestedPath) {
      return (Resolve-Path $RequestedPath).Path
    }
    throw "7-Zip executable not found: $RequestedPath"
  }

  foreach ($name in @("7z.exe", "7za.exe", "7zr.exe")) {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($command) {
      return $command.Source
    }
  }

  $programRoots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}) |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
    Select-Object -Unique
  $candidates = @(
    $programRoots | ForEach-Object { Join-Path $_ "7-Zip\7z.exe" }
    if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "Programs\7-Zip\7z.exe" }
  )
  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }

  $builderCache = Join-Path $Root ".cache\electron-builder"
  if (Test-Path $builderCache) {
    $cached = Get-ChildItem -Path $builderCache -Recurse -File -Filter "7za.exe" -ErrorAction SilentlyContinue |
      Sort-Object FullName |
      Select-Object -First 1
    if ($cached) {
      return $cached.FullName
    }
  }

  return ""
}

function Escape-InnoValue($Value) {
  return ($Value -replace '"', '""')
}

function Get-Sha256Hex($Path) {
  $stream = [IO.File]::OpenRead($Path)
  try {
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
      $hashBytes = $sha256.ComputeHash($stream)
    } finally {
      $sha256.Dispose()
    }
  } finally {
    $stream.Dispose()
  }
  return [BitConverter]::ToString($hashBytes).Replace("-", "").ToLowerInvariant()
}

$StudioDir = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$PackageJsonPath = Join-Path $StudioDir "package.json"
$PackageJson = Get-Content -Raw -Path $PackageJsonPath | ConvertFrom-Json
$Version = [string]$PackageJson.version
$ProductName = [string]$PackageJson.build.productName
if (-not $ProductName) { $ProductName = "EDMG Studio" }
$AppId = [string]$PackageJson.build.appId
if (-not $AppId) { $AppId = "com.dwct.edmgstudio" }

if ([IO.Path]::IsPathRooted($OutDir)) {
  $OutDirAbs = Get-FullPath $OutDir
} else {
  $OutDirAbs = Get-FullPath (Join-Path $StudioDir $OutDir)
}

$DistDir = Join-Path $StudioDir "dist"
$WinUnpackedDir = Join-Path $DistDir "win-unpacked"
$PayloadRoot = Join-Path $OutDirAbs "payload"
$PayloadArchive = Join-Path $PayloadRoot "win-unpacked.7z"
$GeneratedIss = Join-Path $OutDirAbs "edmg-studio-external.iss"
$IconPath = Join-Path $StudioDir "electron-resources\app-icon.ico"

if (-not $SkipElectronDirBuild) {
  Push-Location $StudioDir
  try {
    Invoke-Checked "pnpm run build" { & $PnpmExe run build }
    Invoke-Checked "pnpm run prepare:release-bundle" { & $PnpmExe run prepare:release-bundle }
    Invoke-Checked "pnpm run release:stage-desktop" { & $PnpmExe run release:stage-desktop }
    Invoke-Checked "pnpm run check:release-metadata" { & $PnpmExe run check:release-metadata }
    Invoke-Checked "electron-builder directory package" {
      & node scripts/run-electron-builder.mjs --dir --x64 -c.directories.app=release/staged-app
    }
  } finally {
    Pop-Location
  }
}

if (-not (Test-Path $WinUnpackedDir)) {
  throw "Electron unpacked app not found: $WinUnpackedDir. Run without -SkipElectronDirBuild first."
}

$PayloadSignables = @(
  (Join-Path $WinUnpackedDir "EDMG Studio.exe"),
  (Join-Path $WinUnpackedDir "resources\backend\edmg-studio-backend.exe"),
  (Join-Path $WinUnpackedDir "resources\backend\edmg-hf-bucket-helper.exe")
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
Invoke-WindowsSigning $StudioDir $PayloadSignables "pre-archive payload"

New-Item -ItemType Directory -Force -Path $OutDirAbs | Out-Null
foreach ($previousSetup in Get-ChildItem -LiteralPath $OutDirAbs -File -Filter "EDMG-Studio-Setup-*.exe") {
  Assert-ChildPath $OutDirAbs $previousSetup.FullName "previous setup executable"
  Remove-Item -Force -LiteralPath $previousSetup.FullName
}
if (-not $ReusePayloadArchive) {
  Remove-DirectoryIfExists $PayloadRoot $OutDirAbs "payload directory"
}
New-Item -ItemType Directory -Force -Path $PayloadRoot | Out-Null

$ResolvedSevenZip = Resolve-SevenZip $SevenZipExe $StudioDir
if (-not $ResolvedSevenZip) {
  throw "7-Zip was not found. Install 7-Zip or rerun with -SevenZipExe <path-to-7z.exe>."
}

if ($ReusePayloadArchive) {
  if (-not (Test-Path -LiteralPath $PayloadArchive -PathType Leaf)) {
    throw "Reusable payload archive not found: $PayloadArchive"
  }
  Write-Host ("[info] Validating reusable external payload archive: " + $PayloadArchive) -ForegroundColor Cyan
  Invoke-Checked "7-Zip reusable payload validation" { & $ResolvedSevenZip t $PayloadArchive }
} else {
  Write-Host ("[info] Creating external payload archive: " + $PayloadArchive) -ForegroundColor Cyan
  Push-Location $WinUnpackedDir
  try {
    Invoke-Checked "7-Zip payload archive" {
      & $ResolvedSevenZip a -t7z -mx=0 -mmt=on $PayloadArchive ".\*"
    }
  } finally {
    Pop-Location
  }
}
$ExtendedWinUnpackedDir = if ($WinUnpackedDir.StartsWith("\\")) {
  "\\?\UNC\" + $WinUnpackedDir.Substring(2)
} else {
  "\\?\" + $WinUnpackedDir
}
[Int64]$PayloadExpandedSize = 0
foreach ($payloadFile in [IO.Directory]::EnumerateFiles($ExtendedWinUnpackedDir, "*", [IO.SearchOption]::AllDirectories)) {
  $PayloadExpandedSize += [IO.FileInfo]::new($payloadFile).Length
}
$PayloadSha256 = Get-Sha256Hex $PayloadArchive
Write-Host ("[info] Payload SHA-256: " + $PayloadSha256) -ForegroundColor Cyan
Write-Host ("[info] Payload expanded size: " + $PayloadExpandedSize + " bytes") -ForegroundColor Cyan

$OutputBaseFilename = "EDMG-Studio-Setup-" + $Version
$issLines = @(
  "; Generated by packaging/windows/build_inno_external.ps1. Do not edit this generated copy.",
  "",
  "#if VER < EncodeVer(7,0,0)",
  "  #error Inno Setup 7 or newer is required for extended-length payload paths",
  "#endif",
  "",
  "[Setup]",
  "AppId={{faa597b4-33fe-5e5f-81a9-4db216782ca3}",
  ("AppName={0}" -f (Escape-InnoValue $ProductName)),
  ("AppVersion={0}" -f (Escape-InnoValue $Version)),
  "AppPublisher=Dwct",
  "AppPublisherURL=https://github.com/HIMOI890/DWCTGenerativeSoundStudio",
  "AppSupportURL=https://github.com/HIMOI890/DWCTGenerativeSoundStudio/issues",
  ("DefaultDirName={{localappdata}}\Programs\{0}" -f (Escape-InnoValue $ProductName)),
  ("DefaultGroupName={0}" -f (Escape-InnoValue $ProductName)),
  ("UninstallDisplayIcon={{app}}\{0}.exe" -f (Escape-InnoValue $ProductName)),
  ("OutputDir={0}" -f (Escape-InnoValue $OutDirAbs)),
  ("OutputBaseFilename={0}" -f (Escape-InnoValue $OutputBaseFilename)),
  "Compression=none",
  "SolidCompression=no",
  "ArchiveExtraction=enhanced/nopassword",
  "WizardStyle=modern",
  "PrivilegesRequired=lowest",
  "DisableProgramGroupPage=yes",
  "CloseApplications=yes",
  ("AppMutex={0}" -f (Escape-InnoValue $AppId))
)

if (Test-Path $IconPath) {
  $issLines += ("SetupIconFile={0}" -f (Escape-InnoValue $IconPath))
}

$issLines += @(
  "",
  "[Dirs]",
  'Name: "{app}"',
  "",
  "[InstallDelete]",
  'Type: filesandordirs; Name: "{app}\resources\backend"',
  "",
  "[Files]",
  ('Source: "{{src}}\payload\win-unpacked.7z"; DestDir: "{{app}}"; ExternalSize: {0}; Hash: "{1}"; Flags: external extractarchive recursesubdirs createallsubdirs ignoreversion' -f $PayloadExpandedSize, $PayloadSha256),
  "",
  "[Icons]",
  'Name: "{group}\EDMG Studio"; Filename: "{app}\EDMG Studio.exe"; WorkingDir: "{app}"',
  'Name: "{userdesktop}\EDMG Studio"; Filename: "{app}\EDMG Studio.exe"; WorkingDir: "{app}"; Tasks: desktopicon',
  "",
  "[Tasks]",
  'Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked',
  "",
  "[Run]",
  'Filename: "{app}\EDMG Studio.exe"; Description: "Launch EDMG Studio"; Flags: nowait postinstall skipifsilent'
)

Set-Content -Path $GeneratedIss -Value $issLines -Encoding UTF8
Write-Host ("[info] Wrote Inno script: " + $GeneratedIss) -ForegroundColor Cyan

$ResolvedIscc = Resolve-Iscc $IsccExe
if (-not $ResolvedIscc) {
  Write-Host "[warn] Inno Setup compiler (ISCC.exe) was not found." -ForegroundColor Yellow
  Write-Host "[warn] Install Inno Setup 7 or newer, or rerun with -IsccExe <path-to-ISCC.exe>." -ForegroundColor Yellow
  Write-Host ("[warn] External payload is ready at: " + $PayloadRoot) -ForegroundColor Yellow
  throw "Cannot compile Inno installer because ISCC.exe is missing."
}

Invoke-Checked "Inno Setup compile" {
  & $ResolvedIscc $GeneratedIss
}

$SetupPath = Join-Path $OutDirAbs ($OutputBaseFilename + ".exe")
if (-not (Test-Path -LiteralPath $SetupPath -PathType Leaf)) {
  throw "Inno Setup completed but the setup executable is missing: $SetupPath"
}
Invoke-WindowsSigning $StudioDir @($SetupPath) "post-compile setup"

Write-Host "Done. Inno external-payload release:" -ForegroundColor Green
Write-Host ("  Setup:   " + $SetupPath) -ForegroundColor Green
Write-Host ("  Payload: " + $PayloadRoot) -ForegroundColor Green
Write-Host "Ship the setup EXE and payload directory together." -ForegroundColor Cyan
