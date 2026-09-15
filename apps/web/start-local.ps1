$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$webUrl = "http://localhost:3000"
$nodeInstallDir = Join-Path $env:ProgramFiles "nodejs"

function Write-Step {
  param([string]$Message)
  Write-Host "[Q-Agent] $Message" -ForegroundColor Cyan
}

function Test-HttpReady {
  param([string]$Url)

  try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
    return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
  }
  catch {
    return $false
  }
}

function Get-ListeningProcessId {
  param([int]$Port)

  try {
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
      Select-Object -First 1
    if ($connection) {
      return [int]$connection.OwningProcess
    }
  }
  catch {
    $line = netstat.exe -ano -p tcp |
      Where-Object { $_ -match ":$Port\s+.*LISTENING\s+(\d+)\s*$" } |
      Select-Object -First 1
    if ($line -and $line -match "LISTENING\s+(\d+)\s*$") {
      return [int]$Matches[1]
    }
  }

  return 0
}

function Clear-StaleQAgentService {
  param(
    [string]$Name,
    [int]$Port
  )

  $portProcessId = Get-ListeningProcessId -Port $Port
  if ($portProcessId -eq 0) {
    return
  }

  $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $portProcessId" -ErrorAction SilentlyContinue
  $commandLine = if ($processInfo) { [string]$processInfo.CommandLine } else { "" }
  if ($commandLine.IndexOf($repoRoot, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
    throw "Port $Port is already being used by another program. Close that program and run the launcher again."
  }

  Write-Host "  RESTART  stale $Name process on port $Port" -ForegroundColor Yellow
  & taskkill.exe /PID $portProcessId /T /F | Out-Null
  Start-Sleep -Milliseconds 500
}

function Wait-ForService {
  param(
    [string]$Name,
    [string]$Url,
    [int]$TimeoutSeconds = 60
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-HttpReady -Url $Url) {
      Write-Host "  OK  $Name" -ForegroundColor Green
      return
    }
    Start-Sleep -Milliseconds 500
  }

  throw "$Name did not start within $TimeoutSeconds seconds. Check the '$Name' terminal window for the error."
}

function Start-QAgentService {
  param(
    [string]$Title,
    [string]$NpmScript,
    [string]$ReadyUrl,
    [int]$Port
  )

  if (Test-HttpReady -Url $ReadyUrl) {
    Write-Host "  OK  $Title (already running)" -ForegroundColor Green
    return
  }

  Clear-StaleQAgentService -Name $Title -Port $Port
  $command = "title Q-Agent $Title && npm.cmd run $NpmScript"
  Start-Process -FilePath $env:ComSpec -ArgumentList @("/d", "/k", $command) -WorkingDirectory $repoRoot | Out-Null
  Wait-ForService -Name $Title -Url $ReadyUrl
}

try {
  Set-Location -LiteralPath $repoRoot

  if (Test-Path -LiteralPath $nodeInstallDir) {
    $env:Path = "$nodeInstallDir;$env:Path"
  }

  $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
  $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
  if (-not $nodeCommand -or -not $npmCommand) {
    throw "Node.js is not installed. Install the Windows LTS version from https://nodejs.org/ and run this file again."
  }

  Write-Step "1/5  Node.js $(& $nodeCommand.Source --version) found"

  $dependencyFiles = @(
    (Join-Path $repoRoot "node_modules\react\index.js"),
    (Join-Path $repoRoot "node_modules\next\package.json"),
    (Join-Path $repoRoot "node_modules\express\package.json")
  )
  $dependenciesReady = ($dependencyFiles | Where-Object { -not (Test-Path -LiteralPath $_) }).Count -eq 0

  if (-not $dependenciesReady) {
    Write-Step "2/5  Installing dependencies (first run only)"
    & $npmCommand.Source install
    if ($LASTEXITCODE -ne 0) {
      throw "npm install failed with exit code $LASTEXITCODE."
    }
  }
  else {
    Write-Step "2/5  Dependencies are ready"
  }

  Write-Step "3/5  Building the shared contract and backend services"
  & $npmCommand.Source run build:contracts
  if ($LASTEXITCODE -ne 0) { throw "Contract build failed." }
  & $npmCommand.Source run build -w @q-agent/extract
  if ($LASTEXITCODE -ne 0) { throw "Extract build failed." }
  & $npmCommand.Source run build -w @q-agent/engine
  if ($LASTEXITCODE -ne 0) { throw "Engine build failed." }

  $nextCache = Join-Path $repoRoot "apps\web\.next"
  if (Test-Path -LiteralPath $nextCache) {
    Remove-Item -LiteralPath $nextCache -Recurse -Force
  }

  Write-Step "4/5  Starting services"
  Start-QAgentService -Title "Extract" -NpmScript "start:extract" -ReadyUrl "http://localhost:4001/health" -Port 4001
  Start-QAgentService -Title "Engine" -NpmScript "start:engine" -ReadyUrl "http://localhost:4002/health" -Port 4002
  Start-QAgentService -Title "Web" -NpmScript "dev:web" -ReadyUrl $webUrl -Port 3000

  Write-Step "5/5  Everything is ready - opening the browser"
  Start-Process $webUrl
  Write-Host ""
  Write-Host "Q-Agent is running. Keep the three service windows open." -ForegroundColor Green
  Start-Sleep -Seconds 2
  exit 0
}
catch {
  Write-Host ""
  Write-Host "[Q-Agent] $($_.Exception.Message)" -ForegroundColor Red
  Write-Host "Ports used: Web 3000 / Extract 4001 / Engine 4002" -ForegroundColor Yellow
  exit 1
}
