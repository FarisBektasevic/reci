@echo off
rem Pravi dist\Reci.exe (jedan fajl, bez konzole). Treba: pip install pyinstaller
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --onefile --noconsole --name Reci ^
  --collect-all speech_recognition ^
  --collect-all sounddevice ^
  --hidden-import keyboard ^
  reci.py
if errorlevel 1 (echo BUILD NIJE USPEO & exit /b 1)
echo.
echo Gotovo: dist\Reci.exe
