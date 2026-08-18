@echo off
setlocal
chcp 65001 >nul 2>&1

set "APP_DIR=%~dp0"

echo ==============================================
echo Video Factory - Initial Admin
echo ==============================================
echo.
echo Username: admin
echo Password: generated randomly and printed by the script.

pushd "%APP_DIR%"
python scripts\init_admin.py --username admin --display-name admin
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Initial admin setup failed with code %EXIT_CODE%.
    pause
)

endlocal
exit /b %EXIT_CODE%
