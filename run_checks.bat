@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo [1/3] Running Pytest Unit Tests...
echo ===================================================
call "%~dp0.venv\Scripts\pytest.exe"
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Pytest failed with exit code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)

echo.
echo ===================================================
echo [2/3] Checking Ruff Lint Rules...
echo ===================================================
call "%~dp0.venv\Scripts\ruff.exe" check .
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Ruff lint failed with exit code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)

echo.
echo ===================================================
echo [3/3] Checking Ruff Formatting...
echo ===================================================
call "%~dp0.venv\Scripts\ruff.exe" format --check .
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Ruff format check failed with exit code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)

echo.
echo ===================================================
echo [SUCCESS] All verification checks passed!
echo ===================================================
exit /b 0
