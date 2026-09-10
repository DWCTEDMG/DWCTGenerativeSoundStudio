[CmdletBinding()]
param(
    [string]$StudioHome = $env:EDMG_STUDIO_HOME
)

# The assets attached to the official v0.4.0 release use its b10809 build tag.
# CUDA 12.4 supports the Studio Windows CUDA driver baseline without a toolkit install.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ([string]::IsNullOrWhiteSpace($StudioHome)) {
    $StudioHome = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\data'))
}
$runtimeHome = [IO.Path]::GetFullPath($StudioHome)
$toolsRoot = [IO.Path]::GetFullPath((Join-Path $runtimeHome 'tools'))
$target = [IO.Path]::GetFullPath((Join-Path $toolsRoot 'llama.cpp'))
$cache = Join-Path $runtimeHome 'cache\llama.cpp\b10809-cuda12.4'
$assets = @(
    @{
        Name = 'llama-b10809-bin-win-cuda-12.4-x64.zip'
        Bytes = 253938543
        Sha256 = 'c77bfcd9ed8d91e8721a2d6a290b907fddd4fa5412a47b21c6fa1709116b85f9'
    },
    @{
        Name = 'cudart-llama-bin-win-cuda-12.4-x64.zip'
        Bytes = 391443627
        Sha256 = '8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6'
    }
)

if (Test-Path -LiteralPath $target) {
    throw "Runtime destination already exists: $target. Preserve or relocate it before replacing the runtime."
}
New-Item -ItemType Directory -Path $cache, $toolsRoot -Force | Out-Null
$stage = [IO.Path]::GetFullPath((Join-Path $toolsRoot ('llama.cpp-staging-' + [Guid]::NewGuid().ToString('N'))))
if ((Split-Path -Parent $stage) -ne $toolsRoot -or (Split-Path -Parent $target) -ne $toolsRoot) {
    throw 'Runtime staging and destination must stay inside the selected tools directory.'
}
New-Item -ItemType Directory -Path $stage | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem

foreach ($asset in $assets) {
    $archive = Join-Path $cache $asset.Name
    $url = 'https://github.com/ggml-org/llama.cpp/releases/download/b10809/' + $asset.Name
    $valid = (Test-Path -LiteralPath $archive) -and
        (Get-Item -LiteralPath $archive).Length -eq $asset.Bytes -and
        (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -eq $asset.Sha256
    if (-not $valid) {
        $partial = $archive + '.' + [Guid]::NewGuid().ToString('N') + '.part'
        Write-Output "Downloading $($asset.Name)"
        Invoke-WebRequest -Uri $url -OutFile $partial -TimeoutSec 1800
        if ((Get-Item -LiteralPath $partial).Length -ne $asset.Bytes -or
            (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ne $asset.Sha256) {
            throw "Runtime archive failed size/SHA-256 verification: $partial"
        }
        Move-Item -LiteralPath $partial -Destination $archive -Force
    }
    Write-Output "Verified $($asset.Name)"
    $zip = [IO.Compression.ZipFile]::OpenRead($archive)
    try {
        foreach ($entry in $zip.Entries) {
            $entryTarget = [IO.Path]::GetFullPath((Join-Path $stage $entry.FullName))
            if (-not $entryTarget.StartsWith($stage + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Archive entry escapes runtime staging: $($entry.FullName)"
            }
            if ([string]::IsNullOrEmpty($entry.Name)) {
                New-Item -ItemType Directory -Path $entryTarget -Force | Out-Null
                continue
            }
            $entryDirectory = Split-Path -Parent $entryTarget
            if ($entryDirectory) {
                New-Item -ItemType Directory -Path $entryDirectory -Force | Out-Null
            }
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $entryTarget, $true)
        }
    } finally {
        $zip.Dispose()
    }
}

$server = Join-Path $stage 'llama-server.exe'
if (-not (Test-Path -LiteralPath $server)) {
    throw "Verified archives do not contain llama-server.exe at $stage"
}
$version = (& $server --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "llama-server version probe failed: $version" }
$devices = (& $server --list-devices 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $devices -notmatch 'CUDA0:') {
    throw "llama-server did not expose a CUDA device: $devices"
}
$receipt = @{
    schema_version = 1
    repository = 'https://github.com/ggml-org/llama.cpp'
    release = 'v0.4.0'
    build = 'b10809'
    commit = '5266f24da75dc449bd56cbed7addb9c8e4a6a73e'
    cuda = '12.4'
    assets = $assets
    installed_at = [DateTimeOffset]::UtcNow.ToString('o')
    version_output = $version
    devices_output = $devices
    server_sha256 = (Get-FileHash -LiteralPath $server -Algorithm SHA256).Hash.ToLowerInvariant()
}
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $stage 'runtime-install.json') -Encoding utf8
# Both absolute paths were checked against toolsRoot above; publish only a verified runtime.
Move-Item -LiteralPath $stage -Destination $target
Write-Output "Installed: $target"
Write-Output $version
Write-Output $devices
