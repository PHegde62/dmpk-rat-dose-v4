<#
  run_app.ps1 - one-command local launcher for the DMPK Predictor (Windows).

  No cloud, no Nucleus access required. Creates a local virtual environment,
  installs the (light) app dependencies, and opens the Streamlit app in your
  browser at http://localhost:8501.

  Usage (from the dmpk-predictor-v2 folder):
    .\run_app.ps1                         # full worksheet app (app.py)
    .\run_app.ps1 -App models\dose_method_app.py   # dose-engine selector UI

  First run installs packages (a few minutes, mostly RDKit); later runs are fast.
  If PowerShell blocks the script:  Set-ExecutionPolicy -Scope Process -Bypass
#>
param(
  [string]$App = "app.py",
  [int]$Port = 8501
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "Python not found. Install Python 3.10+ from python.org (check 'Add to PATH')."
}

if (-not (Test-Path ".venv")) {
  Write-Host "==> Creating virtual environment (.venv) ..." -ForegroundColor Cyan
  python -m venv .venv
}
$py = Join-Path ".venv" "Scripts\python.exe"

Write-Host "==> Installing dependencies (first run only) ..." -ForegroundColor Cyan
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r requirements.txt --quiet

Write-Host ("==> Launching " + $App + " at http://localhost:" + $Port + " (Ctrl+C to stop)") -ForegroundColor Green
& $py -m streamlit run $App --server.port $Port
