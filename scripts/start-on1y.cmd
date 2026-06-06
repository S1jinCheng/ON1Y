@echo off
setlocal
cd /d "%~dp0.."
set "ON1Y_ROOT=%CD%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\start-on1y.ps1" %*
if errorlevel 1 exit /b 1
