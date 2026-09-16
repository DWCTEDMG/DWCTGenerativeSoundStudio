param(
  [Parameter(Mandatory = $true)]
  [string[]]$ArtifactPaths,
  [string]$SignToolPath = "",
  [string]$ExpectedSignerThumbprint = $env:EDMG_EXPECTED_SIGNER_THUMBPRINT,
  [string]$ExpectedSignerSubject = $env:EDMG_EXPECTED_SIGNER_SUBJECT
)

$ErrorActionPreference = "Stop"
if (-not $IsWindows -and $PSVersionTable.PSEdition -eq "Core") { throw "Production signature verification requires Windows." }
if ([string]::IsNullOrWhiteSpace($ExpectedSignerThumbprint) -or $ExpectedSignerThumbprint -notmatch '^[A-Fa-f0-9 ]{40,59}$') { throw "EDMG_EXPECTED_SIGNER_THUMBPRINT is required and must be a SHA1 thumbprint." }
if ([string]::IsNullOrWhiteSpace($ExpectedSignerSubject)) { throw "EDMG_EXPECTED_SIGNER_SUBJECT is required." }
$expectedThumbprint = $ExpectedSignerThumbprint.Replace(" ", "").ToUpperInvariant()

function Resolve-SignTool([string]$Requested) {
  if ($Requested) {
    if (-not (Test-Path -LiteralPath $Requested -PathType Leaf)) { throw "Configured SignTool executable was not found." }
    return (Resolve-Path -LiteralPath $Requested).Path
  }
  $command = Get-Command "signtool.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($command) { return $command.Source }
  $root = [string]${env:ProgramFiles(x86)}
  if ($root) {
    $candidate = Get-ChildItem -Path (Join-Path $root "Windows Kits\10\bin\*\x64\signtool.exe") -File -ErrorAction SilentlyContinue |
      Sort-Object { try { [version]$_.Directory.Parent.Name } catch { [version]"0.0" } } -Descending | Select-Object -First 1
    if ($candidate) { return $candidate.FullName }
  }
  throw "signtool.exe was not found."
}

$signTool = Resolve-SignTool $SignToolPath
foreach ($artifact in $ArtifactPaths) {
  if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) { throw "Signed artifact is missing: $artifact" }
  $resolved = (Resolve-Path -LiteralPath $artifact).Path
  $signature = Get-AuthenticodeSignature -LiteralPath $resolved
  if ($signature.Status -ne [Management.Automation.SignatureStatus]::Valid -or -not $signature.SignerCertificate) { throw "Authenticode rejected $resolved (status: $($signature.Status))." }
  $actualThumbprint = ([string]$signature.SignerCertificate.Thumbprint).Replace(" ", "").ToUpperInvariant()
  if ($actualThumbprint -cne $expectedThumbprint) { throw "Signer thumbprint policy rejected $resolved." }
  if (-not [string]::Equals([string]$signature.SignerCertificate.Subject, $ExpectedSignerSubject, [StringComparison]::OrdinalIgnoreCase)) { throw "Signer subject policy rejected $resolved." }

  $chain = [Security.Cryptography.X509Certificates.X509Chain]::new()
  try {
    $chain.ChainPolicy.RevocationMode = [Security.Cryptography.X509Certificates.X509RevocationMode]::Online
    $chain.ChainPolicy.RevocationFlag = [Security.Cryptography.X509Certificates.X509RevocationFlag]::EntireChain
    if (-not $chain.Build($signature.SignerCertificate)) {
      $detail = @($chain.ChainStatus | ForEach-Object { $_.Status.ToString() }) -join ", "
      throw "Certificate chain validation rejected $resolved ($detail)."
    }
  } finally { $chain.Dispose() }

  $output = @(& $signTool verify /pa /all /tw /v $resolved 2>&1)
  if ($LASTEXITCODE -ne 0) { throw "SignTool trusted-timestamp verification rejected ${resolved}: $($output -join [Environment]::NewLine)" }
}
