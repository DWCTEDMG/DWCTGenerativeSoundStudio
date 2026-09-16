[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [Parameter(Mandatory = $true)]
  [ValidateSet("CleanInstall", "Upgrade", "Repair", "Rollback", "Uninstall", "Full")]
  [string]$Scenario,
  [string]$MsixPath = "",
  [string]$UpgradeMsixPath = "",
  [string]$PreviousMsixPath = "",
  [string]$InstallerPath = "",
  [string]$InstallRoot = "",
  [switch]$PlanOnly,
  [switch]$SkipLaunch,
  [string]$EvidenceDirectory = "",
  [string]$CandidateManifest = "",
  [string]$ReceiptInput = "",
  [ValidateSet("retain", "remove")]
  [string]$DataPolicy = "retain"
)

$ErrorActionPreference = "Stop"
$studioRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$manager = Join-Path $PSScriptRoot "manage_winui_package.ps1"
$validator = Join-Path $studioRoot "scripts\validate-lifecycle-evidence.mjs"
if (-not $EvidenceDirectory) { $EvidenceDirectory = Join-Path $PSScriptRoot "qualification-evidence" }
if (-not $CandidateManifest) { $CandidateManifest = Join-Path $studioRoot "release\candidate\release-candidate.json" }
if (-not (Test-Path -LiteralPath $CandidateManifest -PathType Leaf)) { throw "Candidate manifest is missing: $CandidateManifest" }
$candidate = Get-Content -Raw -LiteralPath $CandidateManifest | ConvertFrom-Json
$candidateId = [string]$candidate.candidateId
if ($candidateId -notmatch '^edmg-rc1-[a-f0-9]{64}$') { throw "Candidate manifest has an invalid candidate ID." }
$productionFull = $Scenario -eq "Full" -and [string]$candidate.candidateCore.policy.mode -eq "production"
$packageName = if ($candidate.candidateCore.product.identity.name) { [string]$candidate.candidateCore.product.identity.name } else { "ED2F9BCD-A580-4603-8A17-A7AD5FF6D451" }

