@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0xcli.exe" goto packaged
where py >nul 2>nul
if errorlevel 1 goto no_python
py -3 app.py %*
if errorlevel 1 pause
exit /b
:packaged
"%~dp0xcli.exe" %*
if errorlevel 1 pause
exit /b
:no_python
echo Python 3.10+ is required. Install Python with the Windows launcher enabled.
pause
exit /b 1
