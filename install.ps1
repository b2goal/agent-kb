# agent-kb installer for Windows (PowerShell). Run from this folder:
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
#
# Hooks run a signed python.exe directly ("<python> -m agent_kb ..."). Generated launchers such as
# uv's or pip's kb.exe are unsigned; Smart App Control can block them later and every hook then fails
# silently. The `kb` command for terminals is a .cmd / sh shim around the same python.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = $null
foreach ($c in @("python", "py", "python3")) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd) { $py = (& $c -c "import sys; print(sys.executable)").Trim(); break }
}
if (-not $py) { Write-Error "Python 3.9+ not found. Install it from python.org, then re-run."; exit 1 }
$sig = (Get-AuthenticodeSignature $py).Status
Write-Host "Using $py (signature: $sig)"
if ($sig -ne "Valid") { Write-Warning "This python.exe is not signed; Smart App Control may block it. Prefer the python.org installer." }

& $py -m pip install --user -e . --quiet
if ($LASTEXITCODE -ne 0) { Write-Error "pip install failed"; exit 1 }

# An older install via `uv tool` leaves a blocked kb.exe on PATH; remove it.
if ((Get-Command uv -ErrorAction SilentlyContinue) -and ((uv tool list 2>$null) -match "^agent-kb")) {
    uv tool uninstall agent-kb | Out-Null
}

$bin = Join-Path $env:USERPROFILE ".local\bin"
New-Item -ItemType Directory -Force $bin | Out-Null
$pyPosix = $py -replace "\\", "/"
Set-Content -Encoding ascii -Path (Join-Path $bin "kb.cmd") -Value "@`"$py`" -m agent_kb %*"
[IO.File]::WriteAllText((Join-Path $bin "kb"), "#!/bin/sh`nexec `"$pyPosix`" -m agent_kb `"`$@`"`n")
$onPath = ($env:PATH -split ";") -contains $bin
if (-not $onPath) { Write-Warning "$bin is not on PATH; add it to use 'kb' in terminals (hooks do not need it)." }

& $py -m agent_kb setup claude
& $py -m agent_kb ingest
& $py -m agent_kb doctor
# unittest reports on stderr; keep PowerShell from treating that as a failure.
$ErrorActionPreference = "Continue"
& $py -W ignore::ResourceWarning -m unittest discover -s tests -t . 2>&1 |
    ForEach-Object { if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { "$_" } } |
    Where-Object { $_.Trim() } | Select-Object -Last 2

Write-Host ""
Write-Host "Done. Restart Claude Code: the status line and hooks take effect in new sessions."
Write-Host "Commands: kb stats | tune | search ...  (or: `"$py`" -m agent_kb ...)"
