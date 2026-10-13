param([string]$OutputDirectory = ('release-' + (Get-Date -Format 'yyyyMMdd-HHmmss')))
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --onedir --windowed --distpath $OutputDirectory --name 'RugBuster Live Desk' --icon assets\shield.ico --add-data 'web;web' --add-data 'assets;assets' --collect-all webview --collect-all pystray desktop.py
if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed' }
