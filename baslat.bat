@echo off
setlocal
title Lumina AI
cd /d "%~dp0" || goto :failed
set "LUMINA_PYTHON=python"
if exist ".venv\Scripts\python.exe" set "LUMINA_PYTHON=%CD%\.venv\Scripts\python.exe"
"%LUMINA_PYTHON%" -u "%CD%\start_local.py" %*
if errorlevel 1 goto :failed
exit /b 0

:failed
echo Lumina AI baslatilamadi. Hata ayrintilari yukarida.
pause
exit /b 1
