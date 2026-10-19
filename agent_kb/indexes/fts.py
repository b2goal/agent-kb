"""Full-text index on SQLite FTS5 (standard library). Follows the store's change log."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from .. import schema
from ..paths import ensure_home
from . import Hit, Query


STEPS = [
    "CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5("
    " item_id UNINDEXED, project UNINDEXED, kind UNINDEXED, status UNINDEXED,"
    " title, subject_key, body, tokenize='unicode61 remove_diacritics 2');"
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)",
]


class FTSIndex:
    name = "fts"
    version = "1"

    def __init__(self, path: Path = None) -> None:
        self.path = path or (ensure_home() / "index" / f"fts-v{self.version}.db")
        self.db = schema.connect(self.path, check_same_thread=False)
        schema.migrate(self.db, "fts", STEPS)

    def _seq(self) -> int:
        row = self.db.execute("SELECT value FROM meta WHERE key='last_seq'").fetchone()
        return int(row[0]) if row else 0

    def _set_seq(self, seq: int) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES ('last_seq', ?)", (str(seq),))

    def _put(self, item) -> None:
        self.db.execute("DELETE FROM docs WHERE item_id=?", (item.id,))
        self.db.execute("INSERT INTO docs VALUES (?,?,?,?,?,?,?)",
                        (item.id, item.project, item.kind, item.status, item.title,
                         item.subject_key.replace("/", " ").replace(":", " "), item.body))

    def build(self, store) -> int:
        n = 0
        with schema.immediate(self.db):
            self.db.execute("DELETE FROM docs")
            for item in store.all_items():
                self._put(item)
                n += 1
            self._set_seq(store.last_seq())
        return n

    def update(self, store) -> int:
        changes = store.changes_since(self._seq())
        if not changes:
            return 0
        with schema.immediate(self.db):
            for item_id in dict.fromkeys(c["item_id"] for c in changes):
                item = store.get(item_id)
                if item is None:
                    self.db.execute("DELETE FROM docs WHERE item_id=?", (item_id,))
                else:
                    self._put(item)
            self._set_seq(changes[-1]["seq"])
        return len(changes)

    def query(self, q: Query) -> List[Hit]:
        words = [w for w in re.findall(r"\w+", q.text or "", flags=re.UNICODE) if len(w) > 1]
        if not words:
            return []
        match = " OR ".join(f'"{w}"' for w in words)
        sql = "SELECT item_id, bm25(docs) AS s FROM docs WHERE docs MATCH ?"
        args: list = [match]
        if q.project:
            sql += " AND project IN (?, 'global')"
            args.append(q.project)
        if q.kinds:
            sql += f" AND kind IN ({','.join('?' * len(q.kinds))})"
            args += list(q.kinds)
        if q.statuses:
            sql += f" AND status IN ({','.join('?' * len(q.statuses))})"
            args += list(q.statuses)
        sql += " ORDER BY s LIMIT ?"
        args.append(q.limit * 3)
        return [(r[0], -float(r[1])) for r in self.db.execute(sql, args)]

    def health(self) -> Dict[str, object]:
        n = self.db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        return {"ok": True, "docs": n, "last_seq": self._seq(), "path": str(self.path)}
