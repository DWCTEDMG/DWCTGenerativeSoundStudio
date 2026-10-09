param([string]$Distribution = 'Ubuntu')
$ErrorActionPreference = 'Stop'
$serviceUrl = 'http://127.0.0.1:8011/health'
try {
    $existing = Invoke-RestMethod -Uri $serviceUrl -TimeoutSec 3
} catch { $existing = $null }
if ($null -ne $existing) {
    if ($existing.provider -eq 'local_wsl_cuda') { $existing; return }
    throw 'Port 8011 belongs to another service.'
}
$localScript = Join-Path $PSScriptRoot 'local_nvidia_server.py'
$wslScript = (& wsl.exe --distribution $Distribution --exec wslpath -a -u $localScript).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not resolve the Studio script in WSL.' }
$wslHome = (& wsl.exe --distribution $Distribution --exec sh -c 'printf %s "$HOME"').Trim()
if ($LASTEXITCODE -ne 0 -or -not $wslHome.StartsWith('/home/')) { throw 'Could not resolve the WSL user home.' }
$runtimePython = "$wslHome/.venvs/studio-nvidia/bin/python"
& wsl.exe --distribution $Distribution --exec test -x $runtimePython
if ($LASTEXITCODE -ne 0) { throw 'Install the isolated studio-nvidia WSL environment before starting the local models.' }
$logs = Join-Path $env:LOCALAPPDATA 'EDMGStudio\logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$process = Start-Process wsl.exe -WindowStyle Hidden -PassThru -ArgumentList @(
    '--distribution', $Distribution, '--exec',
    $runtimePython, $wslScript
) -RedirectStandardOutput (Join-Path $logs "local-nvidia-$stamp.stdout.log") `
  -RedirectStandardError (Join-Path $logs "local-nvidia-$stamp.stderr.log")
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 500
    if ($process.HasExited) { throw "Local NVIDIA service exited. Inspect $logs." }
    try {
        $health = Invoke-RestMethod -Uri $serviceUrl -TimeoutSec 2
        if ($health.provider -eq 'local_wsl_cuda') { $health; return }
    } catch { }
}
throw "Service did not become reachable. Inspect $logs."
