@echo off
setlocal
chcp 65001 >nul 2>&1

set "APP_DIR=%~dp0"

echo ==============================================
echo Video Factory - Initial Admin
echo ==============================================
echo.
echo Username: admin
echo Password: 12345678
echo.

pushd "%APP_DIR%"
python scripts\init_admin.py --username admin --password 12345678 --display-name admin
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Initial admin setup failed with code %EXIT_CODE%.
    pause
)

endlocal
exit /b %EXIT_CODE%
