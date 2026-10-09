param(
    [string]$Args = ""
)
$ErrorActionPreference = "Stop"
$venvPy = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
& $venvPy -m pytest backend/tests $Args
