@echo off
setlocal
chcp 65001 >nul 2>&1

set "APP_DIR=%~dp0"
set "FRONTEND_DIR=%APP_DIR%frontend"

echo ==============================================
echo Video Factory - Development
echo ==============================================
echo.

echo Starting backend...
start "Video Factory Backend" /D "%APP_DIR%" cmd /k python -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload
echo Backend:  http://127.0.0.1:8001
echo.

echo Starting frontend...
start "Video Factory Frontend" /D "%FRONTEND_DIR%" cmd /k npm run dev
echo Frontend: http://localhost:5173
echo.

echo Both services are starting in separate windows.
echo Close those windows to stop the services.
echo.

endlocal
