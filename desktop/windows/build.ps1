$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment' }
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Could not install build dependencies' }
    & .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name DevelopAid --collect-all webview app.py
    if ($LASTEXITCODE -ne 0) { throw 'DevelopAid build failed' }
    Copy-Item README.md dist\DevelopAid\README.md
    Compress-Archive -Path dist\DevelopAid -DestinationPath dist\DevelopAid-Windows-x64.zip -Force
} finally {
    Pop-Location
}
