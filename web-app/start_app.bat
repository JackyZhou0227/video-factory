@echo off
setlocal
chcp 65001 >nul 2>&1

set "APP_DIR=%~dp0"
set "APP_PORT=18888"
set "FRONTEND_DIST=%APP_DIR%frontend\dist"

echo ==============================================
echo Video Factory - App
echo ==============================================
echo.
echo Frontend + API: http://127.0.0.1:%APP_PORT%
echo.

if not exist "%FRONTEND_DIST%\index.html" (
    echo Frontend build not found:
    echo %FRONTEND_DIST%\index.html
    echo.
    echo Please build the frontend before running this app:
    echo cd /d "%APP_DIR%frontend"
    echo npm install
    echo npm run build
    echo.
    pause
    endlocal
    exit /b 1
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
python -m uvicorn main:app --host 0.0.0.0 --port %APP_PORT%
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Video Factory exited with code %EXIT_CODE%.
    pause
)

endlocal
