param(
  [string]$StudioDir = "",
  [string]$OutputDirectory = "",
  [switch]$RequireSigning
)

$ErrorActionPreference = "Stop"

if (-not $StudioDir) {
  $StudioDir = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
} else {
  $StudioDir = (Resolve-Path $StudioDir).Path
}

$repositoryRoot = (Resolve-Path (Join-Path $StudioDir "../..")).Path
$winUiDirectory = Join-Path $repositoryRoot "studio\edmg-studio-winui"
$projectPath = Join-Path $winUiDirectory "EdmgStudio.WinUI.csproj"
$manifestPath = Join-Path $winUiDirectory "Package.appxmanifest"
$signingScript = Join-Path $PSScriptRoot "sign_release.ps1"

foreach ($requiredFile in @($projectPath, $manifestPath, $signingScript)) {
  if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
    throw "Required WinUI packaging input was not found: $requiredFile"
  }
}

if (-not $OutputDirectory) {
  $OutputDirectory = Join-Path $StudioDir "release\winui-msix"
} elseif (-not [IO.Path]::IsPathRooted($OutputDirectory)) {
  $OutputDirectory = Join-Path $StudioDir $OutputDirectory
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$buildDirectory = Join-Path $OutputDirectory "build"

[xml]$sourceManifest = Get-Content -Raw -LiteralPath $manifestPath
$sourceIdentity = $sourceManifest.Package.Identity
$expectedName = [string]$sourceIdentity.Name
$expectedPublisher = [string]$sourceIdentity.Publisher
$expectedVersion = [string]$sourceIdentity.Version
$expectedArchitecture = "x64"
$expectedApplicationId = [string]$sourceManifest.Package.Applications.Application.Id
if (-not $expectedName -or -not $expectedPublisher -or -not $expectedVersion -or -not $expectedApplicationId) {
  throw "Package.appxmanifest must define Identity Name, Publisher, Version, and Application Id."
}

Remove-Item -LiteralPath $buildDirectory -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $buildDirectory | Out-Null

$dotnet = Get-Command "dotnet" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $dotnet) {
  throw "dotnet was not found. Install the required .NET SDK before staging WinUI."
}

Write-Host "[stage_winui_msix] Building packaged WinUI Release/x64 MSIX..." -ForegroundColor Cyan
& $dotnet.Source build $projectPath `
--configuration Release `
-p:Platform=x64 `
  -p:RuntimeIdentifier=win-x64 `
  -p:GenerateAppxPackageOnBuild=true `
  -p:WindowsAppSDKSelfContained=true `
  -p:AppxPackageSigningEnabled=false `
  -p:AppxBundle=Never `
  -p:PublishTrimmed=false `
  -p:DebugType=None `
  -p:DebugSymbols=false `
  "-p:AppxPackageDir=$buildDirectory\" `
  -warnaserror
if ($LASTEXITCODE -ne 0) {
  throw "WinUI Release/x64 MSIX build failed with exit code $LASTEXITCODE."
}

