param([Parameter(Mandatory)][string]$HostPath)
$ErrorActionPreference = 'Stop'
$start = [Diagnostics.ProcessStartInfo]::new($HostPath)
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardInput = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
$token = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
$start.Environment['EDMG_JUCE_SESSION_TOKEN'] = $token
$hostProcess = [Diagnostics.Process]::new()
$hostProcess.StartInfo = $start
function Read-HostReply {
    $read = $hostProcess.StandardOutput.ReadLineAsync()
    if (-not $read.Wait(15000)) { throw 'JUCE reply timed out.' }
    if ($null -eq $read.Result) { throw 'JUCE closed stdout unexpectedly.' }
    return $read.Result | ConvertFrom-Json
}
function Send-HostCommand([long]$Sequence, [string]$Kind, $Payload) {
    $hostProcess.StandardInput.WriteLine((@{protocolVersion=1; sequence=$Sequence; correlationId="install-$Sequence"; kind=$Kind; payload=$Payload} | ConvertTo-Json -Compress -Depth 8))
    $hostProcess.StandardInput.Flush()
    $reply = Read-HostReply
    if ($reply.kind -eq 'error') { throw ($reply.payload | ConvertTo-Json -Compress) }
    return $reply
}
try {
    [void]$hostProcess.Start()
    $stderr = $hostProcess.StandardError.ReadToEndAsync()
    $hostProcess.StandardInput.WriteLine((@{minimumProtocolVersion=1; maximumProtocolVersion=1; clientBuildIdentity='edmg-install-verification'; sessionToken=$token} | ConvertTo-Json -Compress))
    $hostProcess.StandardInput.Flush()
    $handshake = Read-HostReply
    if (-not $handshake.compatible -or $handshake.architecture -ne 'x64') { throw 'Incompatible JUCE handshake.' }
    $devices = Send-HostCommand 1 'list_devices' @{}
    if ($devices.kind -ne 'device_list') { throw 'Unexpected device response.' }
    $device = $devices.payload | Where-Object { $_.api -like 'Windows Audio*' -and $_.api -notlike '*Exclusive*' -and $_.isDefaultOutput } | Select-Object -First 1
    if ($null -eq $device) { $device = $devices.payload | Where-Object { $_.supportsSharedMode } | Select-Object -First 1 }
    if ($null -eq $device) { throw 'No output device discovered.' }
    $configured = Send-HostCommand 2 'configure_device' @{deviceId=$device.id; sampleRate=48000; bufferFrames=512; outputChannels=2; exclusiveMode=$false}
    if (-not $configured.payload.configured) { throw 'Device configuration failed.' }
    $position = Send-HostCommand 3 'transport' @{action='query'}
    $closed = Send-HostCommand 4 'close_device' @{}
    $hostProcess.StandardInput.Close()
    if (-not $hostProcess.WaitForExit(10000)) { throw 'JUCE exit timed out.' }
    if ($hostProcess.ExitCode -ne 0) { throw "JUCE exited $($hostProcess.ExitCode)." }
    $errors = $stderr.GetAwaiter().GetResult()
    if ($errors) { throw "JUCE stderr: $errors" }
    @{host=$HostPath; handshake=$handshake; deviceCount=@($devices.payload).Count; configuredDevice=$configured.payload; transport=$position.payload; exitCode=$hostProcess.ExitCode; verifiedUtc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json -Depth 8
} finally {
    if ($hostProcess.Id -and -not $hostProcess.HasExited) { $hostProcess.Kill($true) }
    $hostProcess.Dispose()
}
