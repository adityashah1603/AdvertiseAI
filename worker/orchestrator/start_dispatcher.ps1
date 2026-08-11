# Always launches the dispatcher through THIS folder's own .venv - never
# whatever "python" happens to resolve to on PATH (on this machine that's
# the WindowsApps alias, which has a different, incompatible e2b version
# pinned - see DECISIONS.md SS6/SS2 item 8 for the real incident this caused).
# Foreground/attached on purpose, same as running it by hand: Ctrl+C stops it.
#
# Usage (from anywhere):
#   .\worker\orchestrator\start_dispatcher.ps1
# or, already inside worker\orchestrator:
#   .\start_dispatcher.ps1

$ErrorActionPreference = "Stop"

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$dispatcherScript = Join-Path $PSScriptRoot "dispatcher.py"

if (-not (Test-Path $venvPython)) {
    Write-Error "venv python not found at $venvPython - set it up first:`n  cd $PSScriptRoot`n  python -m venv .venv`n  .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}

Write-Host "Starting dispatcher via $venvPython (not the global 'python' - see requirements.txt's pin note)..."
& $venvPython $dispatcherScript --serve