function Get-BoundArtifact([string]$Role, [string]$ArtifactPath) {
  if (-not $ArtifactPath) { throw "$Role lifecycle operation requires an MSIX path." }
  if (-not (Test-Path -LiteralPath $ArtifactPath -PathType Leaf)) { throw "$Role MSIX is missing: $ArtifactPath" }
  $binding = $candidate.lifecycleArtifacts.$Role
  if (-not $binding) { throw "Candidate manifest lacks the explicit '$Role' lifecycle artifact binding." }
  $item = Get-Item -LiteralPath $ArtifactPath
  $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ArtifactPath).Hash.ToLowerInvariant()
  if ($hash -ne [string]$binding.sha256 -or $item.Length -ne [long]$binding.bytes -or $item.Name -ne [string]$binding.fileName) { throw "$Role MSIX path/hash/size does not match candidate lifecycle metadata." }
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $archive = [IO.Compression.ZipFile]::OpenRead($item.FullName)
  try {
    $entry = $archive.GetEntry("AppxManifest.xml")
    if (-not $entry) { throw "$Role MSIX has no AppxManifest.xml." }
    $reader = [IO.StreamReader]::new($entry.Open())
    try { [xml]$manifest = $reader.ReadToEnd() } finally { $reader.Dispose() }
  } finally { $archive.Dispose() }
  $manifestIdentity = $manifest.Package.Identity
  $identity = [ordered]@{ name=[string]$manifestIdentity.Name; publisher=[string]$manifestIdentity.Publisher; version=[string]$manifestIdentity.Version; architecture=[string]$manifestIdentity.ProcessorArchitecture }
  foreach ($field in @("name", "publisher", "version", "architecture")) {
    if (-not [string]::Equals([string]$identity.$field, [string]$binding.identity.$field, [StringComparison]::OrdinalIgnoreCase)) { throw "$Role MSIX extracted manifest $field does not match candidate lifecycle metadata." }
  }
  return [ordered]@{ fileName=$item.Name; bytes=[long]$item.Length; sha256=$hash; identity=$identity }
}
function Assert-InstalledIdentity($Expected) {
  if ($PlanOnly) { return $null }
  $package = Get-InstalledPackage
  foreach ($field in @("Name", "Publisher", "Version")) {
    $actual = if ($field -eq "Version") { $package.Version.ToString() } else { [string]$package.$field }
    $expectedValue = [string]$Expected.($field.ToLowerInvariant())
    if (-not [string]::Equals($actual, $expectedValue, [StringComparison]::OrdinalIgnoreCase)) { throw "Installed package $field mismatch: expected '$expectedValue', found '$actual'." }
  }
  return $package
}
function Assert-NoRegistrationResidue {
  if ($PlanOnly) { return }
  if (Get-AppxPackage -Name $packageName -ErrorAction SilentlyContinue) { throw "Uninstall residue: package remains registered." }
}
function Get-CandidateOwnedProcesses([string]$Root) {
  if (-not $Root) { return @() }
  $prefix = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
  return @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { $_.ExecutablePath -and ([IO.Path]::GetFullPath($_.ExecutablePath)).StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) })
}
function Invoke-InstallerUninstall {
  if (-not $InstallRoot) { throw "Installer uninstall qualification requires -InstallRoot." }
  $uninstaller = Join-Path $InstallRoot "unins000.exe"
  if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) { throw "Canonical Inno uninstaller is missing: $uninstaller" }
  $process = Start-Process -FilePath $uninstaller -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') -Wait -PassThru
  if ($process.ExitCode -ne 0) { throw "Inno uninstaller failed with exit code $($process.ExitCode)." }
  for ($attempt = 0; $attempt -lt 20 -and (Test-Path -LiteralPath $InstallRoot); $attempt++) { Start-Sleep -Milliseconds 250 }
  if (Test-Path -LiteralPath $InstallRoot) { throw "Uninstall residue: install root remains." }
  foreach ($shortcut in @(Join-Path ([Environment]::GetFolderPath('Desktop')) 'EDMG Studio.lnk'; Join-Path ([Environment]::GetFolderPath('Programs')) 'EDMG Studio\EDMG Studio.lnk')) { if (Test-Path -LiteralPath $shortcut) { throw "Uninstall residue: shortcut remains: $shortcut" } }
  $uninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{faa597b4-33fe-5e5f-81a9-4db216782ca3}_is1'
  foreach ($hive in @("HKCU:\", "HKLM:\", "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{faa597b4-33fe-5e5f-81a9-4db216782ca3}_is1")) {
    $key = if ($hive.EndsWith('\')) { $hive + $uninstallKey } else { $hive }
    if (Test-Path -LiteralPath $key) { throw "Uninstall residue: uninstall registry entry remains." }
  }
  Assert-NoRegistrationResidue
  $survivors = @(Get-CandidateOwnedProcesses $InstallRoot)
  if ($survivors.Count) { throw "Uninstall residue: candidate-owned processes remain: $($survivors.ProcessId -join ', ')." }
}

function Assert-ExternalPrerequisites {
  if (-not $IsWindows -and $PSVersionTable.PSEdition -eq "Core") { throw "MSIX lifecycle qualification requires Windows 10/11." }
  if (-not (Get-Command Add-AppxPackage -ErrorAction SilentlyContinue)) { throw "Appx PowerShell cmdlets are unavailable." }
  if (-not (Test-Path -LiteralPath $manager -PathType Leaf)) { throw "Package manager is missing: $manager" }
}
function Invoke-ManagedAction([string]$Action, [hashtable]$Arguments) {
  $display = "$Action " + (($Arguments.GetEnumerator() | ForEach-Object { "-$($_.Key) '$($_.Value)'" }) -join " ")
  if ($PlanOnly) { Write-Host "[plan] $display"; return }
  if ($PSCmdlet.ShouldProcess($packageName, $display)) { & $manager -Action $Action @Arguments }
}
function Get-InstalledPackage {
  if ($PlanOnly) { return $null }
  $package = Get-AppxPackage -Name $packageName -ErrorAction SilentlyContinue
  if (-not $package) { throw "Package integrity check failed: package is not registered." }
  if (-not (Test-Path -LiteralPath (Join-Path $package.InstallLocation "AppxManifest.xml") -PathType Leaf)) { throw "Package integrity check failed: manifest missing." }
  return $package
}
function New-Receipt([string]$Status = "not-run", [string]$Evidence = "", $ObservedAt = $null) {
  return [ordered]@{ status=$Status; evidence=$Evidence; observedAt=$ObservedAt }
}
function Pass-Receipt([string]$Name, [string]$Evidence) {
  $receipts[$Name] = New-Receipt "passed" $Evidence ((Get-Date).ToUniversalTime().ToString("o"))
}

if (-not $PlanOnly) { Assert-ExternalPrerequisites }
New-Item -ItemType Directory -Force -Path $EvidenceDirectory | Out-Null
$startedAt = (Get-Date).ToUniversalTime()
$receipts = [ordered]@{}
foreach ($name in @("cleanInstall", "firstRunNativeFlow", "projectPersistence", "autosaveRecovery", "upgrade", "repair", "rollback", "uninstall")) { $receipts[$name] = New-Receipt }
$interactiveReceipt = $null
if ($ReceiptInput) {
  if (-not (Test-Path -LiteralPath $ReceiptInput -PathType Leaf)) { throw "Interactive receipt is missing: $ReceiptInput" }
  $supplied = Get-Content -Raw -LiteralPath $ReceiptInput | ConvertFrom-Json
  $interactiveReceipt = $supplied.provenance
  if (-not $interactiveReceipt -or $interactiveReceipt.candidateId -ne $candidateId) { throw "Interactive receipt candidate ID is missing or mismatched." }
  if (-not $interactiveReceipt.evidenceReference -or $interactiveReceipt.evidenceSha256 -notmatch '^[a-f0-9]{64}$') { throw "Interactive receipt requires an immutable evidence reference and SHA256." }
  $evidencePath = if ([IO.Path]::IsPathRooted([string]$interactiveReceipt.evidenceReference)) { [string]$interactiveReceipt.evidenceReference } else { Join-Path (Split-Path -Parent (Resolve-Path -LiteralPath $ReceiptInput).Path) ([string]$interactiveReceipt.evidenceReference) }
  if (-not (Test-Path -LiteralPath $evidencePath -PathType Leaf)) { throw "Interactive receipt evidence is missing: $evidencePath" }
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath $evidencePath).Hash.ToLowerInvariant() -ne [string]$interactiveReceipt.evidenceSha256) { throw "Interactive receipt immutable evidence hash mismatch." }
  foreach ($name in @("firstRunNativeFlow", "projectPersistence", "autosaveRecovery")) {
    if ($supplied.receipts.$name) { $receipts[$name] = $supplied.receipts.$name }
  }
}
$packageIdentity = [ordered]@{ name=$packageName; publisher=[string]$candidate.candidateCore.product.identity.publisher; version=[string]$candidate.candidateCore.product.identity.version; architecture="x64" }
$result = $null
$artifactBindings = [ordered]@{ install=$null; upgrade=$null; rollback=$null }
$currentExpectedIdentity = $null
try {
  if ($MsixPath) { $artifactBindings.install = Get-BoundArtifact "install" $MsixPath }
  if ($UpgradeMsixPath) { $artifactBindings.upgrade = Get-BoundArtifact "upgrade" $UpgradeMsixPath }
  if ($PreviousMsixPath) { $artifactBindings.rollback = Get-BoundArtifact "rollback" $PreviousMsixPath }
  if ($Scenario -eq "Full") {
    $candidatePackage = $candidate.artifacts.msix
    if (-not $candidatePackage -or $artifactBindings.upgrade.sha256 -ne [string]$candidatePackage.sha256 -or $artifactBindings.upgrade.bytes -ne [long]$candidatePackage.bytes -or $artifactBindings.upgrade.fileName -ne [string]$candidatePackage.fileName) { throw "Full scenario upgrade role must be the candidate.artifacts.msix package." }
  }
  $interactiveArtifact = if ($Scenario -eq "Full") { $artifactBindings.upgrade } else { $artifactBindings.install }
  if ($interactiveReceipt) {
    if ($interactiveReceipt.testedPackageSha256 -ne $interactiveArtifact.sha256) { throw "Interactive receipt tested package SHA256 mismatch." }
    foreach ($field in @("name", "publisher", "version", "architecture")) { if ([string]$interactiveReceipt.packageIdentity.$field -ne [string]$interactiveArtifact.identity.$field) { throw "Interactive receipt package identity/version mismatch." } }
    $executedAt = [DateTimeOffset]::Parse([string]$interactiveReceipt.executedAt).ToUniversalTime()
    if ($executedAt -gt [DateTimeOffset]::UtcNow.AddMinutes(5) -or $executedAt -lt [DateTimeOffset]::UtcNow.AddDays(-30)) { throw "Interactive receipt is stale or future-dated." }
  }
  if ($productionFull) {
    if (-not $InstallerPath -or -not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) { throw "Production Full qualification requires the generated installer." }
    $installerItem = Get-Item -LiteralPath $InstallerPath
    $installerHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $InstallerPath).Hash.ToLowerInvariant()
    if (-not $candidate.evidence.signing -or -not $candidate.evidence.timestamp) { throw "Production Full qualification requires bound signing and timestamp evidence." }
    if (-not $candidate.artifacts.installer -or $installerHash -ne [string]$candidate.artifacts.installer.sha256 -or $installerItem.Length -ne [long]$candidate.artifacts.installer.bytes) { throw "Installer does not match candidate.artifacts.installer." }
  }
  if ($Scenario -in @("CleanInstall", "Full")) {
    if (-not $MsixPath) { throw "CleanInstall requires -MsixPath." }
    Invoke-ManagedAction "Uninstall" @{ InstallRoot=$InstallRoot }
    Invoke-ManagedAction "Install" @{ MsixPath=$MsixPath; InstallRoot=$InstallRoot }
    $package = Assert-InstalledIdentity $artifactBindings.install.identity
    $currentExpectedIdentity = $artifactBindings.install.identity
    if (-not $PlanOnly) { $packageIdentity = [ordered]@{ name=$package.Name; publisher=$package.Publisher; version=$package.Version.ToString(); architecture=$package.Architecture.ToString().ToLowerInvariant() } }
    if (-not $PlanOnly) { Pass-Receipt "cleanInstall" "Get-AppxPackage registration and installed AppxManifest.xml verified." }
    if (-not $SkipLaunch -and -not $PlanOnly) { Invoke-ManagedAction "Launch" @{} }
  }
  if ($Scenario -in @("Upgrade", "Full")) { if (-not $UpgradeMsixPath) { throw "Upgrade requires -UpgradeMsixPath." }; Invoke-ManagedAction "Install" @{ MsixPath=$UpgradeMsixPath; InstallRoot=$InstallRoot }; $null=Assert-InstalledIdentity $artifactBindings.upgrade.identity; $currentExpectedIdentity=$artifactBindings.upgrade.identity; if (-not $PlanOnly) { Pass-Receipt "upgrade" "Upgrade package registered and manifest verified." } }
  if ($Scenario -in @("Repair", "Full")) { Invoke-ManagedAction "Repair" @{}; if ($currentExpectedIdentity) { $null=Assert-InstalledIdentity $currentExpectedIdentity } else { $null=Get-InstalledPackage }; if (-not $PlanOnly) { Pass-Receipt "repair" "Repair completed and registration verified." } }
  if ($Scenario -in @("Rollback", "Full")) { if (-not $PreviousMsixPath) { throw "Rollback requires -PreviousMsixPath." }; Invoke-ManagedAction "Rollback" @{ PreviousMsixPath=$PreviousMsixPath }; $null=Assert-InstalledIdentity $artifactBindings.rollback.identity; $currentExpectedIdentity=$artifactBindings.rollback.identity; if (-not $PlanOnly) { Pass-Receipt "rollback" "Previous package restored and registration verified." } }
  if ($Scenario -in @("Uninstall", "Full")) {
    if ($InstallerPath) { Invoke-InstallerUninstall } else { Invoke-ManagedAction "Uninstall" @{ InstallRoot=$InstallRoot }; Assert-NoRegistrationResidue }
    $locator = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "EDMG Studio\installation.json"
    $locatorExists = Test-Path -LiteralPath $locator
    if (-not $PlanOnly -and $DataPolicy -eq "remove" -and $locatorExists) { throw "Data removal policy failed: installation locator remains." }
    if (-not $PlanOnly -and $DataPolicy -eq "retain" -and -not $locatorExists) { throw "Data retention policy failed: installation locator was removed." }
    if (-not $PlanOnly) { Pass-Receipt "uninstall" "Registration removed; data policy '$DataPolicy' observed (locator present=$locatorExists)." }
  }
  $allPassed = @($receipts.Values | Where-Object { $_.status -ne "passed" }).Count -eq 0
  $status = if ($PlanOnly) { "planned" } elseif ($allPassed) { "passed" } else { "incomplete" }
  $result = [ordered]@{ schemaVersion=4; candidateId=$candidateId; packageIdentity=$packageIdentity; artifacts=$artifactBindings; candidateArtifact=$(if ($Scenario -eq "Full") { $artifactBindings.upgrade } else { $null }); interactiveReceipt=$interactiveReceipt; dataPolicy=$DataPolicy; scenario=$Scenario; status=$status; startedAt=$startedAt.ToString("o"); completedAt=(Get-Date).ToUniversalTime().ToString("o"); receipts=$receipts }
} catch {
  $result = [ordered]@{ schemaVersion=4; candidateId=$candidateId; packageIdentity=$packageIdentity; artifacts=$artifactBindings; candidateArtifact=$(if ($Scenario -eq "Full") { $artifactBindings.upgrade } else { $null }); interactiveReceipt=$interactiveReceipt; dataPolicy=$DataPolicy; scenario=$Scenario; status="failed"; startedAt=$startedAt.ToString("o"); completedAt=(Get-Date).ToUniversalTime().ToString("o"); receipts=$receipts; error=$_.Exception.Message }
  throw
} finally {
  $resultPath = Join-Path $EvidenceDirectory "msix-lifecycle.json"
  [IO.File]::WriteAllText($resultPath, (($result | ConvertTo-Json -Depth 8) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
  & node $validator $resultPath --candidate-id $candidateId
  if ($LASTEXITCODE -ne 0) { throw "Lifecycle evidence validation failed." }
}
