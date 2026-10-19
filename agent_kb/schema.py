"""SQLite connections and versioned schema migrations for every agent-kb database.

Each database declares an ordered list of steps; step N brings it from user_version N-1 to N.
A database written by a newer agent-kb (user_version above what this code knows) is refused,
never silently "fixed", so an old install cannot damage new data.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, List, Sequence, Union

Step = Union[str, Callable[[sqlite3.Connection], None]]
BUSY_TIMEOUT_MS = 10000


class SchemaTooNew(RuntimeError):
    pass


def connect(path: Union[str, Path], *, check_same_thread: bool = True) -> sqlite3.Connection:
    """Autocommit connection (callers open their own transactions), WAL, and a busy timeout so
    concurrent hook / CLI / server processes wait for each other instead of failing."""
    conn = sqlite3.connect(str(path), timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None,
                           check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:     # e.g. a read-only or network location: keep the default journal
        pass
    return conn


@contextmanager
def immediate(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """One write transaction that takes the database write lock up front (serializes writers across processes)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection, name: str, steps: Sequence[Step]) -> int:
    """Apply the missing steps in one immediate transaction each. Returns the resulting version."""
    current = version(conn)
    if current > len(steps):
        raise SchemaTooNew(f"{name} schema is v{current}, this agent-kb knows up to v{len(steps)}; upgrade agent-kb")
    for n in range(current + 1, len(steps) + 1):
        step = steps[n - 1]
        conn.execute("BEGIN IMMEDIATE")
        try:
            if version(conn) >= n:                   # another process migrated while we waited for the lock
                conn.execute("COMMIT")
                continue
            if callable(step):
                step(conn)
            else:
                for stmt in _statements(step):
                    conn.execute(stmt)
            conn.execute(f"PRAGMA user_version={n}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return version(conn)


def _statements(script: str) -> List[str]:
    """Split a schema script on ';' (our scripts hold no ';' inside strings)."""
    return [s.strip() for s in script.split(";") if s.strip()]


def has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))
