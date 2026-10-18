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

# Prefer uv: it puts kb.exe in ~/.local/bin (on PATH), so hooks can call plain "kb".
if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv tool install --force -e .
    if ($LASTEXITCODE -ne 0) { Write-Error "uv tool install failed"; exit 1 }
    $kb = @("kb")
} else {
    & $py -m pip install --user -e . --quiet
    if ($LASTEXITCODE -ne 0) { Write-Error "pip install failed"; exit 1 }
    $kb = @($py, "-m", "agent_kb")
}
$kbExe = $kb[0]; $kbArgs = @($kb | Select-Object -Skip 1)

& $kbExe @kbArgs setup claude
& $kbExe @kbArgs ingest
& $kbExe @kbArgs doctor
# unittest reports on stderr; keep PowerShell from treating that as a failure.
$ErrorActionPreference = "Continue"
& $py -W ignore::ResourceWarning -m unittest discover -s tests -t . 2>&1 |
    ForEach-Object { if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { "$_" } } |
    Where-Object { $_.Trim() } | Select-Object -Last 2

Write-Host ""
Write-Host "Done. Restart Claude Code: the status line and hooks take effect in new sessions."
Write-Host "Commands: $($kb -join ' ') stats | tune | search ..."
