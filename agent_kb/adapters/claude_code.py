"""Claude Code adapter.

- Hooks (PostToolUse, PostToolUseFailure, PermissionRequest, PermissionDenied, SessionEnd) call
  `kb hook claude`: it only appends one line to a spool file (no output, 0 tokens). SessionEnd also
  ingests that session's transcript.
- Ingest reads transcripts in ~/.claude/projects (tokens, turns, tool calls) and merges the spool
  (permission events the transcript does not show).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .. import transcript as tr
from ..paths import ensure_home
from ..project import project_id
from ..telemetry import Telemetry

HARNESS = "claude"
TOOL_EVENTS = ["PostToolUse", "PostToolUseFailure", "PermissionRequest", "PermissionDenied"]
HOOK_MARK = "hook claude"


def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))


def spool_dir() -> Path:
    d = ensure_home() / "spool" / HARNESS
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------- hook (must stay fast)
def handle_hook(payload: Dict[str, object]) -> int:
    try:
        event = str(payload.get("hook_event_name") or "")
        sid = str(payload.get("session_id") or "unknown")
        tool_input = payload.get("tool_input") or {}
        response = payload.get("tool_response")
        line = {
            "ts": datetime.now(timezone.utc).isoformat(), "event": event, "session_id": sid,
            "tool": payload.get("tool_name"), "tool_use_id": payload.get("tool_use_id"),
            "cmd": str(tool_input.get("command", ""))[:300] if isinstance(tool_input, dict) else "",
            "bytes": len(json.dumps(response, ensure_ascii=False)) if response is not None else None,
            "cwd": payload.get("cwd"), "agent": payload.get("agent_id"),
        }
        with (spool_dir() / f"{sid}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        if event == "SessionEnd" and payload.get("transcript_path"):
            ingest_file(Path(str(payload["transcript_path"])), force=True)
    except Exception:            # a hook must never break the user's session
        return 0
    return 0


def spool_events(session_id: str) -> List[Dict[str, object]]:
    f = spool_dir() / f"{session_id}.jsonl"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------------------- ingest
def _merge_spool(events: List[Dict[str, object]], spool: List[Dict[str, object]]) -> None:
    by_id = {e["tool_use_id"]: e for e in events}
    asked = set()
    for s in spool:
        tid = s.get("tool_use_id")
        ev = by_id.get(tid)
        if s.get("event") == "PermissionDenied":
            if ev:
                ev["outcome"] = "denied"
            elif s.get("tool"):
                cmd = str(s.get("cmd") or "")
                from .. import shellparse
                events.append({"tool_use_id": tid, "ts": s.get("ts"), "tool": s.get("tool"),
                               "category": tr.category(str(s.get("tool"))), "outcome": "denied", "out_bytes": 0,
                               "agent": s.get("agent") or "main",
                               "cmd_prefix": " | ".join(shellparse.prefixes(cmd))[:200] or None,
                               "compound": int(shellparse.is_compound(cmd)), "url": None, "target": None,
                               "error_sig": None, "file": None})
        elif s.get("event") == "PermissionRequest":
            asked.add(tid)
        elif s.get("event") == "PostToolUseFailure" and ev and ev["outcome"] == "ok":
            ev["outcome"] = "error"
    for tid in asked:
        ev = by_id.get(tid)
        if ev and ev["outcome"] == "ok":
            ev["outcome"] = "approved_by_user"


def ingest_file(path: Path, tele: Optional[Telemetry] = None, force: bool = False) -> Optional[Dict[str, object]]:
    tele = tele or Telemetry()
    try:
        st = path.stat()
    except OSError:
        return None
    cur = tele.cursor(str(path))
    if not force and cur and cur["size"] == st.st_size and abs(cur["mtime"] - st.st_mtime) < 1e-6:
        return None
    p = tr.parse(path)
    if not p.session_id:
        return None
    summ = tr.summarize(p)
    if not summ["api_calls"]:
        tele.set_cursor(str(path), st.st_size, st.st_mtime, p.session_id)
        return None
    events = tr.tool_events(p)
    _merge_spool(events, spool_events(p.session_id))
    outcomes = [e["outcome"] for e in events]
    summ.update(denied=outcomes.count("denied"), approved=outcomes.count("approved_by_user"),
                errors=outcomes.count("error"))
    session = dict(summ, session_id=p.session_id, harness=HARNESS, project=project_id(p.cwd or str(path.parent)),
                   cwd=p.cwd, version=p.version, test_commands=json.dumps(tr.test_commands(p), ensure_ascii=False),
                   source_file=str(path), ingested_at=datetime.now(timezone.utc).isoformat())
    tele.replace_session(session, events)
    tele.set_cursor(str(path), st.st_size, st.st_mtime, p.session_id)
    return session


def discover(recent: Optional[int] = None, project_dir: Optional[str] = None) -> List[Path]:
    root = claude_dir() / "projects"
    files = [f for f in root.glob("*/*.jsonl")] if root.is_dir() else []
    if project_dir:
        want = project_id(project_dir)
        files = [f for f in files if _transcript_project(f) == want]
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return files[:recent] if recent else files


def _transcript_project(f: Path) -> Optional[str]:
    for i, row in enumerate(tr.iter_json(f)):
        if row.get("cwd"):
            return project_id(row["cwd"])
        if i > 40:
            break
    return None


def ingest_all(recent: Optional[int] = None, force: bool = False, project_dir: Optional[str] = None) -> Dict[str, int]:
    tele = Telemetry()
    from ..paths import load_config
    tele.prune(int(load_config()["telemetry"]["raw_retention_days"]))
    done = skipped = 0
    for f in discover(recent, project_dir):
        res = ingest_file(f, tele, force)
        done += res is not None
        skipped += res is None
    return {"ingested": done, "unchanged_or_empty": skipped}


# ---------------------------------------------------------------------------- setup
def kb_command() -> str:
    # Windows: never point hooks at a generated kb.exe launcher. It is unsigned, and Smart App Control
    # can start blocking it at any time, which makes every hook fail silently. A signed python.exe is stable.
    if os.name != "nt" and shutil.which("kb"):
        return "kb"
    exe = Path(sys.executable).as_posix()          # forward slashes: safe in Git Bash, cmd and PowerShell
    return f'"{exe}" -m agent_kb'


def _is_mine_statusline(cmd: str) -> bool:
    return cmd.rstrip().endswith(" statusline") and ("agent_kb" in cmd or cmd.split()[0].strip('"') == "kb")


def settings_file(scope: str, project_dir: Optional[str] = None) -> Path:
    if scope == "user":
        return claude_dir() / "settings.json"
    base = Path(project_dir or ".").resolve() / ".claude"
    return base / ("settings.local.json" if scope == "local" else "settings.json")


def setup(scope: str = "user", project_dir: Optional[str] = None, statusline: bool = True,
          force_statusline: bool = False, dry_run: bool = False) -> Dict[str, object]:
    path = settings_file(scope, project_dir)
    data: Dict[str, object] = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    cmd = f"{kb_command()} {HOOK_MARK}"
    hooks = data.setdefault("hooks", {})
    added = []
    for event in TOOL_EVENTS + ["SessionEnd"]:
        groups = hooks.setdefault(event, [])
        mine = [h for g in groups for h in g.get("hooks", []) if HOOK_MARK in str(h.get("command", ""))]
        if mine:
            for h in mine:                         # re-point an older launcher (e.g. a blocked kb.exe)
                if h.get("command") != cmd:
                    h["command"] = cmd
                    added.append(event + " (updated)")
            continue
        group: Dict[str, object] = {"hooks": [{"type": "command", "command": cmd, "timeout": 30}]}
        if event in TOOL_EVENTS:
            group["matcher"] = "*"
        groups.append(group)
        added.append(event)
    status_note = "kept existing"
    current = str((data.get("statusLine") or {}).get("command", ""))
    if statusline and (force_statusline or "statusLine" not in data
                       or (_is_mine_statusline(current) and current != f"{kb_command()} statusline")):
        data["statusLine"] = {"type": "command", "command": f"{kb_command()} statusline"}
        status_note = "set"
    if not dry_run and (added or status_note == "set"):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.copy(path, path.with_name(path.name + f".bak-agentkb-{int(time.time())}"))
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"settings": str(path), "hooks_added": added, "statusline": status_note, "dry_run": dry_run,
            "command": cmd}
