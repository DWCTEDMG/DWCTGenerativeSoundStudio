param(
  [string]$SubscriptionId = "",
  [string]$ResourceGroup = "rg-edmg-model-cache",
  [string]$Location = "eastus",
  [string]$StorageAccount = "",
  [string]$Container = "edmg-model-cache",
  [string]$Prefix = "models"
)

$ErrorActionPreference = "Stop"

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "==> $Message"
}

function Invoke-Az {
  param([string[]]$Arguments)
  & az @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "az $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
  }
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
  throw "Azure CLI is not installed or not on PATH. Install it, restart PowerShell, then rerun this script."
}

Write-Step "Checking Azure CLI sign-in"
$SignedIn = $false
try {
  $null = (& az account show --query id -o tsv 2>$null)
  $SignedIn = $LASTEXITCODE -eq 0
} catch {
  $SignedIn = $false
}

if (-not $SignedIn) {
  Invoke-Az @("login")
}

if ($SubscriptionId.Trim()) {
  Write-Step "Selecting subscription $SubscriptionId"
  Invoke-Az @("account", "set", "--subscription", $SubscriptionId)
}

if (-not $StorageAccount.Trim()) {
  $chars = "abcdefghijklmnopqrstuvwxyz0123456789".ToCharArray()
  $suffix = -join (1..8 | ForEach-Object { $chars | Get-Random })
  $StorageAccount = "edmgmodels$suffix"
}

$StorageAccount = $StorageAccount.ToLowerInvariant()
if ($StorageAccount.Length -gt 24) {
  throw "Storage account name must be 24 characters or fewer."
}
if ($StorageAccount -notmatch "^[a-z0-9]{3,24}$") {
  throw "Storage account name must be 3-24 lowercase letters or numbers."
}

Write-Step "Creating or reusing resource group $ResourceGroup"
Invoke-Az @("group", "create", "--name", $ResourceGroup, "--location", $Location, "-o", "none")

Write-Step "Creating or reusing storage account $StorageAccount"
Invoke-Az @(
  "storage", "account", "create",
  "--name", $StorageAccount,
  "--resource-group", $ResourceGroup,
  "--location", $Location,
  "--sku", "Standard_LRS",
  "--kind", "StorageV2",
  "--https-only", "true",
  "--min-tls-version", "TLS1_2",
  "--allow-blob-public-access", "false",
  "-o", "none"
)

$StorageScope = (& az storage account show --name $StorageAccount --resource-group $ResourceGroup --query id -o tsv).Trim()

Write-Step "Granting your signed-in account Blob Data Contributor on the storage account"
try {
  $PrincipalId = (& az ad signed-in-user show --query id -o tsv).Trim()
  if ($PrincipalId) {
    & az role assignment create `
      --assignee $PrincipalId `
      --role "Storage Blob Data Contributor" `
      --scope $StorageScope `
      -o none 2>$null
    if ($LASTEXITCODE -ne 0) {
      Write-Warning "Role assignment may already exist, or this account may not have permission to assign roles."
    }
  }
} catch {
  Write-Warning "Could not assign data-plane role automatically: $($_.Exception.Message)"
}

Write-Step "Creating or reusing Blob container $Container"
Invoke-Az @(
  "storage", "container", "create",
  "--account-name", $StorageAccount,
  "--name", $Container,
  "--auth-mode", "login",
  "-o", "none"
)

$AccountUrl = "https://$StorageAccount.blob.core.windows.net"

Write-Step "EDMG Azure model cache environment"
Write-Host "`$env:EDMG_AZURE_MODEL_CACHE='1'"
Write-Host "`$env:EDMG_AZURE_STORAGE_ACCOUNT='$StorageAccount'"
Write-Host "`$env:EDMG_AZURE_STORAGE_ACCOUNT_URL='$AccountUrl'"
Write-Host "`$env:EDMG_AZURE_MODEL_CONTAINER='$Container'"
Write-Host "`$env:EDMG_AZURE_MODEL_CACHE_PREFIX='$Prefix'"

Write-Host ""
Write-Host "Connection-string fallback, if CLI/AAD auth is not available to the backend:"
Write-Host "az storage account show-connection-string --name $StorageAccount --resource-group $ResourceGroup --query connectionString -o tsv"
