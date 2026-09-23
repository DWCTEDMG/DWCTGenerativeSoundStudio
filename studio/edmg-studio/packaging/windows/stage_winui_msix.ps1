param(
  [string]$StudioDir = "",
  [string]$OutputDirectory = "",
  [switch]$RequireSigning,
  [string]$StoreIdentityFile = "",
  [string]$SideloadPublisher = "",
  [switch]$IncludeProductionBackend,
  [switch]$AllowBackendlessPackage,
  [ValidateSet("developer", "production", "store")]
  [string]$ReleaseMode = "developer",
  [string]$CandidateManifest = "",
  [string]$Vst3HostPath = "",
  [string]$Vst3ScannerPath = ""
)

$ErrorActionPreference = "Stop"
if ($AllowBackendlessPackage -and ($ReleaseMode -ne "developer" -or $IncludeProductionBackend)) {
  throw "Backendless packages are only explicit developer diagnostics."
}
if (-not $AllowBackendlessPackage) { $IncludeProductionBackend = $true }

function Get-SigningCertificateSubject([string]$Reference, [string]$Root) {
  if ([string]::IsNullOrWhiteSpace($Reference)) {
    throw "RequireSigning needs EDMG_CODE_SIGN_CERT to identify a PFX/P12 file or certificate thumbprint."
  }

  $trimmed = $Reference.Trim()
  $fileCandidate = if ([IO.Path]::IsPathRooted($trimmed)) { $trimmed } else { Join-Path $Root $trimmed }
  if (Test-Path -LiteralPath $fileCandidate -PathType Leaf) {
    if ([IO.Path]::GetExtension($fileCandidate).ToLowerInvariant() -notin @(".pfx", ".p12")) {
      throw "EDMG_CODE_SIGN_CERT file references must use the .pfx or .p12 extension."
    }
    try {
      $certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::new(
        $fileCandidate,
        [string]$env:EDMG_CODE_SIGN_PASSWORD,
        [Security.Cryptography.X509Certificates.X509KeyStorageFlags]::DefaultKeySet
      )
      return $certificate.Subject
    } catch {
      throw "The configured signing certificate could not be opened: $($_.Exception.Message)"
    } finally {
      if ($certificate) { $certificate.Dispose() }
    }
  }

  $thumbprint = ($trimmed -replace "\s", "").ToUpperInvariant()
  if ($thumbprint -notmatch "^[A-F0-9]{40}$") {
    throw "EDMG_CODE_SIGN_CERT must be an existing PFX/P12 file or a SHA1 certificate thumbprint."
  }
  foreach ($storePath in @("Cert:\CurrentUser\My", "Cert:\LocalMachine\My")) {
    $certificate = Get-Item -LiteralPath (Join-Path $storePath $thumbprint) -ErrorAction SilentlyContinue
    if ($certificate) { return $certificate.Subject }
  }
  throw "EDMG_CODE_SIGN_CERT was not found in the current-user or local-machine certificate store."
}

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
$candidateScript = Join-Path $StudioDir "scripts\release-candidate.mjs"
$storeValidator = Join-Path $StudioDir "scripts\validate-store-submission.mjs"
if (-not $CandidateManifest) {
  $CandidateManifest = Join-Path $StudioDir "release\candidate\release-candidate.json"
} elseif (-not [IO.Path]::IsPathRooted($CandidateManifest)) {
  $CandidateManifest = Join-Path $StudioDir $CandidateManifest
}
$CandidateManifest = [IO.Path]::GetFullPath($CandidateManifest)
if (-not $Vst3HostPath) { $Vst3HostPath = [string]$env:EDMG_VST3_HOST_PATH }
if ([string]::IsNullOrWhiteSpace($Vst3HostPath)) { throw "Vst3HostPath or EDMG_VST3_HOST_PATH must point to the clean-built EdmgStudio.Vst3Host.exe." }
$Vst3HostPath = [IO.Path]::GetFullPath($Vst3HostPath)
if (-not (Test-Path -LiteralPath $Vst3HostPath -PathType Leaf)) { throw "Native VST3 host was not found: $Vst3HostPath" }
if (-not $Vst3ScannerPath) { $Vst3ScannerPath = [string]$env:EDMG_VST3_SCANNER_PATH }
if ([string]::IsNullOrWhiteSpace($Vst3ScannerPath)) { throw "Vst3ScannerPath or EDMG_VST3_SCANNER_PATH must point to the clean-built EdmgStudio.Vst3Scanner.exe." }
$Vst3ScannerPath = [IO.Path]::GetFullPath($Vst3ScannerPath)
if (-not (Test-Path -LiteralPath $Vst3ScannerPath -PathType Leaf)) { throw "Native VST3 scanner was not found: $Vst3ScannerPath" }

