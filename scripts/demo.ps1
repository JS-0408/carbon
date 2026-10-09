$ErrorActionPreference = "Stop"
$venvUvi = Join-Path $PSScriptRoot "..\.venv\Scripts\uvicorn.exe"
& $venvUvi "backend.app.main:app" --host 127.0.0.1 --port 8000 --reload
