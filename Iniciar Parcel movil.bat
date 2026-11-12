@echo off
setlocal
title Parcel - Acceso privado desde movil
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-parcel.ps1" -Mode Private %*
if errorlevel 1 (
    echo.
    echo No se pudo activar el acceso privado. Revisa el mensaje de arriba.
    pause
    exit /b 1
)