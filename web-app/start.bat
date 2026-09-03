@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1

set "APP_DIR=%~dp0"
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

if not exist "%APP_DIR%frontend\dist\index.html" (
    echo Frontend build is missing. Running build.bat...
    call "%APP_DIR%build.bat"
    if errorlevel 1 (
        endlocal
        exit /b 1
    )
)

"%PYTHON_EXE%" -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
    echo Python dependencies are missing from the selected environment.
    echo Run bootstrap.bat, or set PYTHON_EXE to an environment that has requirements.txt installed.
    endlocal
    exit /b 1
)

for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":%APP_PORT% .*LISTENING"') do (
    echo Port %APP_PORT% is already in use by process %%p.
    echo Open http://127.0.0.1:%APP_PORT% if Video Factory is already running.
    endlocal
    exit /b 1
)

set "VIDEO_FACTORY_ENV=production"
set "VIDEO_FACTORY_RELOAD=0"
set "VIDEO_FACTORY_HOST=%APP_HOST%"
echo Video Factory: http://127.0.0.1:%APP_PORT%
pushd "%APP_DIR%"
"%PYTHON_EXE%" -m uvicorn main:app --host "%APP_HOST%" --port "%APP_PORT%"
set "EXIT_CODE=%ERRORLEVEL%"
popd
endlocal
exit /b %EXIT_CODE%
