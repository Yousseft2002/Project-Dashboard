@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (py -3 "%~dp0install.py" & goto :done)
for /f "delims=" %%P in ('where python 2^>nul') do (
  echo %%P | find /i "WindowsApps" >nul || ("%%P" "%~dp0install.py" & goto :done)
)
echo Python 3 is not installed on this PC.
echo Install it with:   winget install Python.Python.3.13
echo or from https://www.python.org/downloads/ , then run this file again.
:done
echo.
pause
