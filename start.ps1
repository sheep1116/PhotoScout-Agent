param([switch]$Install)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:NEXT_TELEMETRY_DISABLED = '1'
$env:LANGSMITH_TRACING = 'false'
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { py -3.12 -m venv .venv; if ($LASTEXITCODE) { throw 'Python 3.12 is required.' } }
if ($Install) {
    & '.venv/Scripts/python.exe' -m pip install -r requirements.lock
    if ($LASTEXITCODE) { throw 'Python dependency installation failed.' }
    & '.venv/Scripts/python.exe' -m pip install --no-deps -e .
    Push-Location frontend
    try { npm ci; if ($LASTEXITCODE) { throw 'npm ci failed.' } } finally { Pop-Location }
}
if (-not (Test-Path -LiteralPath 'frontend/node_modules/next/dist/bin/next')) { throw 'First run: .\start.ps1 -Install' }
New-Item -ItemType Directory -Path '.run' -Force | Out-Null
foreach ($port in @(8000,3800)) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { throw "Port $port is already in use. Existing services have not been stopped." }
}
$backend = Start-Process -FilePath (Join-Path $PSScriptRoot '.venv/Scripts/python.exe') -ArgumentList '-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput '.run/backend.log' -RedirectStandardError '.run/backend.err.log'
$frontend = Start-Process -FilePath (Get-Command node.exe).Source -ArgumentList 'node_modules/next/dist/bin/next','dev','--hostname','127.0.0.1','--port','3800' -WorkingDirectory (Join-Path $PSScriptRoot 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput '.run/frontend.log' -RedirectStandardError '.run/frontend.err.log'
@{backend=$backend.Id; frontend=$frontend.Id; backendStarted=$backend.StartTime.ToString('o'); frontendStarted=$frontend.StartTime.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath '.run/processes.json'
for ($attempt=0; $attempt -lt 30; $attempt++) {
    try {
        $ready = Invoke-WebRequest -Uri 'http://127.0.0.1:3800/v1/health' -TimeoutSec 2
        if ($ready.StatusCode -eq 200) { break }
    } catch { Start-Sleep -Milliseconds 500 }
}
if (-not $ready -or $ready.StatusCode -ne 200) { throw 'Startup did not become healthy. See .run/*.log; stop with .\stop.ps1 before retrying.' }
Write-Host 'PhotoScout ready at http://127.0.0.1:3800'
Write-Host 'Logs: .run/  Stop with .\stop.ps1'
