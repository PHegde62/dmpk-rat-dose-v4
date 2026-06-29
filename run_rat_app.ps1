# Launch the V4 RAT Dose Predictor UI on its own port (8510) so it does NOT
# collide with any V1/V2/V3 app on the default 8501.
#
# It uses whatever Python in your shell already has the dependencies (e.g. your
# Anaconda 'base'), and only activates a local .venv if that venv actually has
# rdkit + streamlit. This avoids the "RDKit not installed" trap from an
# empty/broken .venv.
#
# Usage:  .\run_rat_app.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$Port = 8510

function Test-Deps($exe) {
    try { & $exe -c "import rdkit, streamlit, pandas, numpy, openpyxl, requests" 2>$null; return ($LASTEXITCODE -eq 0) }
    catch { return $false }
}

# 1) current interpreter on PATH (your activated conda env / base)
if (Test-Deps "python") {
    Write-Host "Using current Python. Open http://localhost:$Port" -ForegroundColor Green
    python -m streamlit run app_rat.py --server.port $Port
    return
}

# 2) a working local virtual environment, if present
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if ((Test-Path $venvPy) -and (Test-Deps $venvPy)) {
    Write-Host "Using .venv. Open http://localhost:$Port" -ForegroundColor Green
    & $venvPy -m streamlit run app_rat.py --server.port $Port
    return
}

Write-Host "Could not find a Python with the dependencies installed." -ForegroundColor Yellow
Write-Host "Activate the env that has them (e.g. 'conda activate base') or run:" -ForegroundColor Yellow
Write-Host "  pip install -r requirements.txt" -ForegroundColor Yellow
