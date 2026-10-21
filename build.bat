@echo off
rem Pravi dist\Reci\ (folder, ne jedan exe) + dist\Reci.zip + SHA-256. Treba: pip install pyinstaller
rem Folder umesto onefile, bez UPX-a, sa ikonicom i metapodacima — sve to smanjuje lažne alarme antivirusa.
cd /d "%~dp0"
rem speech_recognition: ne --collect-all (vuče 40+ MB i tuđe pakete), nego samo flac binarni za Google rezervu
python -c "import speech_recognition as s,os;open('sr_path.tmp','w').write(os.path.dirname(s.__file__))"
set /p SR=<sr_path.tmp
del sr_path.tmp
echo speech_recognition: %SR%
python -m PyInstaller --noconfirm --clean --onedir --noconsole --noupx --name Reci ^
  --icon reci.ico --version-file version_info.txt ^
  --add-binary "%SR%\flac-win32.exe;speech_recognition" ^
  --collect-all sounddevice ^
  --exclude-module pandas --exclude-module PIL --exclude-module grpc --exclude-module cryptography ^
  --exclude-module lxml --exclude-module jedi --exclude-module parso --exclude-module IPython ^
  --exclude-module matplotlib --exclude-module scipy --exclude-module pygments --exclude-module google ^
  --exclude-module pytest --exclude-module setuptools --exclude-module pkg_resources ^
  reci.py
if errorlevel 1 (echo BUILD NIJE USPEO & exit /b 1)
rem PyInstaller hook za speech_recognition ubaci i offline engleski model (38 MB) + Linux/Mac flac — ne treba
rmdir /s /q dist\Reci\_internal\speech_recognition\pocketsphinx-data 2>nul
del /q dist\Reci\_internal\speech_recognition\flac-linux-* dist\Reci\_internal\speech_recognition\flac-mac 2>nul
copy /y recnik.txt dist\Reci\ >nul
copy /y pojmovi.txt dist\Reci\ >nul
if exist dist\Reci.zip del dist\Reci.zip
powershell -NoProfile -Command "Compress-Archive -Path 'dist\Reci\*' -DestinationPath 'dist\Reci.zip' -CompressionLevel Optimal; (Get-FileHash 'dist\Reci.zip' -Algorithm SHA256).Hash.ToLower() + '  Reci.zip' | Set-Content 'dist\Reci.zip.sha256' -Encoding ascii; Get-Content 'dist\Reci.zip.sha256'"
echo.
echo Gotovo: dist\Reci\Reci.exe, dist\Reci.zip, dist\Reci.zip.sha256
