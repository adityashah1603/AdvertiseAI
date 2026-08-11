# Finds and stops whatever's running dispatcher.py --serve, regardless of
# which python started it (the WindowsApps-alias mistake this script exists
# to make easy to recover from, or a correctly-started one via
# start_dispatcher.ps1) - matched by command line, not a hardcoded PID, so
# it works from a fresh terminal that never saw the process start.
#
# Usage: .\worker\orchestrator\stop_dispatcher.ps1

$ErrorActionPreference = "Stop"

$procs = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" |
    Where-Object { $_.CommandLine -match "dispatcher\.py" }

if (-not $procs) {
    Write-Host "No dispatcher.py process found running."
    exit 0
}

foreach ($p in $procs) {
    Write-Host "Stopping PID $($p.ProcessId): $($p.CommandLine)"
    Stop-Process -Id $p.ProcessId -Confirm:$false
}

Write-Host "Done."
