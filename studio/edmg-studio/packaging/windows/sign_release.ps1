param(
  [string]$StudioDir = "",
  [string[]]$ArtifactPaths = @(),
  [switch]$RequireSigning,
  [switch]$VerifyOnly,
  [string]$SignToolPath = ""
)

$ErrorActionPreference = "Stop"

# The build can be launched from PowerShell 7, whose PSModulePath is inherited by
# Windows PowerShell 5.1. Load the security module from the current host's own
# PSHOME so module auto-discovery cannot select an incompatible edition.
$securityModule = Join-Path $PSHOME "Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1"
if (-not (Test-Path -LiteralPath $securityModule -PathType Leaf)) {
  throw "Microsoft.PowerShell.Security was not found under the active PowerShell host: $PSHOME"
}
Import-Module -Name $securityModule -Force -ErrorAction Stop

if (-not $StudioDir) {
  $StudioDir = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
} else {
  $StudioDir = (Resolve-Path $StudioDir).Path
}

function ConvertTo-BooleanSetting($Value, [string]$Name) {
  $normalized = ([string]$Value).Trim().ToLowerInvariant()
  if ($normalized -in @("1", "true", "yes", "on")) { return $true }
  if ($normalized -in @("", "0", "false", "no", "off")) { return $false }
  throw "$Name must be one of 1/0, true/false, yes/no, or on/off."
}

function Get-RelativeEvidencePath($Root, $Path) {
  $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd([char[]]"\/")
  $pathFull = [IO.Path]::GetFullPath($Path)
  $prefix = $rootFull + [IO.Path]::DirectorySeparatorChar
  if ($pathFull.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
    return $pathFull.Substring($prefix.Length).Replace("\", "/")
  }
  return $pathFull
}

function Resolve-SignableArtifacts($Root, $ExplicitPaths) {
  $candidates = @()
  if ($ExplicitPaths -and $ExplicitPaths.Count -gt 0) {
    $candidates = @($ExplicitPaths)
  } else {
    foreach ($directoryName in @("dist", "dist-inno", "dist-inno-cuda")) {
      $directory = Join-Path $Root $directoryName
      if (Test-Path -LiteralPath $directory -PathType Container) {
        $candidates += @(
          Get-ChildItem -LiteralPath $directory -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension.ToLowerInvariant() -in @(".exe", ".msi", ".msix") } |
            ForEach-Object { $_.FullName }
        )
      }
    }

    $ownedExecutables = @(
      "dist\win-unpacked\EDMG Studio.exe",
      "dist\win-unpacked\resources\backend\edmg-studio-backend.exe",
      "dist\win-unpacked\resources\backend\edmg-hf-bucket-helper.exe",
      "release\staged-app\electron-resources\backend\edmg-studio-backend.exe",
      "release\staged-app\electron-resources\backend\edmg-hf-bucket-helper.exe"
    )
    $candidates += @(
      $ownedExecutables |
        ForEach-Object { Join-Path $Root $_ } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
    )
  }

  $resolved = @()
  $seen = @{}
  foreach ($candidate in $candidates) {
    if ([string]::IsNullOrWhiteSpace([string]$candidate)) { continue }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
      throw "Signing artifact does not exist: $candidate"
    }
    $fullPath = (Resolve-Path -LiteralPath $candidate).Path
    $extension = [IO.Path]::GetExtension($fullPath).ToLowerInvariant()
    if ($extension -notin @(".exe", ".msi", ".msix")) {
      throw "Unsupported Windows signing artifact: $fullPath"
    }
    $key = $fullPath.ToLowerInvariant()
    if (-not $seen.ContainsKey($key)) {
      $seen[$key] = $true
      $resolved += $fullPath
    }
  }
  return @($resolved)
}

