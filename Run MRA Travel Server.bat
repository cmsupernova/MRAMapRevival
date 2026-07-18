@echo off
REM Prefer frozen travel server (stock speed). Falls back to Python 3.14 launcher.
cd /d "%~dp0"

if exist "WINMRA\MRA_Server_Travel.exe" (
  echo Starting WINMRA\MRA_Server_Travel.exe
  start "" "WINMRA\MRA_Server_Travel.exe"
  exit /b 0
)

echo MRA_Server_Travel.exe not found — using Python launcher.
echo Tip: py -3.14 patch_mra_server_travel.py
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3.14 run_mra_server.py
) else (
  "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" run_mra_server.py
)
if errorlevel 1 pause
