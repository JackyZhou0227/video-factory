@echo off
setlocal
chcp 65001 >nul 2>&1

set "APP_DIR=%~dp0"

echo ==============================================
echo Video Factory
echo ==============================================
echo.
echo App: http://127.0.0.1:8001
echo.

pushd "%APP_DIR%"
python -m uvicorn main:app --host 0.0.0.0 --port 8001
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Video Factory exited with code %EXIT_CODE%.
    pause
)

endlocal
