param(
  [string]$Image = "nvcr.io/nvidia/k8s/cuda-sample:nbody",
  [string[]]$Command = @("nbody", "-gpu", "-benchmark")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repoRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw "docker was not found on PATH. Install/start Docker Desktop first."
}

Write-Host "[nvidia-docker] Docker version: $(docker --version)"
Write-Host "[nvidia-docker] Runtime map:"
docker info --format "{{json .Runtimes}}"

Write-Host "[nvidia-docker] Running GPU container probe with $Image"
docker run --rm --gpus all $Image @Command
Write-Host "[nvidia-docker] GPU container probe complete"
