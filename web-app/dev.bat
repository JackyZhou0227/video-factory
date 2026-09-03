@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1

set "APP_DIR=%~dp0"
set "FRONTEND_DIR=%APP_DIR%frontend"
set "VENV_PYTHON=%APP_DIR%..\.venv\Scripts\python.exe"
if not defined APP_HOST set "APP_HOST=127.0.0.1"
if not defined APP_PORT set "APP_PORT=18888"
if not defined PYTHON_EXE if exist "%VENV_PYTHON%" set "PYTHON_EXE=%VENV_PYTHON%"
if not defined PYTHON_EXE if defined VIRTUAL_ENV if exist "%VIRTUAL_ENV%\Scripts\python.exe" set "PYTHON_EXE=%VIRTUAL_ENV%\Scripts\python.exe"
if not defined PYTHON_EXE set "PYTHON_EXE=python"

if /i "%PYTHON_EXE%"=="python" (
    where python >nul 2>&1
    if errorlevel 1 (
        echo Python was not found on PATH. Run bootstrap.bat or activate an environment first.
        endlocal
        exit /b 1
    )
) else if not exist "%PYTHON_EXE%" (
    echo Python executable was not found: %PYTHON_EXE%
    endlocal
    exit /b 1
)
if not exist "%FRONTEND_DIR%\node_modules" (
    echo Frontend dependencies are missing. Run bootstrap.bat first.
    endlocal
    exit /b 1
)

"%PYTHON_EXE%" -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
    echo Python dependencies are missing from the selected environment. Run bootstrap.bat first.
    endlocal
    exit /b 1
)

set "VIDEO_FACTORY_ENV=development"
set "VIDEO_FACTORY_RELOAD=1"
set "VIDEO_FACTORY_HOST=%APP_HOST%"
echo API:      http://%APP_HOST%:%APP_PORT%
echo Frontend: http://%APP_HOST%:5173
echo Close the API and frontend windows to stop development mode.

start "Video Factory API" /D "%APP_DIR%" "%PYTHON_EXE%" -m uvicorn main:app --host "%APP_HOST%" --port "%APP_PORT%" --reload
start "Video Factory Frontend" /D "%FRONTEND_DIR%" cmd /k npm run dev -- --host "%APP_HOST%"
endlocal
exit /b 0
