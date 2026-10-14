$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..\frontend')
nvm use 24
npm run dev
