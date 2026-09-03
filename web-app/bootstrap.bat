@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1

set "APP_DIR=%~dp0"
for %%I in ("%APP_DIR%..\.venv") do set "VENV_DIR=%%~fI"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

echo ==============================================
echo Video Factory - Bootstrap
echo ==============================================
echo.

if not exist "%PYTHON_EXE%" (
    echo Creating virtual environment: %VENV_DIR%
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 -m venv "%VENV_DIR%"
    ) else (
        where python >nul 2>&1
        if errorlevel 1 (
            echo Python was not found on PATH.
            endlocal
            exit /b 1
        )
        python -m venv "%VENV_DIR%"
    )
    if errorlevel 1 (
        echo Failed to create the virtual environment.
        endlocal
        exit /b 1
    )
)

echo Installing Python dependencies...
"%PYTHON_EXE%" -m pip install -r "%APP_DIR%requirements.txt"
if errorlevel 1 (
    echo Failed to install Python dependencies.
    endlocal
    exit /b 1
)

if not exist "%APP_DIR%frontend\package.json" (
    echo Frontend package.json was not found.
    endlocal
    exit /b 1
)
where npm >nul 2>&1
if errorlevel 1 (
    echo npm was not found on PATH. Install Node.js before bootstrapping Video Factory.
    endlocal
    exit /b 1
)

echo Installing frontend dependencies...
pushd "%APP_DIR%frontend"
if exist package-lock.json (
    call npm ci
) else (
    call npm install
)
set "NPM_EXIT_CODE=%ERRORLEVEL%"
popd
if not "%NPM_EXIT_CODE%"=="0" (
    echo Failed to install frontend dependencies.
    endlocal
    exit /b %NPM_EXIT_CODE%
)

call "%APP_DIR%build.bat"
set "EXIT_CODE=%ERRORLEVEL%"
endlocal
exit /b %EXIT_CODE%
