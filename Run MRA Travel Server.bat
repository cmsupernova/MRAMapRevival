@echo off
REM Travel-link aware MRA server (Python 3.14 stub + teleports).
REM Use this instead of WINMRA\MRA_Server.exe when testing custom Links.
REM Stock MRA_Server.exe ignores travelLinks.

cd /d "%~dp0"
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3.14 run_mra_server.py
) else (
  "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" run_mra_server.py
)
if errorlevel 1 pause
