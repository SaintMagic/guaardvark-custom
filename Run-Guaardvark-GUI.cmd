@echo off
setlocal

set "PS_SCRIPT=%~dp0Run-Guaardvark-GUI.ps1"
set "VBS_LAUNCHER=%TEMP%\guaardvark-launcher-gui.vbs"

>"%VBS_LAUNCHER%" echo Set WshShell = CreateObject("WScript.Shell")
>>"%VBS_LAUNCHER%" echo WshShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""%PS_SCRIPT%""", 0, False

wscript.exe "%VBS_LAUNCHER%"
del "%VBS_LAUNCHER%" >nul 2>&1

endlocal
