@echo off
cd /d "%~dp0"
if defined OPEN_CINEMA_PYTHON (
  "%OPEN_CINEMA_PYTHON%" app\launcher.py %*
) else (
  python app\launcher.py %*
)
if errorlevel 1 pause
