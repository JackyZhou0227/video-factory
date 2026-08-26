@echo off
setlocal
chcp 65001 >nul 2>&1

set "APP_DIR=%~dp0"
if not defined DATABASE_URL (
    for /f "tokens=2,*" %%a in ('reg query "HKCU\Environment" /v DATABASE_URL 2^>nul') do set "DATABASE_URL=%%b"
)
set "PYTHON_EXE=python"
if not defined APP_HOST set "APP_HOST=127.0.0.1"
if not defined APP_PORT set "APP_PORT=18888"
set "VIDEO_FACTORY_ENV=production"
set "VIDEO_FACTORY_RELOAD=0"
set "FRONTEND_DIST=%APP_DIR%frontend\dist"
set "FRONTEND_DIR=%APP_DIR%frontend"

echo ==============================================
echo Video Factory - App
echo ==============================================
echo.
echo Frontend + API: http://%APP_HOST%:%APP_PORT%
echo.

if not exist "%FRONTEND_DIR%\package.json" (
    echo Frontend package.json was not found: %FRONTEND_DIR%
    endlocal
    exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
    echo npm was not found on PATH. Install Node.js before starting Video Factory.
    endlocal
    exit /b 1
)

if not exist "%FRONTEND_DIR%\node_modules" (
    echo Installing frontend dependencies...
    pushd "%FRONTEND_DIR%"
    call npm install
    set "NPM_EXIT_CODE=%ERRORLEVEL%"
    popd
    if not "%NPM_EXIT_CODE%"=="0" (
        echo Failed to install frontend dependencies.
        endlocal
        exit /b %NPM_EXIT_CODE%
    )
)

echo Building frontend...
pushd "%FRONTEND_DIR%"
call npm run build
set "BUILD_EXIT_CODE=%ERRORLEVEL%"
popd
if not "%BUILD_EXIT_CODE%"=="0" (
    echo Frontend build failed. Backend startup was skipped.
    endlocal
    exit /b %BUILD_EXIT_CODE%
)

for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":%APP_PORT% .*LISTENING"') do (
    echo Port %APP_PORT% is already in use by process %%p.
    echo.
    echo If Video Factory is already running, open:
    echo http://127.0.0.1:%APP_PORT%
    echo.
    echo To stop the existing process, run:
    echo taskkill /PID %%p /F
    echo.
    pause
    endlocal
    exit /b 1
)

pushd "%APP_DIR%"
where %PYTHON_EXE% >nul 2>&1
if errorlevel 1 (
    echo Python was not found on PATH. Activate the virtual environment first.
    popd
    endlocal
    exit /b 1
)
%PYTHON_EXE% -m uvicorn main:app --host %APP_HOST% --port %APP_PORT%
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Video Factory exited with code %EXIT_CODE%.
    pause
)

endlocal
