@echo off
chcp 65001 >nul 2>&1

echo ==============================================
echo   Video Factory - 数字人口播视频
echo ==============================================
echo.
echo [1/2] Starting backend (FastAPI)...
start "Video Factory Backend" cmd /c "D:\Develop\anaconda3\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload"
echo   Backend running at http://127.0.0.1:8001
echo.

echo [2/2] Starting frontend (Vite dev)...
cd /d "%~dp0frontend"
start "Video Factory Frontend" cmd /c "npm run dev"
echo   Frontend running at http://localhost:5173
echo.

echo ==============================================
echo   Press any key to stop all services...
echo ==============================================
pause >nul 2>&1

taskkill /f /im python.exe /fi "IMAGENAME eq python.exe" 2>nul
taskkill /f /im node.exe /fi "IMAGENAME eq node.exe" 2>nul
echo All services stopped.
