"""Telemetry store (SQLite): sessions and tool events, harness-independent."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from . import schema
from .paths import ensure_home

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY, harness TEXT, project TEXT, cwd TEXT, started TEXT, ended TEXT,
  model TEXT, version TEXT, api_calls INTEGER, api_calls_sub INTEGER, tool_calls INTEGER,
  tool_turns INTEGER, parallel_turns INTEGER, read_only_turns INTEGER, single_read_turns INTEGER,
  ctx_tokens INTEGER, out_tokens INTEGER, cache_read INTEGER, cache_write INTEGER, first_ctx INTEGER,
  cache_breaks INTEGER, compactions INTEGER, denied INTEGER, approved INTEGER, errors INTEGER,
  test_commands TEXT, source_file TEXT, ingested_at TEXT);
CREATE INDEX IF NOT EXISTS sessions_project ON sessions(project, started);
CREATE TABLE IF NOT EXISTS tool_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, harness TEXT, project TEXT, ts TEXT,
  tool_use_id TEXT, tool TEXT, category TEXT, outcome TEXT, out_bytes INTEGER, agent TEXT,
  cmd_prefix TEXT, compound INTEGER, url TEXT, target TEXT, error_sig TEXT, file TEXT);
CREATE INDEX IF NOT EXISTS tool_events_project ON tool_events(project, ts);
CREATE INDEX IF NOT EXISTS tool_events_session ON tool_events(session_id);
CREATE TABLE IF NOT EXISTS ingest_cursor (path TEXT PRIMARY KEY, size INTEGER, mtime REAL, session_id TEXT);
CREATE TABLE IF NOT EXISTS trigger_state (project TEXT PRIMARY KEY, last_fired TEXT, last_applied TEXT,
  sessions_at_apply INTEGER);
"""

def _v2_prompt(conn) -> None:
    """The session's first request, used to relate a new task to past sessions (kb pack)."""
    if not schema.has_column(conn, "sessions", "prompt"):
        conn.execute("ALTER TABLE sessions ADD COLUMN prompt TEXT")


def _v3_notes(conn) -> None:
    """Derived per-session facts as JSON (e.g. which account reached which page). Never secrets."""
    if not schema.has_column(conn, "sessions", "notes"):
        conn.execute("ALTER TABLE sessions ADD COLUMN notes TEXT")


STEPS = [_SCHEMA, _v2_prompt, _v3_notes]   # append migration steps; never edit a released one

SESSION_COLS = ["session_id", "harness", "project", "cwd", "started", "ended", "model", "version", "api_calls",
                "api_calls_sub", "tool_calls", "tool_turns", "parallel_turns", "read_only_turns",
                "single_read_turns", "ctx_tokens", "out_tokens", "cache_read", "cache_write", "first_ctx",
                "cache_breaks", "compactions", "denied", "approved", "errors", "test_commands", "source_file",
                "ingested_at", "prompt", "notes"]
EVENT_COLS = ["session_id", "harness", "project", "ts", "tool_use_id", "tool", "category", "outcome",
              "out_bytes", "agent", "cmd_prefix", "compound", "url", "target", "error_sig", "file"]


def since_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class Telemetry:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or (ensure_home() / "telemetry.db")
        self.db = schema.connect(self.path)
        schema.migrate(self.db, "telemetry", STEPS)

    # ------------------------------------------------------------------ writes
    def replace_session(self, session: Dict[str, object], events: Iterable[Dict[str, object]]) -> None:
        sid = session["session_id"]
        with schema.immediate(self.db):
            self._replace(sid, session, events)

    def _replace(self, sid: str, session: Dict[str, object], events: Iterable[Dict[str, object]]) -> None:
        self.db.execute("DELETE FROM tool_events WHERE session_id=?", (sid,))
        self.db.execute(f"INSERT OR REPLACE INTO sessions ({','.join(SESSION_COLS)}) "
                        f"VALUES ({','.join('?' * len(SESSION_COLS))})",
                        [session.get(c) for c in SESSION_COLS])
        rows = [[dict(ev, session_id=sid, harness=session.get("harness"), project=session.get("project")).get(c)
                 for c in EVENT_COLS] for ev in events]
        self.db.executemany(f"INSERT INTO tool_events ({','.join(EVENT_COLS)}) "
                            f"VALUES ({','.join('?' * len(EVENT_COLS))})", rows)

    def cursor(self, path: str) -> Optional[sqlite3.Row]:
        return self.db.execute("SELECT * FROM ingest_cursor WHERE path=?", (path,)).fetchone()

    def set_cursor(self, path: str, size: int, mtime: float, session_id: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO ingest_cursor VALUES (?,?,?,?)", (path, size, mtime, session_id))
        self.db.commit()

    def prune(self, days: int) -> int:
        cur = self.db.execute("DELETE FROM tool_events WHERE ts < ?", (since_iso(days),))
        self.db.commit()
        return cur.rowcount

    # ------------------------------------------------------------------ reads
    def sessions(self, project: Optional[str] = None, days: Optional[int] = None,
                 since: Optional[str] = None) -> List[sqlite3.Row]:
        sql, args = "SELECT * FROM sessions WHERE 1=1", []
        if project:
            sql += " AND project=?"
            args.append(project)
        if days:
            sql += " AND started >= ?"
            args.append(since_iso(days))
        if since:
            sql += " AND started > ?"
            args.append(since)
        return self.db.execute(sql + " ORDER BY started DESC", args).fetchall()

    def events(self, project: Optional[str] = None, days: Optional[int] = None,
               session_id: Optional[str] = None) -> List[sqlite3.Row]:
        sql, args = "SELECT * FROM tool_events WHERE 1=1", []
        if project:
            sql += " AND project=?"
            args.append(project)
        if days:
            sql += " AND ts >= ?"
            args.append(since_iso(days))
        if session_id:
            sql += " AND session_id=?"
            args.append(session_id)
        return self.db.execute(sql, args).fetchall()

    def projects(self) -> List[str]:
        return [r[0] for r in self.db.execute("SELECT DISTINCT project FROM sessions ORDER BY project")]

    def trigger_state(self, project: str) -> Optional[sqlite3.Row]:
        return self.db.execute("SELECT * FROM trigger_state WHERE project=?", (project,)).fetchone()

    def set_trigger_state(self, project: str, **fields: object) -> None:
        cur = dict(self.trigger_state(project) or {"project": project, "last_fired": None,
                                                    "last_applied": None, "sessions_at_apply": None})
        cur.update(fields)
        self.db.execute("INSERT OR REPLACE INTO trigger_state VALUES (?,?,?,?)",
                        (project, cur["last_fired"], cur["last_applied"], cur["sessions_at_apply"]))
        self.db.commit()
