@echo off
setlocal
title Parcel - Desactivar acceso privado
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-parcel.ps1" -Mode DisablePrivate
echo.
pause