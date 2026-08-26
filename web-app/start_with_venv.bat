@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1

set "APP_DIR=%~dp0"
for %%I in ("%APP_DIR%..\.venv") do set "VENV_DIR=%%~fI"
set "PYTHON_EXE="
set "ACTIVATE_SCRIPT=%VENV_DIR%\Scripts\activate.bat"

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

if exist "%ACTIVATE_SCRIPT%" (
    echo Activating virtual environment: %VENV_DIR%
    call "%ACTIVATE_SCRIPT%"
    if errorlevel 1 (
        echo Failed to activate the virtual environment.
        endlocal
        exit /b 1
    )
) else (
    echo Using existing environment directly: %VENV_DIR%
    set "PATH=%VENV_DIR%;%VENV_DIR%\Library\bin;%VENV_DIR%\Scripts;%VENV_DIR%\bin;%PATH%"
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
call "%APP_DIR%start_without_venv.bat"
set "EXIT_CODE=%ERRORLEVEL%"

endlocal
exit /b %EXIT_CODE%
