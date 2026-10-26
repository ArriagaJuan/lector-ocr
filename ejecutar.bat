@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Proyecto laser - OCR y exportacion Excel

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "PYTHON_CMD="

echo ==============================================
echo        PROYECTO LASER - INICIO
echo ==============================================
echo.

if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys; assert sys.version_info[:2] in ((3,10),(3,11),(3,12),(3,13))" >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] El entorno .venv existente no es compatible.
        echo Renombra la carpeta .venv a .venv_anterior e intenta otra vez.
        goto :ERROR
    )
    echo [1/3] Entorno virtual existente detectado.
    goto :DEPENDENCIAS
)

echo [1/3] Buscando Python compatible ^(3.10 - 3.13^) ...

REM Prioridad: 3.11, 3.12, 3.10 y despues 3.13.
for %%V in (3.11 3.12 3.10 3.13) do (
    py -%%V -c "import sys; assert sys.version_info[:2] in ((3,10),(3,11),(3,12),(3,13))" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=py -%%V"
        goto :CREAR_ENTORNO
    )
)

REM Algunas instalaciones tienen Python en PATH pero no registrado con 'py'.
for %%C in (python python3) do (
    %%C -c "import sys; assert sys.version_info[:2] in ((3,10),(3,11),(3,12),(3,13))" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=%%C"
        goto :CREAR_ENTORNO
    )
)

echo.
echo [ERROR] No encuentro Python compatible en este equipo.
echo Instala Python 3.11 desde https://www.python.org/downloads/
echo Activa Add Python to PATH durante la instalacion.
echo Despues vuelve a ejecutar este archivo.
echo.
echo Diagnostico ^(versiones registradas^):
py -0p 2>nul
goto :ERROR

:CREAR_ENTORNO
echo Python seleccionado: %PYTHON_CMD%
echo Creando .venv ...
%PYTHON_CMD% -m venv .venv
if errorlevel 1 (
    echo [ERROR] Fallo la creacion del entorno virtual.
    goto :ERROR
)
if not exist "%VENV_PY%" (
    echo [ERROR] No se creo .venv\Scripts\python.exe.
    goto :ERROR
)

:DEPENDENCIAS
echo.
echo [2/3] Comprobando dependencias ...
"%VENV_PY%" -c "import cv2, numpy, openpyxl, PIL, rapidocr_onnxruntime" >nul 2>&1
if not errorlevel 1 goto :INICIAR

echo Instalando paquetes de requirements.txt ...
"%VENV_PY%" -m pip --version >nul 2>&1
if errorlevel 1 (
    "%VENV_PY%" -m ensurepip --upgrade
    if errorlevel 1 goto :ERROR
)
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] No fue posible instalar las dependencias.
    echo Verifica Internet y el error anterior.
    goto :ERROR
)

:INICIAR
echo.
echo [3/3] Abriendo interfaz ...
"%VENV_PY%" app.py
if errorlevel 1 (
    echo [ERROR] La aplicacion termino con error. Lee el mensaje anterior.
    goto :ERROR
)
exit /b 0

:ERROR
echo.
echo No se han modificado los videos originales.
pause
exit /b 1
