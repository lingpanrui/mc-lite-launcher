@echo off
cd /d "%~dp0"
for %%D in ("%LOCALAPPDATA%\Programs\Python\Python312" "%LOCALAPPDATA%\Programs\Python\Python313" "%LOCALAPPDATA%\Programs\Python\Python314" "%LOCALAPPDATA%\Programs\Python\Python310" "%ProgramFiles%\Python312" "%ProgramFiles%\Python311") do (
    if exist "%%~D\pythonw.exe" (
        start "" "%%~D\pythonw.exe" main.py
        exit /b
    )
)
where pyw.exe >nul 2>nul
if not errorlevel 1 (
    start "" pyw.exe main.py
    exit /b
)
where pythonw.exe >nul 2>nul
if not errorlevel 1 (
    start "" pythonw.exe main.py
    exit /b
)
where python.exe >nul 2>nul
if not errorlevel 1 (
    start "" python.exe main.py
    exit /b
)
echo Python 3.10+ not found. Install Python, then run this file again.
pause
