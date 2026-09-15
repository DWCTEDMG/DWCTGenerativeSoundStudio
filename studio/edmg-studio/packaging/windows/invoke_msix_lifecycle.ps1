[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [Parameter(Mandatory = $true)]
  [ValidateSet("CleanInstall", "Upgrade", "Repair", "Rollback", "Uninstall", "Full")]
  [string]$Scenario,
  [string]$MsixPath = "",
  [string]$UpgradeMsixPath = "",
  [string]$PreviousMsixPath = "",
  [string]$InstallRoot = "",
  [switch]$PlanOnly,
  [switch]$SkipLaunch,
  [string]$EvidenceDirectory = ""
)

$ErrorActionPreference = "Stop"
$manager = Join-Path $PSScriptRoot "manage_winui_package.ps1"
$packageName = "ED2F9BCD-A580-4603-8A17-A7AD5FF6D451"
if (-not $EvidenceDirectory) { $EvidenceDirectory = Join-Path $PSScriptRoot "qualification-evidence" }

function Assert-ExternalPrerequisites {
  if ($PSVersionTable.PSEdition -ne "Desktop" -and $PSVersionTable.PSEdition -ne "Core") { throw "PowerShell is required." }
  if (-not $IsWindows -and $PSVersionTable.PSEdition -eq "Core") { throw "MSIX lifecycle qualification requires Windows 10/11." }
  if (-not (Get-Command Add-AppxPackage -ErrorAction SilentlyContinue)) { throw "Appx PowerShell cmdlets are unavailable." }
  if (-not (Test-Path -LiteralPath $manager -PathType Leaf)) { throw "Package manager is missing: $manager" }
}

function Invoke-ManagedAction([string]$Action, [hashtable]$Arguments) {
  $display = "$Action " + (($Arguments.GetEnumerator() | ForEach-Object { "-$($_.Key) '$($_.Value)'" }) -join " ")
  if ($PlanOnly) { Write-Host "[plan] $display"; return }
  if ($PSCmdlet.ShouldProcess($packageName, $display)) { & $manager -Action $Action @Arguments }
}

function Assert-Installed {
  if ($PlanOnly) { return }
  $package = Get-AppxPackage -Name $packageName -ErrorAction SilentlyContinue
  if (-not $package) { throw "Package integrity check failed: package is not registered." }
  $manifest = Join-Path $package.InstallLocation "AppxManifest.xml"
  if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { throw "Package integrity check failed: manifest missing." }
}

function Invoke-LaunchProbe {
  if ($SkipLaunch -or $PlanOnly) { return }
  Invoke-ManagedAction "Launch" @{}
  Start-Sleep -Seconds 5
  $package = Get-AppxPackage -Name $packageName
  if (-not $package) { throw "Launch probe lost package registration." }
}

function Assert-NoRegistrationResidue {
  if ($PlanOnly) { return }
  if (Get-AppxPackage -Name $packageName -ErrorAction SilentlyContinue) { throw "Uninstall residue: package remains registered." }
  $locator = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "EDMG Studio\installation.json"
  if ($InstallRoot -and (Test-Path -LiteralPath $locator)) { throw "Uninstall residue: installation locator remains." }
}

if (-not $PlanOnly) { Assert-ExternalPrerequisites }
New-Item -ItemType Directory -Force -Path $EvidenceDirectory | Out-Null
$startedAt = (Get-Date).ToUniversalTime()
$steps = [Collections.Generic.List[string]]::new()
try {
  if ($Scenario -in @("CleanInstall", "Full")) {
    if (-not $MsixPath) { throw "CleanInstall requires -MsixPath." }
    Invoke-ManagedAction "Uninstall" @{ InstallRoot = $InstallRoot }; $steps.Add("clean-uninstall")
    Invoke-ManagedAction "Install" @{ MsixPath = $MsixPath; InstallRoot = $InstallRoot }; $steps.Add("install")
    Assert-Installed; Invoke-LaunchProbe; $steps.Add("integrity-launch")
  }
  if ($Scenario -in @("Upgrade", "Full")) {
    if (-not $UpgradeMsixPath) { throw "Upgrade requires -UpgradeMsixPath." }
    Invoke-ManagedAction "Install" @{ MsixPath = $UpgradeMsixPath; InstallRoot = $InstallRoot }; Assert-Installed; $steps.Add("upgrade")
  }
  if ($Scenario -in @("Repair", "Full")) { Invoke-ManagedAction "Repair" @{}; Assert-Installed; $steps.Add("repair") }
  if ($Scenario -in @("Rollback", "Full")) {
    if (-not $PreviousMsixPath) { throw "Rollback requires -PreviousMsixPath." }
    Invoke-ManagedAction "Rollback" @{ PreviousMsixPath = $PreviousMsixPath }; Assert-Installed; $steps.Add("rollback")
  }
  if ($Scenario -in @("Uninstall", "Full")) {
    Invoke-ManagedAction "Uninstall" @{ InstallRoot = $InstallRoot }; Assert-NoRegistrationResidue; $steps.Add("uninstall-residue")
  }
  $result = [ordered]@{ schemaVersion=1; scenario=$Scenario; status=if($PlanOnly){"planned"}else{"passed"}; interactiveLaunchExecuted=(-not $PlanOnly -and -not $SkipLaunch); startedAt=$startedAt.ToString("o"); completedAt=(Get-Date).ToUniversalTime().ToString("o"); steps=@($steps) }
} catch {
  $result = [ordered]@{ schemaVersion=1; scenario=$Scenario; status="failed"; interactiveLaunchExecuted=$false; startedAt=$startedAt.ToString("o"); completedAt=(Get-Date).ToUniversalTime().ToString("o"); steps=@($steps); error=$_.Exception.Message }
  throw
} finally {
  $resultPath = Join-Path $EvidenceDirectory "msix-lifecycle.json"
  [IO.File]::WriteAllText($resultPath, (($result | ConvertTo-Json -Depth 6) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
}
