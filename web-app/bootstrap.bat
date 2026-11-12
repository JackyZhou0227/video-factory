@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1

set "APP_DIR=%~dp0"
for %%I in ("%APP_DIR%..\.venv") do set "VENV_DIR=%%~fI"
rem Support both layouts: python -m venv (Scripts\python.exe) and conda/envs (python.exe at root).
set "PYTHON_EXE="
if exist "%VENV_DIR%\Scripts\python.exe" set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%VENV_DIR%\python.exe" set "PYTHON_EXE=%VENV_DIR%\python.exe"

echo ==============================================
echo Video Factory - Bootstrap
echo ==============================================
echo.

if defined PYTHON_EXE goto :python_ready
if exist "%VENV_DIR%" goto :unusable_venv

echo Creating virtual environment: %VENV_DIR%
set "VENV_CREATOR="
where py >nul 2>&1
if not errorlevel 1 set "VENV_CREATOR=py -3 -m venv"
if not defined VENV_CREATOR (
    where python >nul 2>&1
    if errorlevel 1 goto :no_python
    set "VENV_CREATOR=python -m venv"
)
%VENV_CREATOR% "%VENV_DIR%"
if errorlevel 1 goto :venv_failed
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

:python_ready
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

:unusable_venv
echo Found a directory that is not a usable Python environment:
echo   %VENV_DIR%
echo Remove that directory, then run bootstrap again.
endlocal
exit /b 1

:no_python
echo Python was not found on PATH.
endlocal
exit /b 1

:venv_failed
echo Failed to create the virtual environment.
endlocal
exit /b 1
