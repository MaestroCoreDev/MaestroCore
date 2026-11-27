@echo off
setlocal
title MaestroCore recognizer

if exist "C:\Users\A\Desktop\MaestroCore\main_app\recognizer_gui.py" (
  cd /d "C:\Users\A\Desktop\MaestroCore"
) else (
  cd /d "%~dp0"
)

set "PY=C:\Users\A\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PY%" set "PY="
if not defined PY where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopy

if not exist "main_app\recognizer_gui.py" goto nofile

"%PY%" main_app\recognizer_gui.py
if errorlevel 1 pause
goto :eof

:nopy
echo [ERROR] Python not found. Expected Python 3.11.
pause
goto :eof

:nofile
echo [ERROR] main_app\recognizer_gui.py not found. Was the project moved?
pause
goto :eof