function Resolve-SignTool([string]$RequestedPath) {
  $configured = if ($RequestedPath) { $RequestedPath } else { [string]$env:EDMG_SIGNTOOL_PATH }
  if ($configured) {
    if (-not (Test-Path -LiteralPath $configured -PathType Leaf)) {
      throw "Configured SignTool executable was not found."
    }
    return (Resolve-Path -LiteralPath $configured).Path
  }

  $command = Get-Command "signtool.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($command) { return $command.Source }

  $kitRoots = @()
  $programFilesX86 = [string]${env:ProgramFiles(x86)}
  if ($programFilesX86) {
    $kitRoots += Join-Path $programFilesX86 "Windows Kits\10\bin"
    $kitRoots += Join-Path $programFilesX86 "Windows Kits\8.1\bin"
  }
  $kitRoots = @($kitRoots | Where-Object { Test-Path -LiteralPath $_ -PathType Container })

  $candidates = @()
  foreach ($kitRoot in $kitRoots) {
    $candidates += @(
      Get-ChildItem -Path (Join-Path $kitRoot "*\x64\signtool.exe") -File -ErrorAction SilentlyContinue
    )
    $direct = Join-Path $kitRoot "x64\signtool.exe"
    if (Test-Path -LiteralPath $direct -PathType Leaf) {
      $candidates += Get-Item -LiteralPath $direct
    }
  }

  $selected = $candidates | Sort-Object {
    try { [version]$_.Directory.Parent.Name } catch { [version]"0.0" }
  } -Descending | Select-Object -First 1
  if (-not $selected) {
    throw "signtool.exe was not found. Install the Windows SDK signing tools or set EDMG_SIGNTOOL_PATH."
  }
  return $selected.FullName
}

function Resolve-CertificateConfiguration([string]$Reference, [string]$Root) {
  $trimmed = $Reference.Trim()
  if (-not $trimmed) {
    return [pscustomobject]@{ Mode = "none"; Path = ""; Thumbprint = ""; MachineStore = $false }
  }

  $fileCandidate = if ([IO.Path]::IsPathRooted($trimmed)) { $trimmed } else { Join-Path $Root $trimmed }
  if (Test-Path -LiteralPath $fileCandidate -PathType Leaf) {
    $resolvedPath = (Resolve-Path -LiteralPath $fileCandidate).Path
    if ([IO.Path]::GetExtension($resolvedPath).ToLowerInvariant() -notin @(".pfx", ".p12")) {
      throw "EDMG_CODE_SIGN_CERT file references must use the .pfx or .p12 extension."
    }
    try {
      $pfx = [Security.Cryptography.X509Certificates.X509Certificate2]::new(
        $resolvedPath,
        [string]$env:EDMG_CODE_SIGN_PASSWORD,
        [Security.Cryptography.X509Certificates.X509KeyStorageFlags]::DefaultKeySet
      )
    } catch {
      throw "The configured PFX/P12 certificate could not be opened with EDMG_CODE_SIGN_PASSWORD."
    }
    try {
      $now = Get-Date
      $ekuOids = @($pfx.EnhancedKeyUsageList | ForEach-Object { $_.ObjectId.Value })
      if (-not $pfx.HasPrivateKey) {
        throw "The configured PFX/P12 certificate does not contain a private key."
      }
      if ($pfx.NotBefore -gt $now -or $pfx.NotAfter -le $now) {
        throw "The configured PFX/P12 certificate is not currently valid."
      }
      if ($ekuOids -notcontains "1.3.6.1.5.5.7.3.3") {
        throw "The configured PFX/P12 certificate does not include the Code Signing enhanced key usage."
      }
      $pfxThumbprint = ([string]$pfx.Thumbprint).Replace(" ", "").ToUpperInvariant()
    } finally {
      $pfx.Dispose()
    }
    return [pscustomobject]@{
      Mode = "pfx"
      Path = $resolvedPath
      Thumbprint = $pfxThumbprint
      MachineStore = $false
    }
  }

  $thumbprint = ($trimmed -replace "\s", "").ToUpperInvariant()
  if ($thumbprint -notmatch "^[A-F0-9]{40}$") {
    throw "EDMG_CODE_SIGN_CERT must be an existing local PFX/P12 file or a SHA1 certificate thumbprint."
  }

  $now = Get-Date
  foreach ($store in @(
    [pscustomobject]@{ Path = "Cert:\CurrentUser\My"; Machine = $false },
    [pscustomobject]@{ Path = "Cert:\LocalMachine\My"; Machine = $true }
  )) {
    $certificatePath = Join-Path $store.Path $thumbprint
    $certificate = Get-Item -LiteralPath $certificatePath -ErrorAction SilentlyContinue
    if (-not $certificate) { continue }
    $ekuOids = @($certificate.EnhancedKeyUsageList | ForEach-Object { $_.ObjectId.Value })
    if (-not $certificate.HasPrivateKey) {
      throw "The configured code-signing certificate does not expose a private key."
    }
    if ($certificate.NotBefore -gt $now -or $certificate.NotAfter -le $now) {
      throw "The configured code-signing certificate is not currently valid."
    }
    if ($ekuOids -notcontains "1.3.6.1.5.5.7.3.3") {
      throw "The configured certificate does not include the Code Signing enhanced key usage."
    }
    return [pscustomobject]@{
      Mode = "thumbprint"
      Path = ""
      Thumbprint = $thumbprint
      MachineStore = [bool]$store.Machine
    }
  }
  throw "The configured code-signing certificate thumbprint was not found in the CurrentUser or LocalMachine My store."
}

