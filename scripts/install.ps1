<#
.SYNOPSIS
Install everything the PR-UX Assurance Agent needs on Windows.

.DESCRIPTION
Always installed: Python 3.10+ (through winget when missing), the .venv virtual environment,
Python packages from requirements.txt, Playwright Chromium, and .env copied from .env.example.
Optional components are installed only when their switch is given.

.EXAMPLE
.\scripts\install.ps1
.\scripts\install.ps1 -WithEvaluation -WithOllama -Test
.\scripts\install.ps1 -All
#>
[CmdletBinding()]
param(
    [switch]$WithEvaluation,      # DeepEval advisory judge (requirements-evaluation.txt)
    [switch]$WithOllama,          # Ollama local model runtime
    [switch]$PullModel,           # download qwen2.5:7b into Ollama (about 4.7 GB); implies -WithOllama
    [switch]$WithK6,              # k6 for browser journeys and load profiles
    [switch]$WithLighthouse,      # Node.js LTS + Lighthouse CI (@lhci/cli)
    [switch]$WithObservability,   # Docker Desktop, observability/.env, Grafana stack images
    [switch]$All,                 # every optional component except -PullModel
    [switch]$Test,                # run the test suite after installing
    [string]$VenvDir = "",
    [string]$OllamaModel = "qwen2.5:7b"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $VenvDir) { $VenvDir = Join-Path $Root ".venv" }
if ($All) { $WithEvaluation = $WithOllama = $WithK6 = $WithLighthouse = $WithObservability = $true }
if ($PullModel) { $WithOllama = $true }

function Step([string]$Message) { Write-Host "`n==> $Message" -ForegroundColor Cyan }
function Have([string]$Name) { [bool](Get-Command $Name -ErrorAction SilentlyContinue) }
function Update-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}
function Invoke-Checked([string]$File, [string[]]$Arguments) {
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "'$File $($Arguments -join ' ')' failed with exit code $LASTEXITCODE" }
}
function Install-WithWinget([string]$Id, [string]$Command, [string]$Url) {
    if (Have $Command) { Write-Host "$Command is already installed"; return }
    if (-not (Have "winget")) { Write-Warning "winget is not available. Install $Id from $Url"; return }
    Invoke-Checked "winget" @("install", "--id", $Id, "-e", "--accept-source-agreements", "--accept-package-agreements")
    Update-Path
    if (-not (Have $Command)) { Write-Warning "$Command was installed but is not on PATH yet. Open a new terminal." }
}
function Find-Python {
    $candidates = @()
    if ($env:PYTHON) { $candidates += , @($env:PYTHON) }
    if (Have "py") { foreach ($version in "3.14", "3.13", "3.12", "3.11", "3.10") { $candidates += , @("py", "-$version") } }
    if (Have "python") { $candidates += , @("python") }
    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $pyArgs = @($candidate | Select-Object -Skip 1)
        try {
            & $exe @pyArgs -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return , $candidate }
        } catch { }
    }
    return $null
}

Step "Python 3.10+"
$python = Find-Python
if (-not $python) {
    Install-WithWinget "Python.Python.3.13" "py" "https://www.python.org/downloads/"
    $python = Find-Python
}
if (-not $python) { throw "Python 3.10 or newer is required. Install it from https://www.python.org/downloads/ and re-run." }
$pyExe = $python[0]
$pyArgs = @($python | Select-Object -Skip 1)
Write-Host "Using $($python -join ' ') ($(& $pyExe @pyArgs --version 2>&1))"

Step "Virtual environment: $VenvDir"
$venvPython = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    if (Test-Path (Join-Path $VenvDir "bin\python")) {
        throw "$VenvDir is a Linux/WSL virtual environment. Use scripts/install.sh there, or pass -VenvDir .venv-win."
    }
    Invoke-Checked $pyExe ($pyArgs + @("-m", "venv", $VenvDir))
}
Invoke-Checked $venvPython @("-m", "pip", "install", "--upgrade", "pip")

Step "Python packages"
Invoke-Checked $venvPython @("-m", "pip", "install", "-r", (Join-Path $Root "requirements.txt"))
if ($WithEvaluation) {
    Invoke-Checked $venvPython @("-m", "pip", "install", "-r", (Join-Path $Root "requirements-evaluation.txt"))
}

Step "Playwright Chromium"
Invoke-Checked $venvPython @("-m", "playwright", "install", "chromium")

Step "Configuration"
$envFile = Join-Path $Root ".env"
if (Test-Path $envFile) {
    Write-Host ".env already exists; left unchanged"
} else {
    Copy-Item (Join-Path $Root ".env.example") $envFile
    Write-Host "Created .env from .env.example. Set STAGE_PASSWORD (and OPENAI_API_KEY for live LLM runs) before running."
}

if ($WithOllama) {
    Step "Ollama"
    Install-WithWinget "Ollama.Ollama" "ollama" "https://ollama.com/download"
    if ($PullModel) {
        if (-not (Have "ollama")) { throw "Ollama is not on PATH; open a new terminal and run: ollama pull $OllamaModel" }
        Invoke-Checked "ollama" @("pull", $OllamaModel)
    }
}

if ($WithK6) {
    Step "k6"
    Install-WithWinget "GrafanaLabs.k6" "k6" "https://grafana.com/docs/k6/latest/set-up/install-k6/"
}

if ($WithLighthouse) {
    Step "Lighthouse CI"
    if (Have "lhci") {
        Write-Host "lhci is already installed"
    } else {
        Install-WithWinget "OpenJS.NodeJS.LTS" "npm" "https://nodejs.org"
        if (Have "npm") { Invoke-Checked "npm" @("install", "-g", "@lhci/cli") }
        else { Write-Warning "npm is not on PATH yet. Open a new terminal and run: npm install -g @lhci/cli" }
    }
}

if ($WithObservability) {
    Step "Observability stack"
    $obsEnv = Join-Path $Root "observability\.env"
    if (-not (Test-Path $obsEnv)) {
        $bytes = New-Object byte[] 18
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $password = [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_").TrimEnd("=")
        Set-Content -Path $obsEnv -Value "GRAFANA_ADMIN_PASSWORD=$password" -Encoding ascii
        Write-Host "Created observability\.env with a random Grafana admin password (read it from that file)."
    }
    Install-WithWinget "Docker.DockerDesktop" "docker" "https://docs.docker.com/desktop/"
    if (Have "docker") {
        & docker compose -f (Join-Path $Root "observability\compose.yaml") --env-file $obsEnv pull
        if ($LASTEXITCODE -ne 0) { Write-Warning "Could not pull the images. Start Docker Desktop and run: docker compose -f observability\compose.yaml pull" }
    }
}

Step "Verifying"
Invoke-Checked $venvPython @("-c", "import flask, playwright, pydantic, openai, mcp, langgraph, numpy, jinja2, openpyxl; print('Python packages import correctly')")
if ($Test) {
    Push-Location $Root
    try { Invoke-Checked $venvPython @("-m", "pytest", "-q") } finally { Pop-Location }
}

Write-Host @"

PR-UX Assurance Agent is installed.
Next steps:
  1. Edit .env and set STAGE_PASSWORD (OPENAI_API_KEY is optional; replay mode works without it).
  2. .venv\Scripts\Activate.ps1
  3. python -m agent ingest
  4. python -m agent run --all --start-stage
"@
