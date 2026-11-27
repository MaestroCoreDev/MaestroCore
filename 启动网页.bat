@echo off
setlocal
title MaestroCore server

if exist "C:\Users\A\Desktop\MaestroCore\api_server\server.py" (
  cd /d "C:\Users\A\Desktop\MaestroCore"
) else (
  cd /d "%~dp0"
)

set "PY=C:\Users\A\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PY%" set "PY="
if not defined PY where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopy

if not exist "api_server\server.py" goto nofile

echo ========================================
echo      MaestroCore local web server
echo ========================================
echo   URL:   http://127.0.0.1:8765/
echo   Keep this window open. Closing it stops the service.
echo   The browser should open by itself; if not, paste the URL above.
echo ----------------------------------------
echo.

"%PY%" -u "api_server\server.py" --host 0.0.0.0

echo.
echo Server stopped. If the browser could not open it, screenshot this window.
pause
goto :eof

:nopy
echo [ERROR] Python not found. Expected Python 3.11.
pause
goto :eof

:nofile
echo [ERROR] api_server\server.py not found. Was the project moved?
pause
goto :eof
