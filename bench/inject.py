"""UserPromptSubmit hook for the bench: adds a context pack to the session (arms b and c).

Usage (in .claude/settings.json): python inject.py <pack file> <log file>
Prints the hook JSON that Claude Code turns into additional context. Never fails the hook.
"""
import json
import sys

try:
    pack = open(sys.argv[1], encoding="utf-8").read().strip()
    sys.stdin.read()
    with open(sys.argv[2], "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": "inject", "chars": len(pack)}) + "\n")
    out = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": pack}}
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
except Exception:
    pass
