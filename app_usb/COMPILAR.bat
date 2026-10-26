@echo off
setlocal
cd /d "%~dp0"
title PULSIA - Compilador del cliente EXE
where py >nul 2>&1
if not errorlevel 1 (
    py -3 compilar.py
    goto fin
)
where python >nul 2>&1
if not errorlevel 1 (
    python compilar.py
    goto fin
)
echo ERROR: Instale Python 3 de 64 bits desde python.org con Tcl/Tk y pip.
:fin
pause
