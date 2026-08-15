param(
  [Parameter(Mandatory = $true)]
  [ValidateSet("Install", "Launch", "Uninstall")]
  [string]$Action,
  [string]$InstallRoot = "",
  [string]$MsixPath = ""
)

$ErrorActionPreference = "Stop"

$packageName = "ED2F9BCD-A580-4603-8A17-A7AD5FF6D451"
$applicationId = "App"
$locatorDirectory = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "EDMG Studio"
$locatorPath = Join-Path $locatorDirectory "installation.json"

function Get-NormalizedDirectoryPath {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  if (-not [IO.Path]::IsPathRooted($Path)) {
    throw "InstallRoot must be an absolute path."
  }
  return [IO.Path]::GetFullPath($Path).TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
  )
}

function Write-Utf8FileAtomically {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [Parameter(Mandatory = $true)]
    [string]$Content
  )

  $directory = [IO.Path]::GetDirectoryName($Path)
  New-Item -ItemType Directory -Force -Path $directory | Out-Null
  $temporaryPath = Join-Path $directory (".{0}.{1}.tmp" -f [IO.Path]::GetFileName($Path), [Guid]::NewGuid())
  try {
    [IO.File]::WriteAllText($temporaryPath, $Content, [Text.UTF8Encoding]::new($false))
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
      [IO.File]::Replace($temporaryPath, $Path, $null)
    } else {
      [IO.File]::Move($temporaryPath, $Path)
    }
  } finally {
    Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
  }
}

function Read-LocatorInstallRoot {
  if (-not (Test-Path -LiteralPath $locatorPath -PathType Leaf)) {
    return $null
  }
  try {
    $locator = Get-Content -Raw -LiteralPath $locatorPath | ConvertFrom-Json
    if ($locator.schemaVersion -ne 1 -or [string]::IsNullOrWhiteSpace([string]$locator.installRoot)) {
      return $null
    }
    return Get-NormalizedDirectoryPath ([string]$locator.installRoot)
  } catch {
    return $null
  }
}

function Remove-MatchingLocator {
  param(
    [Parameter(Mandatory = $true)]
    [string]$ExpectedInstallRoot
  )

  $locatedRoot = Read-LocatorInstallRoot
  if ($null -ne $locatedRoot -and
      [string]::Equals($locatedRoot, $ExpectedInstallRoot, [StringComparison]::OrdinalIgnoreCase)) {
    Remove-Item -LiteralPath $locatorPath -Force
    if ((Test-Path -LiteralPath $locatorDirectory -PathType Container) -and
        -not (Get-ChildItem -LiteralPath $locatorDirectory -Force | Select-Object -First 1)) {
      Remove-Item -LiteralPath $locatorDirectory -Force
    }
  }
}

function Get-InstalledPackage {
  $packages = @(Get-AppxPackage -Name $packageName -ErrorAction SilentlyContinue)
  if ($packages.Count -eq 0) {
    return $null
  }
  return $packages | Sort-Object Version -Descending | Select-Object -First 1
}

function Assert-BackendBundle {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Root
  )

  if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
    throw "InstallRoot does not exist: $Root"
  }

  $backendDirectory = Join-Path $Root "resources\backend"
  $backendExecutable = Join-Path $backendDirectory "edmg-studio-backend.exe"
  $backendManifestPath = Join-Path $backendDirectory "backend-bundle-manifest.json"
  $backendInternalDirectory = Join-Path $backendDirectory "_internal"
  foreach ($requiredPath in @($backendExecutable, $backendManifestPath, $backendInternalDirectory)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
      throw "Installed backend bundle is incomplete: $requiredPath"
    }
  }

  try {
    $manifest = Get-Content -Raw -LiteralPath $backendManifestPath | ConvertFrom-Json
  } catch {
    throw "Installed backend bundle manifest is invalid JSON: $($_.Exception.Message)"
  }
  if ($manifest.ok -ne $true -or
      $manifest.platform -cne "win32" -or
      $manifest.bundleLayout -cne "onedir" -or
      $manifest.backendEntryPoint -cne "edmg-studio-backend.exe" -or
      [string]$manifest.acceleratorProfile -notin @("cpu", "directml", "cuda") -or
      @($manifest.bundleEntries).Count -eq 0) {
    throw "Installed backend bundle manifest does not describe a supported Windows onedir bundle."
  }
}

function Assert-WinUiMsix {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  if (-not [IO.Path]::IsPathRooted($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "MsixPath must identify an existing absolute .msix file."
  }
  if ([IO.Path]::GetExtension($Path) -cne ".msix") {
    throw "MsixPath must have a .msix extension."
  }

  $signature = Get-AuthenticodeSignature -LiteralPath $Path
  if ($signature.Status -ne [Management.Automation.SignatureStatus]::Valid) {
    throw "The WinUI MSIX must have a valid Authenticode signature before installation (status: $($signature.Status))."
  }

  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $archive = [IO.Compression.ZipFile]::OpenRead($Path)
  try {
    $entry = $archive.Entries | Where-Object { $_.FullName -eq "AppxManifest.xml" } | Select-Object -First 1
    if (-not $entry) {
      throw "The WinUI MSIX does not contain AppxManifest.xml."
    }
    $reader = [IO.StreamReader]::new($entry.Open())
    try {
      [xml]$manifest = $reader.ReadToEnd()
    } finally {
      $reader.Dispose()
    }
  } finally {
    $archive.Dispose()
  }

  if ([string]$manifest.Package.Identity.Name -cne $packageName -or
      [string]$manifest.Package.Identity.ProcessorArchitecture -cne "x64" -or
      [string]$manifest.Package.Applications.Application.Id -cne $applicationId) {
    throw "The supplied MSIX is not the expected EDMG Studio WinUI x64 package."
  }
}

switch ($Action) {
  "Install" {
    $normalizedRoot = Get-NormalizedDirectoryPath $InstallRoot
    $normalizedMsixPath = [IO.Path]::GetFullPath($MsixPath)
    Assert-BackendBundle $normalizedRoot
    Assert-WinUiMsix $normalizedMsixPath

    $previousLocator = $null
    if (Test-Path -LiteralPath $locatorPath -PathType Leaf) {
      $previousLocator = Get-Content -Raw -LiteralPath $locatorPath
    }
    $locator = [ordered]@{
      schemaVersion = 1
      installRoot = $normalizedRoot
      updatedAt = (Get-Date).ToUniversalTime().ToString("o")
    }
    Write-Utf8FileAtomically $locatorPath (($locator | ConvertTo-Json -Depth 4) + [Environment]::NewLine)

    try {
      Add-AppxPackage -Path $normalizedMsixPath -ForceApplicationShutdown
    } catch {
      if ($null -ne $previousLocator) {
        Write-Utf8FileAtomically $locatorPath $previousLocator
      } else {
        Remove-MatchingLocator $normalizedRoot
      }
      throw
    }
    Write-Host "EDMG Studio WinUI package installed."
  }

  "Launch" {
    $package = Get-InstalledPackage
    if (-not $package) {
      throw "EDMG Studio WinUI is not installed for the current user."
    }
    $applicationTarget = "shell:AppsFolder\$($package.PackageFamilyName)!$applicationId"
    Start-Process -FilePath "explorer.exe" -ArgumentList $applicationTarget
  }

  "Uninstall" {
    $normalizedRoot = Get-NormalizedDirectoryPath $InstallRoot
    $package = Get-InstalledPackage
    if ($package) {
      Remove-AppxPackage -Package $package.PackageFullName
    }
    Remove-MatchingLocator $normalizedRoot
  }
}
