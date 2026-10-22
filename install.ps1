# Reci — instalacija iz terminala (bez git-a, bez Python-a).
#   irm https://raw.githubusercontent.com/FarisBektasevic/reci/main/install.ps1 | iex
# Skine poslednji Reci.zip sa GitHub Releases, proveri SHA-256, raspakuje u %LOCALAPPDATA%\Programs\Reci,
# napravi prečicu u Start meniju i pokrene. Prvo pokretanje pita za Groq ključ i autostart.
# Deinstalacija: obriši %LOCALAPPDATA%\Programs\Reci i %LOCALAPPDATA%\reci (ključ, log) + shell:startup\Reci.lnk

$ErrorActionPreference = 'Stop'
$repo = 'FarisBektasevic/reci'
$dir = Join-Path $env:LOCALAPPDATA 'Programs\Reci'
$exe = Join-Path $dir 'Reci.exe'
$tmp = Join-Path $env:TEMP 'Reci.zip'

Write-Host "Reci — diktat na srpskom" -ForegroundColor Cyan
Write-Host "Tražim poslednju verziju..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$rel = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -Headers @{ 'User-Agent' = 'reci-install' }
$zip = $rel.assets | Where-Object name -eq 'Reci.zip' | Select-Object -First 1
$sha = $rel.assets | Where-Object name -eq 'Reci.zip.sha256' | Select-Object -First 1
if (-not $zip) { throw "U release-u $($rel.tag_name) nema Reci.zip" }

Write-Host "Skidam $($rel.tag_name) ($([math]::Round($zip.size/1MB)) MB)..."
Invoke-WebRequest $zip.browser_download_url -OutFile $tmp -UseBasicParsing

if ($sha) {
    $raw = (Invoke-WebRequest $sha.browser_download_url -UseBasicParsing).Content
    if ($raw -is [byte[]]) { $raw = [Text.Encoding]::ASCII.GetString($raw) }   # GitHub ga šalje kao octet-stream
    $expected = ($raw.Trim() -split '\s+')[0].ToLower()
    $actual = (Get-FileHash $tmp -Algorithm SHA256).Hash.ToLower()
    if ($expected -ne $actual) { Remove-Item $tmp; throw "SHA-256 se ne poklapa — fajl je oštećen ili izmenjen. Prekidam." }
    Write-Host "SHA-256 u redu."
}

# ugasi stari ako radi, pa zameni folder
Get-Process Reci -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500
if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
New-Item -ItemType Directory -Force $dir | Out-Null
Expand-Archive $tmp -DestinationPath $dir -Force
Remove-Item $tmp
Get-ChildItem $dir -Recurse | Unblock-File -ErrorAction SilentlyContinue

# prečica u Start meniju
$lnk = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Reci.lnk'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = $exe; $s.WorkingDirectory = $dir; $s.IconLocation = $exe; $s.Description = 'Reci - diktat na srpskom (drzi desni Ctrl)'; $s.Save()

Write-Host "Instalirano u $dir" -ForegroundColor Green
Write-Host "Pokrećem... (prvi put pita za Groq ključ — besplatno na console.groq.com — i za autostart)"
Start-Process $exe -WorkingDirectory $dir
