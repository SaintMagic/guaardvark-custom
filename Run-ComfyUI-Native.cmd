@echo off
setlocal

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Run-ComfyUI-Native.ps1"

endlocal
