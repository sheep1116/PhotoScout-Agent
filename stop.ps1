$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.run/processes.json')) { Write-Host 'No managed processes recorded.'; exit }
$record = Get-Content -LiteralPath '.run/processes.json' -Raw | ConvertFrom-Json
foreach ($name in @('backend','frontend')) {
    $taskProcess = Get-Process -Id $record.$name -ErrorAction SilentlyContinue
    $started = [datetime]$record."${name}Started"
    if ($taskProcess -and [Math]::Abs(($taskProcess.StartTime.ToUniversalTime() - $started.ToUniversalTime()).TotalSeconds) -lt 1) {
        # Only the recorded process tree from this local launcher is stopped.
        $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $($taskProcess.Id)"
        foreach ($child in $children) { Stop-Process -Id $child.ProcessId -ErrorAction SilentlyContinue }
        Stop-Process -Id $taskProcess.Id -ErrorAction SilentlyContinue
    }
}
Write-Host 'Managed PhotoScout processes stopped. Plan database preserved.'
