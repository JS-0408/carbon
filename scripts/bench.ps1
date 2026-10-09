$ErrorActionPreference = "Stop"
$venvPy = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
& $venvPy -m backend.app.bench --compare
