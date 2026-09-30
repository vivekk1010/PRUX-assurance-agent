param(
    [string]$Model = "qwen2.5:7b",
    [switch]$Pull
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

$OllamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
$Ollama = if ($OllamaCommand) {
    $OllamaCommand.Source
} else {
    Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
}
if (-not (Test-Path $Ollama)) {
    throw "Ollama is not installed. Install it from https://ollama.com/download or run: winget install Ollama.Ollama"
}
if (-not (Test-Path $Python)) {
    throw "Virtual environment is missing. Run: python -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements.txt"
}

try {
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
} catch {
    Start-Process -FilePath $Ollama -ArgumentList "serve" -WindowStyle Hidden
    $ready = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
            $ready = $true
            break
        } catch {}
    }
    if (-not $ready) {
        throw "Ollama did not become ready at http://127.0.0.1:11434"
    }
}

$installed = & $Ollama list |
    Select-Object -Skip 1 |
    ForEach-Object { ($_ -split "\s+")[0] }
if ($installed -notcontains $Model) {
    if ($Pull) {
        & $Ollama pull $Model
    } else {
        throw "Model '$Model' is not installed. Re-run with -Pull or execute: ollama pull $Model"
    }
}

$env:REQUIREMENTS_ALCHEMIST_CONFIG = Join-Path $Root "config\requirements-alchemist.ollama.json"
$env:RA_LLM_PROVIDER = "openai-compatible"
$env:RA_LLM_BASE_URL = "http://127.0.0.1:11434/v1"
$env:RA_LLM_MODEL = $Model

Write-Host "Starting Requirements Alchemist with local Ollama model $Model"
Write-Host "Open http://127.0.0.1:5070"
& $Python -m requirements_alchemist
