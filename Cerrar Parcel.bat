@echo off
setlocal
title Parcel - Cerrar aplicacion
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-parcel.ps1" -Mode Stop %*
if errorlevel 1 (
    echo.
    echo No se pudo completar el cierre. Revisa el mensaje de arriba.
    pause
    exit /b 1
)