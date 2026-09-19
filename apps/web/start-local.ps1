$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$webUrl = "http://localhost:3000"
$nodeInstallDir = Join-Path $env:ProgramFiles "nodejs"
$realtimeDir = Join-Path $repoRoot "services\realtime"
$realtimeEnvFile = Join-Path $realtimeDir ".env"
$realtimeVenvDir = Join-Path $realtimeDir ".venv"
$realtimePython = Join-Path $realtimeVenvDir "Scripts\python.exe"
$realtimeServer = Join-Path $realtimeVenvDir "Scripts\q-agent-realtime-server.exe"

function Write-Step {
  param([string]$Message)
  Write-Host "[Q-Agent] $Message" -ForegroundColor Cyan
}

function Import-DotEnv {
  param([string]$Path)

  if (-not (Test-Path -LiteralPath $Path)) {
    return
  }

  foreach ($line in Get-Content -LiteralPath $Path) {
    if ($line -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
      continue
    }
    $name = $Matches[1]
    $value = $Matches[2].Trim()
    if (
      $value.Length -ge 2 -and
      (($value.StartsWith('"') -and $value.EndsWith('"')) -or
       ($value.StartsWith("'") -and $value.EndsWith("'")))
    ) {
      $value = $value.Substring(1, $value.Length - 2)
    }
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, "Process"))) {
      [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
  }
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

function Start-QAgentRealtime {
  $readyUrl = "http://127.0.0.1:8765/health"
  if (Test-HttpReady -Url $readyUrl) {
    Write-Host "  OK  Realtime API (already running)" -ForegroundColor Green
    return
  }

  Clear-StaleQAgentService -Name "Realtime API" -Port 8765
  $command = "title Q-Agent Realtime API && `"$realtimeServer`" --host 127.0.0.1 --port 8765"
  Start-Process -FilePath $env:ComSpec -ArgumentList @("/d", "/k", $command) -WorkingDirectory $repoRoot | Out-Null
  Wait-ForService -Name "Realtime API" -Url $readyUrl -TimeoutSeconds 90
}

try {
  Set-Location -LiteralPath $repoRoot

  # Shell variables take precedence, followed by the realtime and repository env files.
  Import-DotEnv -Path $realtimeEnvFile
  Import-DotEnv -Path (Join-Path $repoRoot ".env")

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
    (Join-Path $repoRoot "node_modules\next\package.json")
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

  Write-Step "3/5  Preparing the realtime API server"
  if (-not (Test-Path -LiteralPath $realtimePython)) {
    $systemPython = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $systemPython) {
      throw "Python 3.11 or 3.12 is required. Install Python and run this launcher again."
    }
    & $systemPython.Source -m venv $realtimeVenvDir
    if ($LASTEXITCODE -ne 0) { throw "Could not create the realtime Python environment." }
  }
  if (-not (Test-Path -LiteralPath $realtimeServer)) {
    & $realtimePython -m pip install -e $realtimeDir
    if ($LASTEXITCODE -ne 0) { throw "Realtime dependencies could not be installed." }
  }

  $llmProvider = if ($env:LLM_PROVIDER) { $env:LLM_PROVIDER.ToLowerInvariant() } else { "openai" }
  $sttProvider = if ($env:STT_PROVIDER) { $env:STT_PROVIDER.ToLowerInvariant() } else { "openai" }
  if (($llmProvider -eq "openai" -or $sttProvider -eq "openai") -and [string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
    throw "OpenAI API key is missing. Copy 'services\realtime\.env.example' to 'services\realtime\.env', put your key after OPENAI_API_KEY=, and run start-local.cmd again."
  }

  Write-Step "4/5  Building the shared web contract"
  & $npmCommand.Source run build:contracts
  if ($LASTEXITCODE -ne 0) { throw "Contract build failed." }

  Write-Step "5/5  Starting the realtime API and web app"
  Start-QAgentRealtime
  Start-QAgentService -Title "Web" -NpmScript "dev:web" -ReadyUrl $webUrl -Port 3000

  Write-Step "Everything is ready - opening the browser"
  Start-Process $webUrl
  Write-Host ""
  Write-Host "Q-Agent is running. Keep the Realtime API and Web windows open." -ForegroundColor Green
  Start-Sleep -Seconds 2
  exit 0
}
catch {
  Write-Host ""
  Write-Host "[Q-Agent] $($_.Exception.Message)" -ForegroundColor Red
  Write-Host "Ports used: Web 3000 / Realtime API 8765" -ForegroundColor Yellow
  exit 1
}
