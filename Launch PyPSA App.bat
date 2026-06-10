@echo off
setlocal

cd /d "%~dp0"

set "HOST=127.0.0.1"
set "PORT=8765"
set "APP_URL=http://%HOST%:%PORT%/"

if /I "%~1"=="--check" (
  echo Launcher syntax check OK.
  exit /b 0
)

echo Starting PyPSA app from:
echo %CD%
echo.

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_CMD=.venv\Scripts\python.exe"
) else (
  where py >nul 2>nul
  if %ERRORLEVEL% EQU 0 (
    set "PYTHON_CMD=py -3"
  ) else (
    where python >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
      set "PYTHON_CMD=python"
    ) else (
      echo Python was not found on PATH.
      echo Install Python or create a .venv in this folder, then try again.
      echo.
      pause
      exit /b 1
    )
  )
)

start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process '%APP_URL%'"

echo Launching http://%HOST%:%PORT%/
echo Keep this window open while using the app.
echo Press Ctrl+C in this window to stop the app.
echo.

%PYTHON_CMD% csv_source_editor_app.py --host %HOST% --port %PORT%

echo.
echo App stopped.
pause
