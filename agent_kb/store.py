"""Storage behind one interface + the single write path.

Source of truth: one Markdown file per knowledge item under knowledge/<project>/<kind>/.
kb.db holds a rebuildable metadata table, the change log (what indexes follow) and conflicts.
Swap LocalStore for a cloud store later without touching callers.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Protocol

from .model import Item, now_iso
from .paths import ensure_home, load_config
from .project import slug

WriteFilter = Callable[[Item], Optional[Item]]   # return None to drop the write


class Store(Protocol):
    def put(self, item: Item, actor: str = "manual") -> Dict[str, object]: ...
    def get(self, item_id: str) -> Optional[Item]: ...
    def find(self, **filters: object) -> List[Item]: ...
    def changes_since(self, seq: int) -> List[sqlite3.Row]: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY, kind TEXT, project TEXT, subject_key TEXT, title TEXT, status TEXT,
  rank INTEGER, hash TEXT, path TEXT, valid_from TEXT, valid_to TEXT, updated TEXT);
CREATE INDEX IF NOT EXISTS items_subject ON items(project, kind, subject_key, status);
CREATE TABLE IF NOT EXISTS change_log (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT, op TEXT, hash TEXT, ts TEXT, actor TEXT);
CREATE TABLE IF NOT EXISTS conflicts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT, other_id TEXT, subject_key TEXT, project TEXT,
  created TEXT, resolved TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class LocalStore:
    """Files as source of truth; SQLite for metadata, change log and conflicts."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = root or ensure_home()
        self.kdir = self.root / "knowledge"
        self.kdir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.root / "kb.db"))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        self.write_filters: List[WriteFilter] = []      # filter_on_write: empty in v1
        self.rank = load_config()["rank"]

    # ------------------------------------------------------------------ paths
    def path_for(self, item: Item) -> Path:
        return self.kdir / slug(item.project) / item.kind / f"{item.id}.md"

    # ------------------------------------------------------------------ read
    def get(self, item_id: str) -> Optional[Item]:
        row = self.db.execute("SELECT path FROM items WHERE id=?", (item_id,)).fetchone()
        if not row or not Path(row["path"]).exists():
            return None
        return Item.from_text(Path(row["path"]).read_text(encoding="utf-8"))

    def find(self, **filters: object) -> List[Item]:
        rows = self.find_meta(**filters)
        out = []
        for r in rows:
            p = Path(r["path"])
            if p.exists():
                out.append(Item.from_text(p.read_text(encoding="utf-8")))
        return out

    def find_meta(self, **filters: object) -> List[sqlite3.Row]:
        allowed = {"project", "kind", "subject_key", "status", "id"}
        where, args = [], []
        for k, v in filters.items():
            if v is None or k not in allowed:
                continue
            if isinstance(v, (list, tuple, set)):
                where.append(f"{k} IN ({','.join('?' * len(v))})")
                args.extend(v)
            else:
                where.append(f"{k}=?")
                args.append(v)
        sql = "SELECT * FROM items" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY updated DESC"
        return self.db.execute(sql, args).fetchall()

    def changes_since(self, seq: int) -> List[sqlite3.Row]:
        return self.db.execute("SELECT * FROM change_log WHERE seq>? ORDER BY seq", (seq,)).fetchall()

    def last_seq(self) -> int:
        row = self.db.execute("SELECT MAX(seq) FROM change_log").fetchone()
        return int(row[0] or 0)

    def conflicts(self, open_only: bool = True) -> List[sqlite3.Row]:
        sql = "SELECT * FROM conflicts" + (" WHERE resolved IS NULL" if open_only else "") + " ORDER BY id"
        return self.db.execute(sql).fetchall()

    # ------------------------------------------------------------------ write path
    def _write(self, item: Item, op: str, actor: str) -> None:
        path = self.path_for(item)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = item.to_text()                       # also refreshes item.hash
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)                           # atomic on the same filesystem
        self.db.execute(
            "INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (item.id, item.kind, item.project, item.subject_key, item.title, item.status, item.rank,
             item.hash, str(path), item.valid_from, item.valid_to, now_iso()))
        self.db.execute("INSERT INTO change_log(item_id, op, hash, ts, actor) VALUES (?,?,?,?,?)",
                        (item.id, op, item.hash, now_iso(), actor))

    def _supersede(self, old: Item, new: Item, actor: str) -> None:
        old.status = "superseded"
        old.superseded_by = new.id
        old.valid_to = now_iso()
        self._write(old, "supersede", actor)

    def put(self, item: Item, actor: str = "manual") -> Dict[str, object]:
        """The single write path. Applies filters, dedupe, precedence and supersede rules.

        Returns {"result": created|updated|unchanged|superseded_others|conflict|dropped, ...}.
        """
        for f in self.write_filters:
            filtered = f(item)
            if filtered is None:
                return {"result": "dropped", "id": item.id}
            item = filtered
        item.hash = item.content_hash()
        result: Dict[str, object] = {"id": item.id}
        try:
            existing = self.get(item.id)
            if existing is not None:
                if existing.hash == item.hash and existing.status == item.status and existing.rank == item.rank:
                    return {"result": "unchanged", "id": item.id}
                self._write(item, "update", actor)
                self.db.commit()
                return {"result": "updated", "id": item.id}

            # explicit supersede
            if item.supersedes:
                old = self.get(item.supersedes)
                self._write(item, "create", actor)
                if old is not None and old.status == "active":
                    self._supersede(old, item, actor)
                self.db.commit()
                return {"result": "created", "id": item.id, "superseded": [item.supersedes]}

            peers = [p for p in self.find(project=item.project, kind=item.kind,
                                          subject_key=item.subject_key, status="active")]
            same = [p for p in peers if p.hash == item.hash]
            if same:                                   # identical content already active
                keep = same[0]
                if item.rank < keep.rank:              # more trusted source confirms it
                    keep.rank = item.rank
                    keep.source = item.source
                    keep.evidence = list(dict.fromkeys((keep.evidence or []) + (item.evidence or [])))
                    self._write(keep, "update", actor)
                    self.db.commit()
                    return {"result": "updated", "id": keep.id}
                return {"result": "unchanged", "id": keep.id}

            beaten, conflicting = [], []
            for p in peers:
                if item.rank <= p.rank:                # same or more trusted: newer wins
                    beaten.append(p)
                else:                                  # less trusted and different: needs review
                    conflicting.append(p)
            if conflicting and item.status == "active":
                item.status = "proposed"
            self._write(item, "create", actor)
            for p in beaten:
                if item.status == "active":
                    self._supersede(p, item, actor)
            for p in conflicting:
                self.db.execute(
                    "INSERT INTO conflicts(item_id, other_id, subject_key, project, created) VALUES (?,?,?,?,?)",
                    (item.id, p.id, item.subject_key, item.project, now_iso()))
            self.db.commit()
            result.update(result="conflict" if conflicting else ("created" if not beaten else "superseded_others"),
                          superseded=[p.id for p in beaten] if item.status == "active" else [],
                          conflicts=[p.id for p in conflicting])
            return result
        except Exception:
            self.db.rollback()
            raise

    def set_status(self, item_id: str, status: str, actor: str = "manual") -> Item:
        item = self.get(item_id)
        if item is None:
            raise KeyError(item_id)
        item.status = status
        if status in ("retired", "superseded"):
            item.valid_to = now_iso()
        self._write(item, status if status in ("retired", "stale") else "update", actor)
        self.db.commit()
        return item

    def confirm(self, item_id: str, actor: str = "manual") -> Dict[str, object]:
        """A person confirms an item: it becomes rank 1 and active; other active peers are superseded."""
        item = self.get(item_id)
        if item is None:
            raise KeyError(item_id)
        item.rank = int(self.rank.get("manual", 1))
        item.status = "active"
        item.source = dict(item.source or {}, confirmed=True)
        self._write(item, "confirm", actor)
        superseded = []
        for p in self.find(project=item.project, kind=item.kind, subject_key=item.subject_key, status="active"):
            if p.id != item.id:
                self._supersede(p, item, actor)
                superseded.append(p.id)
        self.db.execute("UPDATE conflicts SET resolved=? WHERE resolved IS NULL AND (item_id=? OR other_id=?)",
                        (now_iso(), item.id, item.id))
        self.db.commit()
        return {"id": item.id, "superseded": superseded}

    # ------------------------------------------------------------------ maintenance
    def rebuild_meta(self) -> int:
        """Recreate the metadata table from the files (files are the source of truth)."""
        self.db.execute("DELETE FROM items")
        n = 0
        for f in self.kdir.rglob("*.md"):
            try:
                it = Item.from_text(f.read_text(encoding="utf-8"))
            except ValueError:
                continue
            self.db.execute("INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (it.id, it.kind, it.project, it.subject_key, it.title, it.status, it.rank,
                             it.content_hash(), str(f), it.valid_from, it.valid_to, now_iso()))
            n += 1
        self.db.commit()
        return n

    def all_items(self) -> Iterable[Item]:
        for r in self.db.execute("SELECT path FROM items"):
            p = Path(r["path"])
            if p.exists():
                yield Item.from_text(p.read_text(encoding="utf-8"))

    def close(self) -> None:
        self.db.close()
