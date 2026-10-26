@echo off
setlocal
cd /d "%~dp0"
title PULSIA - Servidor de licencias
where py >nul 2>&1
if not errorlevel 1 (
    py -3 preparar_servidor.py
    goto fin
)
where python >nul 2>&1
if not errorlevel 1 (
    python preparar_servidor.py
    goto fin
)
echo Instale Python 3 de 64 bits con pip y Tcl/Tk desde python.org.
:fin
if errorlevel 1 pause
