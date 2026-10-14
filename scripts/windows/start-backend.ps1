$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..\..\backend')
conda run --no-capture-output -n media-tool python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
