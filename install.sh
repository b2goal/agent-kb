#!/bin/sh
# agent-kb installer for macOS/Linux/Git Bash. Run from this folder: sh install.sh
set -e
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python || command -v py)
"$PY" -m pip install --user -e . --quiet || "$PY" -m pip install --user --break-system-packages -e . --quiet
"$PY" -m agent_kb setup claude
"$PY" -m agent_kb ingest
"$PY" -m agent_kb doctor
echo "Done. Restart Claude Code to load the hooks and status line."
