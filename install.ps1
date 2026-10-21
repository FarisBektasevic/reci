# Reci — instalacija iz terminala (bez git-a, bez Python-a).
#   irm https://raw.githubusercontent.com/FarisBektasevic/reci/main/install.ps1 | iex
# Skine poslednji Reci.exe sa GitHub Releases u %LOCALAPPDATA%\Programs\Reci, napravi prečicu
# u Start meniju i pokrene ga. Prvo pokretanje pita za Groq ključ i autostart.
# Deinstalacija: obriši %LOCALAPPDATA%\Programs\Reci i %LOCALAPPDATA%\reci (ključ, log) + shell:startup\Reci.lnk

$ErrorActionPreference = 'Stop'
$repo = 'FarisBektasevic/reci'
$dir = Join-Path $env:LOCALAPPDATA 'Programs\Reci'
$exe = Join-Path $dir 'Reci.exe'

Write-Host "Reci — diktat na srpskom" -ForegroundColor Cyan
Write-Host "Tražim poslednju verziju..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$rel = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -Headers @{ 'User-Agent' = 'reci-install' }
$asset = $rel.assets | Where-Object name -eq 'Reci.exe' | Select-Object -First 1
if (-not $asset) { throw "U release-u $($rel.tag_name) nema Reci.exe" }

# ugasi stari ako radi
Get-Process Reci -ErrorAction SilentlyContinue | Stop-Process -Force

New-Item -ItemType Directory -Force $dir | Out-Null
Write-Host "Skidam $($rel.tag_name) ($([math]::Round($asset.size/1MB)) MB)..."
Invoke-WebRequest $asset.browser_download_url -OutFile $exe -UseBasicParsing
Unblock-File $exe -ErrorAction SilentlyContinue

# prečica u Start meniju
$lnk = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Reci.lnk'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = $exe; $s.WorkingDirectory = $dir; $s.Description = 'Reci - diktat na srpskom (drzi desni Ctrl)'; $s.Save()

Write-Host "Instalirano u $dir" -ForegroundColor Green
Write-Host "Pokrećem... (prvi put pita za Groq ključ — besplatno na console.groq.com — i za autostart)"
Start-Process $exe -WorkingDirectory $dir