foreach ($requiredFile in @($projectPath, $manifestPath, $signingScript, $candidateScript, $storeValidator)) {
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
  if ($ReleaseMode -ne "store") { throw "StoreIdentityFile requires -ReleaseMode store." }
  if (-not [IO.Path]::IsPathRooted($StoreIdentityFile)) {
    $StoreIdentityFile = Join-Path (Get-Location) $StoreIdentityFile
  }
  if (-not (Test-Path -LiteralPath $StoreIdentityFile -PathType Leaf)) {
    throw "StoreIdentityFile was not found: $StoreIdentityFile"
  }
  & node $storeValidator $StoreIdentityFile
  if ($LASTEXITCODE -ne 0) { throw "Store submission metadata validation failed." }

  try {
    $storeIdentity = Get-Content -Raw -LiteralPath $StoreIdentityFile | ConvertFrom-Json
  } catch {
    throw "StoreIdentityFile is not valid JSON: $($_.Exception.Message)"
  }

  foreach ($property in @("identityName", "publisher", "version", "displayName", "publisherDisplayName")) {
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
  $sourceManifest.Package.Properties.DisplayName = [string]$storeIdentity.displayName
  $sourceManifest.Package.Properties.PublisherDisplayName = [string]$storeIdentity.publisherDisplayName
}

if ($ReleaseMode -eq "production" -and -not $RequireSigning) {
  throw "Production mode requires -RequireSigning."
}
if ($ReleaseMode -ne "developer" -and -not $IncludeProductionBackend) {
  throw "$ReleaseMode mode requires -IncludeProductionBackend."
}
if ($RequireSigning -and -not $StoreIdentityFile -and -not $SideloadPublisher) {
  $SideloadPublisher = if ($env:EDMG_ARTIFACT_SIGNING_METADATA) {
    [string]$sourceManifest.Package.Identity.Publisher
  } else { Get-SigningCertificateSubject ([string]$env:EDMG_CODE_SIGN_CERT) $StudioDir }
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
if ($expectedPublisher -cne "CN=Driftwoodcraftthing, O=Driftwoodcraftthing, STREET=1815 Sterling Avenue, L=Cincinnati, S=Ohio, C=US, PostalCode=45239") {
  throw "Package publisher must match the permanent Driftwoodcraftthing signing identity."
}
$expectedVersion = [string]$sourceIdentity.Version
$expectedArchitecture = "x64"
$expectedApplicationId = [string]$sourceManifest.Package.Applications.Application.Id
if (-not $expectedName -or -not $expectedPublisher -or -not $expectedVersion -or -not $expectedApplicationId) {
  throw "Package.appxmanifest must define Identity Name, Publisher, Version, and Application Id."
}

if ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($buildDirectory)) -ne $OutputDirectory) { throw "Unsafe build directory." }
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

