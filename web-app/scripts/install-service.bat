@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "APP_DIR=%%~fI"
for %%I in ("%APP_DIR%\..\.venv") do set "VENV_DIR=%%~fI"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "SERVICE_EXE=%SCRIPT_DIR%VideoFactory.exe"
set "WINSW_URL=https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe"

if /I "%~1"=="check" goto :check
if /I "%~1"=="uninstall" goto :uninstall
if not "%~1"=="" (
    echo Usage: install-service.bat [check^|uninstall]
    endlocal
    exit /b 1
)

net session >nul 2>&1
if errorlevel 1 (
    echo Run this script from an elevated Command Prompt.
    endlocal
    exit /b 1
)

call :check
if errorlevel 1 (
    endlocal
    exit /b 1
)

call :ensure_winsw
if errorlevel 1 (
    endlocal
    exit /b 1
)

if not exist "%SCRIPT_DIR%logs" mkdir "%SCRIPT_DIR%logs"

"%SERVICE_EXE%" status | findstr /I /C:"NonExistent" >nul
if not errorlevel 1 (
    "%SERVICE_EXE%" install
    if errorlevel 1 (
        endlocal
        exit /b 1
    )
) else (
    echo Video Factory service is already installed. Restarting it.
    "%SERVICE_EXE%" stop >nul 2>&1
)

"%SERVICE_EXE%" start
if errorlevel 1 (
    echo Service start failed. See %SCRIPT_DIR%logs
    endlocal
    exit /b 1
)

echo Video Factory service is running: http://127.0.0.1:18888
echo Logs: %SCRIPT_DIR%logs
endlocal
exit /b 0

:uninstall
net session >nul 2>&1
if errorlevel 1 (
    echo Run this script from an elevated Command Prompt.
    endlocal
    exit /b 1
)
if not exist "%SERVICE_EXE%" (
    echo WinSW executable was not found: %SERVICE_EXE%
    endlocal
    exit /b 1
)
"%SERVICE_EXE%" stop >nul 2>&1
"%SERVICE_EXE%" uninstall
set "EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %EXIT_CODE%

:ensure_winsw
if exist "%SERVICE_EXE%" exit /b 0
if exist "%SCRIPT_DIR%WinSW-x64.exe" (
    copy /Y "%SCRIPT_DIR%WinSW-x64.exe" "%SERVICE_EXE%" >nul
    if exist "%SERVICE_EXE%" exit /b 0
)
echo WinSW 2.12 x64 was not found.
echo Download %WINSW_URL%
echo Save it as %SERVICE_EXE%
echo Then run this script again from an elevated Command Prompt.
exit /b 1

:check
if not exist "%PYTHON_EXE%" (
    echo Python executable was not found: %PYTHON_EXE%
    echo Run scripts\bootstrap.bat first.
    exit /b 1
)
if not exist "%APP_DIR%\frontend\dist\index.html" (
    echo Frontend build is missing. Run scripts\build.bat first.
    exit /b 1
)
"%PYTHON_EXE%" -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
    echo Python dependencies are missing from the selected environment.
    echo Run scripts\bootstrap.bat first.
    exit /b 1
)
if not exist "%SCRIPT_DIR%VideoFactory.xml" (
    echo Service configuration was not found: %SCRIPT_DIR%VideoFactory.xml
    exit /b 1
)
exit /b 0
