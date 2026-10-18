# agent-kb installer for Windows (PowerShell). Run from this folder:
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = $null
foreach ($c in @("py", "python", "python3")) {
    if (Get-Command $c -ErrorAction SilentlyContinue) { $py = $c; break }
}
if (-not $py) { Write-Error "Python 3.9+ not found. Install it from python.org, then re-run."; exit 1 }
Write-Host "Using $py"

& $py -m pip install --user -e . --quiet
if ($LASTEXITCODE -ne 0) { Write-Error "pip install failed"; exit 1 }

& $py -m agent_kb setup claude
& $py -m agent_kb ingest
& $py -m agent_kb doctor
& $py -m unittest discover -s tests -t . 2>&1 | Select-Object -Last 3

Write-Host ""
Write-Host "Done. Restart Claude Code: the status line and hooks take effect in new sessions."
Write-Host "Commands: $py -m agent_kb stats | tune | search ...  (or 'kb' if your Python Scripts folder is on PATH)"