$node = Get-Command "node" -ErrorAction Stop | Select-Object -First 1
$candidateArguments = @(
  "create", "--manifest", $CandidateManifest, "--mode", $ReleaseMode,
  "--package-name", $expectedName, "--package-publisher", $expectedPublisher,
  "--package-version", $expectedVersion, "--application-id", $expectedApplicationId,
  "--vst3-host", $Vst3HostPath, "--vst3-scanner", $Vst3ScannerPath
)
if ($IncludeProductionBackend) { $candidateArguments += @("--backend-manifest", (Join-Path $backendPayloadPath "backend-bundle-manifest.json")) }
if ($StoreIdentityFile) { $candidateArguments += @("--store-metadata", $StoreIdentityFile) }
& $node.Source $candidateScript @candidateArguments
if ($LASTEXITCODE -ne 0) { throw "Release candidate provenance creation failed." }
$candidate = Get-Content -Raw -LiteralPath $CandidateManifest | ConvertFrom-Json
$candidateId = [string]$candidate.candidateId
if ($IncludeProductionBackend) {
  & $node.Source $candidateScript bind-backend --manifest $CandidateManifest --backend-manifest (Join-Path $backendPayloadPath "backend-bundle-manifest.json")
  if ($LASTEXITCODE -ne 0) { throw "Backend candidate binding failed." }
  $candidate = Get-Content -Raw -LiteralPath $CandidateManifest | ConvertFrom-Json
}
$candidatePayloadPath = Join-Path $buildDirectory "release-candidate.json"
Copy-Item -LiteralPath $CandidateManifest -Destination $candidatePayloadPath -Force

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
  "-p:EdmgPackageManifestPath=$effectiveManifestPath",
  "-p:EdmgReleaseCandidatePath=$candidatePayloadPath",
  "-p:EdmgVst3HostPath=$Vst3HostPath",
  "-p:EdmgVst3ScannerPath=$Vst3ScannerPath"
)
if ($AllowBackendlessPackage) { $buildArguments += "-p:EdmgAllowBackendlessPackage=true" }
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
    "bin/ffprobe.exe",
    "release-candidate.json",
    "EdmgStudio.Vst3Host.exe",
    "EdmgStudio.Vst3Scanner.exe",
    "EdmgStudio.Vst3Host.THIRD-PARTY-NOTICES.txt"
  )
  if ($IncludeProductionBackend) {
    $requiredPayloadEntries += @(
      "backend/edmg-studio-backend.exe",
      "backend/backend-bundle-manifest.json",
      "backend/_internal/python312.dll",
      "backend/_internal/edmg_studio_backend/services/engine_package_manifests.json",
      "bin/FFmpeg-LICENSE.txt",
      "bin/FFmpeg-SOURCE.txt"
    )
  }
  $archiveEntryNames = @($archive.Entries | ForEach-Object { $_.FullName.Replace("\", "/") })
  $signingMaterial = @($archiveEntryNames | Where-Object { $_ -match '(?i)(\.pfx|\.p12|\.cer|_TemporaryKey\.)$' })
  if ($signingMaterial.Count -gt 0) {
    throw "The generated WinUI MSIX contains signing material: $($signingMaterial -join ', ')"
  }
  foreach ($requiredEntry in $requiredPayloadEntries) {
    if ($requiredEntry -cnotin $archiveEntryNames) {
      throw "The generated WinUI MSIX is missing required payload entry: $requiredEntry"
    }
  }
  $hostEntry = $archive.Entries | Where-Object { $_.FullName.Replace("\", "/") -ceq "EdmgStudio.Vst3Host.exe" } | Select-Object -First 1
  $hostStream = $hostEntry.Open()
  $hostHasher = [Security.Cryptography.SHA256]::Create()
  try { $packagedHostHash = ([BitConverter]::ToString($hostHasher.ComputeHash($hostStream))).Replace("-", "").ToLowerInvariant() }
  finally { $hostHasher.Dispose(); $hostStream.Dispose() }
  if ($packagedHostHash -cne [string]$candidate.candidateCore.nativeVst3Host.sha256) {
    throw "Packaged VST3 host hash does not match release-candidate provenance."
  }
  $scannerEntry = $archive.Entries | Where-Object { $_.FullName.Replace("\", "/") -ceq "EdmgStudio.Vst3Scanner.exe" } | Select-Object -First 1
  $scannerStream = $scannerEntry.Open()
  $scannerHasher = [Security.Cryptography.SHA256]::Create()
  try { $packagedScannerHash = ([BitConverter]::ToString($scannerHasher.ComputeHash($scannerStream))).Replace("-", "").ToLowerInvariant() }
  finally { $scannerHasher.Dispose(); $scannerStream.Dispose() }
  if ($packagedScannerHash -cne [string]$candidate.candidateCore.nativeVst3Scanner.sha256) {
    throw "Packaged VST3 scanner hash does not match release-candidate provenance."
  }
  if ($IncludeProductionBackend -and
      -not ($archiveEntryNames | Where-Object { $_ -like "backend/_internal/*" } | Select-Object -First 1)) {
    throw "The generated WinUI MSIX is missing the production backend _internal runtime."
  }
  if ($IncludeProductionBackend) {
    $bundleManifest = Get-Content -Raw -LiteralPath (Join-Path $backendPayloadPath "backend-bundle-manifest.json") | ConvertFrom-Json
    $entryMap = @{}
    foreach ($entry in $archive.Entries) { $entryMap[$entry.FullName.Replace("\", "/")] = $entry }
    foreach ($file in @($bundleManifest.bundleEntries | Where-Object { $_.type -eq "file" })) {
      $entry = $entryMap["backend/" + $file.path]
      if (-not $entry -or $entry.Length -ne $file.size) { throw "Packaged backend inventory mismatch: $($file.path)" }
      $stream = $entry.Open()
      $hasher = [Security.Cryptography.SHA256]::Create()
      try { $entryHash = ([BitConverter]::ToString($hasher.ComputeHash($stream))).Replace("-", "").ToLowerInvariant() }
      finally { $hasher.Dispose(); $stream.Dispose() }
      if ($entryHash -cne $file.sha256) { throw "Packaged backend hash mismatch: $($file.path)" }
    }
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
  if ($RequireSigning) { throw "Store upload artifacts are re-signed by Microsoft Store; do not request local Authenticode signing." }
  Write-Host "[stage_winui_msix] Store upload artifact is intentionally unsigned; Microsoft Store re-signs submitted packages." -ForegroundColor Yellow
} elseif ($RequireSigning) {
  Write-Host "[stage_winui_msix] Production bytes are intermediate; build_all.ps1 signs and finalizes both artifacts together." -ForegroundColor Yellow
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
  schemaVersion = 2
  createdAt = (Get-Date).ToUniversalTime().ToString("o")
  candidateId = $candidateId
  releaseMode = $ReleaseMode
  distributable = $false
  backend = if ($IncludeProductionBackend) { $candidate.candidateCore.backend } else { $null }
  nativeVst3Host = $candidate.candidateCore.nativeVst3Host
  nativeVst3Scanner = $candidate.candidateCore.nativeVst3Scanner
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
Write-Host "[stage_winui_msix] Intermediate package is not candidate-bound or distributable until build_all finalization." -ForegroundColor Yellow
if ($ReleaseMode -eq "developer") {
  Write-Warning "Developer structural package is NON-DISTRIBUTABLE. It does not satisfy signing, timestamp, lifecycle, or Store gates."
}

Write-Host ("[stage_winui_msix] Staged: " + $stagedPath) -ForegroundColor Green
Write-Host ("[stage_winui_msix] Metadata: " + $metadataPath) -ForegroundColor Green
