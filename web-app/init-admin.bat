@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1

set "APP_DIR=%~dp0"
set "VENV_PYTHON=%APP_DIR%..\.venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%VENV_PYTHON%" set "PYTHON_EXE=%VENV_PYTHON%"
if not defined PYTHON_EXE if defined VIRTUAL_ENV if exist "%VIRTUAL_ENV%\Scripts\python.exe" set "PYTHON_EXE=%VIRTUAL_ENV%\Scripts\python.exe"
if not defined PYTHON_EXE set "PYTHON_EXE=python"

if /i "%PYTHON_EXE%"=="python" (
    where python >nul 2>&1
    if errorlevel 1 (
        echo Python was not found on PATH. Run bootstrap.bat first.
        endlocal
        exit /b 1
    )
) else if not exist "%PYTHON_EXE%" (
    echo Python executable was not found: %PYTHON_EXE%
    endlocal
    exit /b 1
)

pushd "%APP_DIR%"
"%PYTHON_EXE%" scripts\init_admin.py %*
set "EXIT_CODE=%ERRORLEVEL%"
popd
endlocal
exit /b %EXIT_CODE%
