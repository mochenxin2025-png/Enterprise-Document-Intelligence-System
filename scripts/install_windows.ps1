# EDIS Windows Install Script
# Run: .\scripts\install_windows.ps1

Write-Host "EDIS Windows Installer" -ForegroundColor Cyan

# Check Python
python --version 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Python 3.10+ required. Install from https://python.org" -ForegroundColor Red
    exit 1
}

# Create venv
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    Write-Host "Created .venv" -ForegroundColor Green
}

# Activate & install
.\.venv\Scripts\activate
pip install uv
uv pip install -r requirements-base.txt
uv pip install -r requirements-windows.txt

Write-Host "EDIS installed. Run: .venv\Scripts\python main.py" -ForegroundColor Green
