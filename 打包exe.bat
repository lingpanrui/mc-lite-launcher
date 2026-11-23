@echo off
cd /d "%~dp0"
echo Installing PyInstaller if needed...
python -m pip install --upgrade pyinstaller
if errorlevel 1 goto :err
echo Building MCLite.exe ...
python -m PyInstaller --noconfirm --clean --onefile --windowed --name MCLite main.py
if errorlevel 1 goto :err
echo.
echo Done: dist\MCLite.exe
pause
exit /b
:err
echo Build failed. Check the messages above.
pause
