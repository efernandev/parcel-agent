@echo off
setlocal
title Parcel - Este PC
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-parcel.ps1" -Mode Local %*
if errorlevel 1 (
    echo.
    echo No se pudo iniciar Parcel. Revisa el mensaje de arriba.
    pause
    exit /b 1
)