function Invoke-SignToolChecked([string]$Tool, [string]$Operation, [string[]]$Arguments) {
  $output = @(& $Tool @Arguments 2>&1)
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    $detail = ($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
    throw "$Operation failed with exit code $exitCode.$([Environment]::NewLine)$detail"
  }
}

function Get-AuthenticodeRecord([string]$Artifact) {
  $signature = Get-AuthenticodeSignature -LiteralPath $Artifact
  return [ordered]@{
    status = [string]$signature.Status
    statusMessage = [string]$signature.StatusMessage
    signerSubject = if ($signature.SignerCertificate) { [string]$signature.SignerCertificate.Subject } else { "" }
    signerThumbprint = if ($signature.SignerCertificate) { [string]$signature.SignerCertificate.Thumbprint } else { "" }
    signerNotAfter = if ($signature.SignerCertificate) { $signature.SignerCertificate.NotAfter.ToUniversalTime().ToString("o") } else { $null }
  }
}

function Write-SignatureEvidence($Root, $Run) {
  $evidenceDir = Join-Path $Root "release\evidence"
  New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null
  $evidencePath = Join-Path $evidenceDir "windows-signatures.json"
  $runs = @()
  if (Test-Path -LiteralPath $evidencePath -PathType Leaf) {
    try {
      $existing = Get-Content -Raw -LiteralPath $evidencePath | ConvertFrom-Json
      if ($existing.schemaVersion -eq 1 -and $existing.runs) {
        $runs = @($existing.runs)
      }
    } catch {
      throw "Existing Windows signature evidence is invalid JSON: $evidencePath"
    }
  }
  $runs += [pscustomobject]$Run
  $document = [ordered]@{
    schemaVersion = 1
    updatedAt = (Get-Date).ToUniversalTime().ToString("o")
    runs = $runs
  }
  $temporaryPath = "$evidencePath.tmp.$PID"
  $json = $document | ConvertTo-Json -Depth 12
  [IO.File]::WriteAllText($temporaryPath, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
  Move-Item -Force -LiteralPath $temporaryPath -Destination $evidencePath
  return $evidencePath
}

$required = [bool]$RequireSigning -or (ConvertTo-BooleanSetting $env:EDMG_REQUIRE_CODE_SIGNING "EDMG_REQUIRE_CODE_SIGNING")
$artifacts = @(Resolve-SignableArtifacts $StudioDir $ArtifactPaths)
$certificateReference = [string]$env:EDMG_CODE_SIGN_CERT
$certificate = Resolve-CertificateConfiguration $certificateReference $StudioDir
$timestampUrl = if ($env:EDMG_CODE_SIGN_TIMESTAMP_URL) {
  [string]$env:EDMG_CODE_SIGN_TIMESTAMP_URL
} else {
  "http://timestamp.digicert.com"
}
if ($timestampUrl -notmatch "^https?://") {
  throw "EDMG_CODE_SIGN_TIMESTAMP_URL must be an absolute HTTP or HTTPS URL."
}

$run = [ordered]@{
  startedAt = (Get-Date).ToUniversalTime().ToString("o")
  completedAt = $null
  required = $required
  verifyOnly = [bool]$VerifyOnly
  certificateMode = [string]$certificate.Mode
  expectedSignerThumbprint = [string]$certificate.Thumbprint
  timestampUrl = $timestampUrl
  signTool = $null
  ok = $false
  error = $null
  artifacts = @()
}

try {
  if ($artifacts.Count -eq 0) {
    if ($required) {
      throw "Code signing is required, but no Windows installer or EDMG-owned executable artifacts were found."
    }
    Write-Host "[sign_release] No Windows signing artifacts were found." -ForegroundColor Yellow
    $run.ok = $true
  } else {
    $needsSignTool = $certificate.Mode -ne "none"
    if (-not $needsSignTool) {
      foreach ($artifact in $artifacts) {
        if ((Get-AuthenticodeSignature -LiteralPath $artifact).Status -eq "Valid") {
          $needsSignTool = $true
          break
        }
      }
    }
    $signTool = if ($needsSignTool -or $required) { Resolve-SignTool $SignToolPath } else { "" }
    if ($signTool) {
      $run.signTool = [ordered]@{
        path = $signTool
        version = [string](Get-Item -LiteralPath $signTool).VersionInfo.FileVersion
      }
    }

    Write-Host ("[sign_release] Artifacts: " + $artifacts.Count) -ForegroundColor Cyan
    Write-Host ("[sign_release] Certificate mode: " + $certificate.Mode) -ForegroundColor Cyan
    foreach ($artifact in $artifacts) {
      $relativePath = Get-RelativeEvidencePath $StudioDir $artifact
      $record = [ordered]@{
        path = $relativePath
        action = ""
        authenticodeStatus = ""
        signToolVerified = $false
        signerSubject = ""
        signerThumbprint = ""
        expectedSignerThumbprint = [string]$certificate.Thumbprint
        signerNotAfter = $null
      }
      $before = Get-AuthenticodeRecord $artifact
      $beforeMatchesConfiguredSigner = $certificate.Mode -eq "none" -or (
        -not [string]::IsNullOrWhiteSpace([string]$before.signerThumbprint) -and
        [string]::Equals(
          ([string]$before.signerThumbprint).Replace(" ", ""),
          ([string]$certificate.Thumbprint).Replace(" ", ""),
          [StringComparison]::OrdinalIgnoreCase
        )
      )

      if ($before.status -eq "Valid" -and $beforeMatchesConfiguredSigner) {
        if (-not $signTool) { $signTool = Resolve-SignTool $SignToolPath }
        Invoke-SignToolChecked $signTool "Authenticode verification for $relativePath" @(
          "verify", "/pa", "/all", "/tw", "/v", $artifact
        )
        $after = $before
        $record.action = "verified"
        $record.signToolVerified = $true
      } elseif ($VerifyOnly -or $certificate.Mode -eq "none") {
        $record.action = "skipped"
        $record.authenticodeStatus = $before.status
        $run.artifacts += [pscustomobject]$record
        if ($required) {
          $signerDetail = if ($before.status -eq "Valid" -and -not $beforeMatchesConfiguredSigner) {
            "signer thumbprint $($before.signerThumbprint) does not match configured thumbprint $($certificate.Thumbprint)"
          } else {
            "status: $($before.status)"
          }
          throw "Required Authenticode signature is missing, invalid, or signed by the wrong certificate for $relativePath ($signerDetail)."
        }
        Write-Host ("[sign_release] Skipping unsigned artifact: " + $relativePath) -ForegroundColor Yellow
        continue
      } else {
        if (-not $signTool) { $signTool = Resolve-SignTool $SignToolPath }
        $signArguments = @("sign", "/fd", "SHA256", "/td", "SHA256", "/tr", $timestampUrl, "/v")
        if ($certificate.Mode -eq "pfx") {
          $signArguments += @("/a", "/f", $certificate.Path)
          $password = [string]$env:EDMG_CODE_SIGN_PASSWORD
          if ($password) { $signArguments += @("/p", $password) }
        } else {
          $signArguments += @("/sha1", $certificate.Thumbprint, "/s", "My")
          if ($certificate.MachineStore) { $signArguments += "/sm" }
        }
        $signArguments += $artifact
        Invoke-SignToolChecked $signTool "Authenticode signing for $relativePath" $signArguments
        $after = Get-AuthenticodeRecord $artifact
        if ($after.status -ne "Valid") {
          throw "Get-AuthenticodeSignature rejected $relativePath after signing (status: $($after.status))."
        }
        if (-not [string]::Equals(
          ([string]$after.signerThumbprint).Replace(" ", ""),
          ([string]$certificate.Thumbprint).Replace(" ", ""),
          [StringComparison]::OrdinalIgnoreCase
        )) {
          throw "Signed artifact $relativePath does not use the configured certificate thumbprint."
        }
        Invoke-SignToolChecked $signTool "Authenticode verification for $relativePath" @(
          "verify", "/pa", "/all", "/tw", "/v", $artifact
        )
        $record.action = "signed"
        $record.signToolVerified = $true
        Write-Host ("[sign_release] Signed and verified: " + $relativePath) -ForegroundColor Green
      }

      $record.authenticodeStatus = $after.status
      $record.signerSubject = $after.signerSubject
      $record.signerThumbprint = $after.signerThumbprint
      $record.signerNotAfter = $after.signerNotAfter
      $run.artifacts += [pscustomobject]$record
    }
    $run.ok = $true
  }
} catch {
  $run.error = $_.Exception.Message
  throw
} finally {
  $run.completedAt = (Get-Date).ToUniversalTime().ToString("o")
  $evidencePath = Write-SignatureEvidence $StudioDir $run
  Write-Host ("[sign_release] Signature evidence: " + $evidencePath) -ForegroundColor Cyan
}

exit 0
