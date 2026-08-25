param(
  [string]$StudioDir = "",
  [string]$OutputDirectory = "",
  [switch]$RequireSigning,
  [string]$StoreIdentityFile = "",
  [string]$SideloadPublisher = "",
  [switch]$IncludeProductionBackend
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
$effectiveManifestPath = $manifestPath

if ($StoreIdentityFile -and $SideloadPublisher) {
  throw "StoreIdentityFile and SideloadPublisher are mutually exclusive."
}

if ($StoreIdentityFile) {
  if (-not [IO.Path]::IsPathRooted($StoreIdentityFile)) {
    $StoreIdentityFile = Join-Path (Get-Location) $StoreIdentityFile
  }
  if (-not (Test-Path -LiteralPath $StoreIdentityFile -PathType Leaf)) {
    throw "StoreIdentityFile was not found: $StoreIdentityFile"
  }

  try {
    $storeIdentity = Get-Content -Raw -LiteralPath $StoreIdentityFile | ConvertFrom-Json
  } catch {
    throw "StoreIdentityFile is not valid JSON: $($_.Exception.Message)"
  }

  foreach ($property in @("identityName", "publisher", "version")) {
    $value = [string]$storeIdentity.$property
    if ([string]::IsNullOrWhiteSpace($value) -or $value -match "(?i)<|>|replace|todo") {
      throw "StoreIdentityFile.$property must contain the exact value from Partner Center, not a placeholder."
    }
  }
  if ([string]$storeIdentity.publisher -notmatch "^CN=") {
    throw "StoreIdentityFile.publisher must be the complete Partner Center publisher distinguished name (CN=...)."
  }
  $versionParts = @(([string]$storeIdentity.version).Split("."))
  $validVersion = $versionParts.Count -eq 4 -and $versionParts[3] -eq "0"
  if ($validVersion) {
    for ($index = 0; $index -lt $versionParts.Count; $index++) {
      $numericPart = 0
      if (-not [int]::TryParse($versionParts[$index], [ref]$numericPart) -or
          $numericPart -lt 0 -or
          $numericPart -gt 65535 -or
          ($index -eq 0 -and $numericPart -eq 0)) {
        $validVersion = $false
        break
      }
    }
  }
  if (-not $validVersion) {
    throw "StoreIdentityFile.version must be a Windows Store version with a zero fourth component."
  }

  $sourceManifest.Package.Identity.Name = [string]$storeIdentity.identityName
  $sourceManifest.Package.Identity.Publisher = [string]$storeIdentity.publisher
  $sourceManifest.Package.Identity.Version = [string]$storeIdentity.version
}

if ($SideloadPublisher) {
  if ($SideloadPublisher -notmatch "^CN=") {
    throw "SideloadPublisher must be the complete signing-certificate subject distinguished name (CN=...)."
  }
  $sourceManifest.Package.Identity.Publisher = $SideloadPublisher
}

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

if ($StoreIdentityFile -or $SideloadPublisher) {
  $manifestVariant = if ($StoreIdentityFile) { "Store" } else { "Sideload" }
  $effectiveManifestPath = Join-Path $buildDirectory "Package.$manifestVariant.appxmanifest"
  $settings = [System.Xml.XmlWriterSettings]::new()
  $settings.Encoding = [Text.UTF8Encoding]::new($false)
  $settings.Indent = $true
  $writer = [System.Xml.XmlWriter]::Create($effectiveManifestPath, $settings)
  try {
    $sourceManifest.Save($writer)
  } finally {
    $writer.Dispose()
  }
}

$backendPayloadPath = ""
if ($IncludeProductionBackend) {
  $backendPayloadPath = Join-Path $StudioDir "electron-resources\backend"
  if (-not (Test-Path -LiteralPath $backendPayloadPath -PathType Container)) {
    throw "Production backend payload is missing: $backendPayloadPath"
  }
  $node = Get-Command "node" -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $node) {
    throw "node is required to validate the production backend payload."
  }
  & $node.Source (Join-Path $StudioDir "scripts\check-backend-release-manifest.mjs") $backendPayloadPath
  if ($LASTEXITCODE -ne 0) {
    throw "The production backend release-manifest/hash gate failed with exit code $LASTEXITCODE."
  }
}

