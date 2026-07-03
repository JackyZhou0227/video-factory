@echo off
setlocal
chcp 65001 >nul 2>&1

set "APP_DIR=%~dp0"
set "FRONTEND_DIR=%APP_DIR%frontend"

echo ==============================================
echo Video Factory - Frontend
echo ==============================================
echo.
echo Frontend: http://localhost:5173
echo.

pushd "%FRONTEND_DIR%"
npm run dev
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Frontend exited with code %EXIT_CODE%.
    pause
)

endlocal
