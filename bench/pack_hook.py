"""UserPromptSubmit hook for arm b: the real `kb pack --hook`, against the frozen bench knowledge base.

Usage (in .claude/settings.json): python pack_hook.py <frozen AGENT_KB_HOME> <log file>
Logs the pack size, prints the hook JSON. Never fails the hook.
"""
import io
import json
import os
import sys
from contextlib import redirect_stdout

try:
    os.environ["AGENT_KB_HOME"] = sys.argv[1]
    payload = sys.stdin.read()
    sys.stdin = io.StringIO(payload)
    from agent_kb.cli import main
    out = io.StringIO()
    with redirect_stdout(out):
        try:
            main(["pack", "--hook"])
        except SystemExit:
            pass
    text = out.getvalue().strip()
    ctx = json.loads(text)["hookSpecificOutput"]["additionalContext"] if text else ""
    with open(sys.argv[2], "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": "inject", "chars": len(ctx), "pack": ctx}, ensure_ascii=False) + "\n")
    if text:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
except Exception:
    pass
