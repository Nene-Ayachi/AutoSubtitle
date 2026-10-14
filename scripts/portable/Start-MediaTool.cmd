@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1" %*
if errorlevel 1 pause
endlocal
