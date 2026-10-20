@echo off
rem Gasi Reci koji radi u pozadini.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*reci.py*' -and $_.Name -like 'python*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Reci ugasen.
timeout /t 2 >nul
