@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1

set "APP_DIR=%~dp0"
set "VENV_DIR=%APP_DIR%..\.venv"
set "PYTHON_EXE="

if exist "%VENV_DIR%\Scripts\python.exe" set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%VENV_DIR%\python.exe" set "PYTHON_EXE=%VENV_DIR%\python.exe"

if not defined PYTHON_EXE (
    where python >nul 2>&1
    if errorlevel 1 (
        echo Python was not found on PATH.
        endlocal
        exit /b 1
    )

    echo Creating virtual environment: %VENV_DIR%
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo Failed to create the virtual environment.
        endlocal
        exit /b 1
    )
    set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
)

echo Activating virtual environment: %VENV_DIR%
call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 (
    echo Failed to activate the virtual environment.
    endlocal
    exit /b 1
)

set "READY_MARKER=%VENV_DIR%\.video_factory_requirements_ready"
if not exist "%READY_MARKER%" (
    echo Installing Python dependencies...
    "%PYTHON_EXE%" -m pip install -r "%APP_DIR%requirements.txt"
    if errorlevel 1 (
        echo Failed to install Python dependencies.
        endlocal
        exit /b 1
    )
    >"%READY_MARKER%" echo requirements installed
)

echo Using Python: %PYTHON_EXE%
call "%APP_DIR%start_app.bat"
set "EXIT_CODE=%ERRORLEVEL%"

endlocal
exit /b %EXIT_CODE%
