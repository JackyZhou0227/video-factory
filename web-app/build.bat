@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1

set "APP_DIR=%~dp0"
set "FRONTEND_DIR=%APP_DIR%frontend"

if not exist "%FRONTEND_DIR%\package.json" (
    echo Frontend package.json was not found: %FRONTEND_DIR%
    endlocal
    exit /b 1
)
where npm >nul 2>&1
if errorlevel 1 (
    echo npm was not found on PATH. Install Node.js first.
    endlocal
    exit /b 1
)
if not exist "%FRONTEND_DIR%\node_modules" (
    echo Frontend dependencies are missing. Run bootstrap.bat first.
    endlocal
    exit /b 1
)

echo Building frontend...
pushd "%FRONTEND_DIR%"
call npm run build
set "EXIT_CODE=%ERRORLEVEL%"
popd

if "%EXIT_CODE%"=="0" echo Frontend build completed: %FRONTEND_DIR%\dist
endlocal
exit /b %EXIT_CODE%
