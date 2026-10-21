@echo off
rem Pravi dist\Reci\ (folder, ne jedan exe) + dist\Reci.zip + SHA-256. Treba: pip install pyinstaller
rem Folder umesto onefile, bez UPX-a, sa ikonicom i metapodacima — sve to smanjuje lažne alarme antivirusa.
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --onedir --noconsole --noupx --name Reci ^
  --icon reci.ico --version-file version_info.txt ^
  --collect-all speech_recognition ^
  --collect-all sounddevice ^
  reci.py
if errorlevel 1 (echo BUILD NIJE USPEO & exit /b 1)
copy /y recnik.txt dist\Reci\ >nul
copy /y pojmovi.txt dist\Reci\ >nul
if exist dist\Reci.zip del dist\Reci.zip
powershell -NoProfile -Command "Compress-Archive -Path 'dist\Reci\*' -DestinationPath 'dist\Reci.zip' -CompressionLevel Optimal; (Get-FileHash 'dist\Reci.zip' -Algorithm SHA256).Hash.ToLower() + '  Reci.zip' | Set-Content 'dist\Reci.zip.sha256' -Encoding ascii; Get-Content 'dist\Reci.zip.sha256'"
echo.
echo Gotovo: dist\Reci\Reci.exe, dist\Reci.zip, dist\Reci.zip.sha256