$candidates = @(
  Get-ChildItem -LiteralPath $buildDirectory -Filter "EdmgStudio.WinUI_*.msix" -File -Recurse |
    Where-Object {
      $_.Name -notmatch "\.msix(upload|sym)$" -and
      $_.DirectoryName -notmatch "[\\/]Dependencies([\\/]|$)"
    }
)
if ($candidates.Count -ne 1) {
  throw "Expected exactly one WinUI .msix under $buildDirectory, found $($candidates.Count)."
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($candidates[0].FullName)
try {
  $manifestEntry = $archive.Entries |
    Where-Object { $_.FullName -eq "AppxManifest.xml" } |
    Select-Object -First 1
  if (-not $manifestEntry) {
    throw "The generated WinUI MSIX does not contain AppxManifest.xml."
  }
  $reader = [IO.StreamReader]::new($manifestEntry.Open())
  try {
    [xml]$packageManifest = $reader.ReadToEnd()
  } finally {
    $reader.Dispose()
  }
} finally {
  $archive.Dispose()
}

$identity = $packageManifest.Package.Identity
$actualName = [string]$identity.Name
$actualPublisher = [string]$identity.Publisher
$actualVersion = [string]$identity.Version
$actualArchitecture = [string]$identity.ProcessorArchitecture
$actualApplicationId = [string]$packageManifest.Package.Applications.Application.Id
if ($actualName -cne $expectedName -or
    $actualPublisher -cne $expectedPublisher -or
    $actualVersion -cne $expectedVersion -or
    $actualArchitecture -cne $expectedArchitecture -or
    $actualApplicationId -cne $expectedApplicationId) {
  throw ("Generated WinUI MSIX identity mismatch. Expected {0}, {1}, {2}, {3}, {4}; got {5}, {6}, {7}, {8}, {9}." -f
    $expectedName, $expectedPublisher, $expectedVersion, $expectedArchitecture, $expectedApplicationId,
    $actualName, $actualPublisher, $actualVersion, $actualArchitecture, $actualApplicationId)
}

$frameworkDependencies = @(
  $packageManifest.SelectNodes(
    "//*[local-name()='Dependencies']/*[local-name()='PackageDependency']"
  )
)
if ($frameworkDependencies.Count -gt 0) {
  $dependencyNames = @(
    $frameworkDependencies |
     ForEach-Object { [string]$_.Name } |
     Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
  )
  $dependencySummary = if ($dependencyNames.Count -gt 0) {
    $dependencyNames -join ", "
  } else {
    "unnamed framework package"
  }
  throw (
    "Generated WinUI MSIX is not self-contained; AppxManifest.xml declares PackageDependency: " +
    $dependencySummary
  )
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
Get-ChildItem -LiteralPath $OutputDirectory -Filter "*.msix" -File -ErrorAction SilentlyContinue |
  Remove-Item -Force
$stagedName = "{0}_{1}_{2}.msix" -f $expectedName, $expectedVersion, $expectedArchitecture
$stagedPath = Join-Path $OutputDirectory $stagedName
Copy-Item -LiteralPath $candidates[0].FullName -Destination $stagedPath -Force

$signingArguments = @{
  StudioDir = $StudioDir
  ArtifactPaths = @($stagedPath)
}
if ($RequireSigning) {
  $signingArguments.RequireSigning = $true
}
& $signingScript @signingArguments
if ($LASTEXITCODE -ne 0) {
  throw "WinUI MSIX signing failed with exit code $LASTEXITCODE."
}

$sha256 = [Security.Cryptography.SHA256]::Create()
try {
  $stream = [IO.File]::OpenRead($stagedPath)
  try {
    $hash = ([BitConverter]::ToString($sha256.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
  } finally {
    $stream.Dispose()
  }
} finally {
  $sha256.Dispose()
}

$metadata = [ordered]@{
  schemaVersion = 1
  createdAt = (Get-Date).ToUniversalTime().ToString("o")
  package = [ordered]@{
    fileName = [IO.Path]::GetFileName($stagedPath)
    name = $expectedName
    publisher = $expectedPublisher
    version = $expectedVersion
    architecture = $expectedArchitecture
    applicationId = $expectedApplicationId
    windowsAppSdkDeployment = "self-contained"
    sha256 = $hash
  }
}
$metadataPath = Join-Path $OutputDirectory "winui-msix.json"
[IO.File]::WriteAllText(
  $metadataPath,
  (($metadata | ConvertTo-Json -Depth 8) + [Environment]::NewLine),
  [Text.UTF8Encoding]::new($false)
)

Write-Host ("[stage_winui_msix] Staged: " + $stagedPath) -ForegroundColor Green
Write-Host ("[stage_winui_msix] Metadata: " + $metadataPath) -ForegroundColor Green