$dotnet = Get-Command "dotnet" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $dotnet) {
  throw "dotnet was not found. Install the required .NET SDK before staging WinUI."
}

Write-Host "[stage_winui_msix] Building packaged WinUI Release/x64 MSIX..." -ForegroundColor Cyan
$buildArguments = @(
  "build",
  $projectPath,
  "--configuration", "Release",
  "-p:Platform=x64",
  "-p:RuntimeIdentifier=win-x64",
  "-p:GenerateAppxPackageOnBuild=true",
  "-p:WindowsAppSDKSelfContained=true",
  "-p:AppxPackageSigningEnabled=false",
  "-p:AppxBundle=Never",
  "-p:PublishTrimmed=false",
  "-p:DebugType=None",
  "-p:DebugSymbols=false",
  "-p:AppxPackageDir=$buildDirectory\",
  "-p:EdmgPackageManifestPath=$effectiveManifestPath"
)
if ($IncludeProductionBackend) {
  $buildArguments += "-p:EdmgPackagedBackendPath=$backendPayloadPath"
  $buildArguments += "-p:RequireEdmgPackagedBackend=true"
}
if ($StoreIdentityFile) {
  $buildArguments += "-p:UapAppxPackageBuildMode=CI"
}
$buildArguments += "-warnaserror"
& $dotnet.Source @buildArguments
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
  $requiredPayloadEntries = @(
    "bin/ffmpeg.exe",
    "bin/ffprobe.exe"
  )
  if ($IncludeProductionBackend) {
    $requiredPayloadEntries += @(
      "backend/edmg-studio-backend.exe",
      "backend/backend-bundle-manifest.json"
    )
  }
  $archiveEntryNames = @($archive.Entries | ForEach-Object { $_.FullName.Replace("\", "/") })
  foreach ($requiredEntry in $requiredPayloadEntries) {
    if ($requiredEntry -cnotin $archiveEntryNames) {
      throw "The generated WinUI MSIX is missing required payload entry: $requiredEntry"
    }
  }
  if ($IncludeProductionBackend -and
      -not ($archiveEntryNames | Where-Object { $_ -like "backend/_internal/*" } | Select-Object -First 1)) {
    throw "The generated WinUI MSIX is missing the production backend _internal runtime."
  }
  if ($IncludeProductionBackend) {
    foreach ($unsupportedEntry in @(
      "backend/_internal/tcl86t.dll",
      "backend/_internal/tk86t.dll"
    )) {
      if ($unsupportedEntry -cin $archiveEntryNames) {
        throw "The generated WinUI MSIX contains an unsupported malformed Tcl/Tk runtime file: $unsupportedEntry"
      }
    }
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
Get-ChildItem -LiteralPath $OutputDirectory -File -ErrorAction SilentlyContinue |
  Where-Object { $_.Extension -in @(".msix", ".msixupload", ".appxupload") } |
  Remove-Item -Force

$artifact = $candidates[0]
if ($StoreIdentityFile) {
  $uploadCandidates = @(
    Get-ChildItem -LiteralPath $buildDirectory -File -Recurse |
      Where-Object { $_.Extension -in @(".msixupload", ".appxupload") }
  )
  if ($uploadCandidates.Count -ne 1) {
    throw "Expected exactly one Store upload artifact under $buildDirectory, found $($uploadCandidates.Count)."
  }
  $artifact = $uploadCandidates[0]
}

$stagedName = if ($StoreIdentityFile) {
  "{0}_{1}_{2}{3}" -f $expectedName, $expectedVersion, $expectedArchitecture, $artifact.Extension
} else {
  "{0}_{1}_{2}.msix" -f $expectedName, $expectedVersion, $expectedArchitecture
}
$stagedPath = Join-Path $OutputDirectory $stagedName
Copy-Item -LiteralPath $artifact.FullName -Destination $stagedPath -Force

if ($StoreIdentityFile) {
  if ($RequireSigning) {
    throw "Store upload artifacts are re-signed by Microsoft Store; do not request local Authenticode signing."
  }
  Write-Host "[stage_winui_msix] Store upload artifact is intentionally unsigned; Microsoft Store re-signs submitted MSIX/AppX packages." -ForegroundColor Yellow
} else {
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
