"""Storage behind one interface + the single write path.

Source of truth: one Markdown file per knowledge item under knowledge/<project>/<kind>/.
kb.db holds a rebuildable metadata table, the change log (what indexes follow) and conflicts.
Swap LocalStore for a cloud store later without touching callers.

Every write runs inside one immediate SQLite transaction, so two processes writing about the same
subject are serialized and see each other's result. Files edited by hand are picked up by reconcile().
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Protocol

from . import kinds, schema
from .model import Item, now_iso
from .paths import ensure_home, load_config
from .project import slug

WriteFilter = Callable[[Item], Optional[Item]]   # return None to drop the write


class Store(Protocol):
    def put(self, item: Item, actor: str = "manual") -> Dict[str, object]: ...
    def get(self, item_id: str) -> Optional[Item]: ...
    def find(self, **filters: object) -> List[Item]: ...
    def changes_since(self, seq: int) -> List[sqlite3.Row]: ...


_SCHEMA_V1 = """
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


def _v2_file_stamp(conn: sqlite3.Connection) -> None:
    """Remember each file's mtime and size, so reconcile() only re-reads files that changed."""
    if not schema.has_column(conn, "items", "mtime"):
        conn.execute("ALTER TABLE items ADD COLUMN mtime REAL")
    if not schema.has_column(conn, "items", "size"):
        conn.execute("ALTER TABLE items ADD COLUMN size INTEGER")


STEPS = [_SCHEMA_V1, _v2_file_stamp]      # append migration steps; never edit a released one
_ITEM_COLS = "id, kind, project, subject_key, title, status, rank, hash, path, valid_from, valid_to, updated, mtime, size"


class LocalStore:
    """Files as source of truth; SQLite for metadata, change log and conflicts."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = root or ensure_home()
        self.kdir = self.root / "knowledge"
        self.kdir.mkdir(parents=True, exist_ok=True)
        self.db = schema.connect(self.root / "kb.db")
        schema.migrate(self.db, "kb", STEPS)
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

    def unknown_kinds(self) -> Dict[str, int]:
        """Kinds present in the store that this version has not registered (written by a newer agent-kb or by hand)."""
        rows = self.db.execute("SELECT kind, COUNT(*) FROM items GROUP BY kind").fetchall()
        return {r[0]: r[1] for r in rows if not kinds.is_known(r[0])}

    # ------------------------------------------------------------------ write path (call inside a transaction)
    def _meta(self, item: Item, path: Path, content_hash: str) -> None:
        st = path.stat()
        self.db.execute(f"INSERT OR REPLACE INTO items ({_ITEM_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (item.id, item.kind, item.project, item.subject_key, item.title, item.status, item.rank,
                         content_hash, str(path), item.valid_from, item.valid_to, now_iso(), st.st_mtime, st.st_size))

    def _log(self, item_id: str, op: str, content_hash: Optional[str], actor: str) -> None:
        self.db.execute("INSERT INTO change_log(item_id, op, hash, ts, actor) VALUES (?,?,?,?,?)",
                        (item_id, op, content_hash, now_iso(), actor))

    def _write(self, item: Item, op: str, actor: str) -> None:
        path = self.path_for(item)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = item.to_text()                       # also refreshes item.hash
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)                           # atomic on the same filesystem
        self._meta(item, path, item.hash)
        self._log(item.id, op, item.hash, actor)

    def _supersede(self, old: Item, new: Item, actor: str) -> None:
        old.status = "superseded"
        old.superseded_by = new.id
        old.valid_to = now_iso()
        self._write(old, "supersede", actor)

    def _open_conflict(self, item_id: str, other_id: Optional[str], subject_key: str, project: str) -> None:
        """One open conflict per pair; a repeated disagreement does not pile up rows."""
        if self.db.execute("SELECT 1 FROM conflicts WHERE resolved IS NULL AND item_id=? AND other_id IS ?",
                           (item_id, other_id)).fetchone():
            return
        self.db.execute("INSERT INTO conflicts(item_id, other_id, subject_key, project, created) VALUES (?,?,?,?,?)",
                        (item_id, other_id, subject_key, project, now_iso()))

    def put(self, item: Item, actor: str = "manual") -> Dict[str, object]:
        """The single write path. Applies filters, dedupe, precedence and supersede rules.

        Returns {"result": created|updated|unchanged|superseded_others|conflict|dropped, ...}.
        """
        kinds.require(item.kind)                    # reading tolerates unknown kinds, writing does not
        for f in self.write_filters:
            filtered = f(item)
            if filtered is None:
                return {"result": "dropped", "id": item.id}
            item = filtered
        item.hash = item.content_hash()
        with schema.immediate(self.db):
            return self._put_locked(item, actor)

    def _put_locked(self, item: Item, actor: str) -> Dict[str, object]:
        existing = self.get(item.id)
        if existing is not None:
            if existing.hash == item.hash and existing.status == item.status and existing.rank == item.rank:
                return {"result": "unchanged", "id": item.id}
            if item.rank > existing.rank:           # less trusted source rewriting a more trusted item
                self._open_conflict(item.id, None, existing.subject_key, existing.project)
                return {"result": "conflict", "id": item.id, "kept_rank": existing.rank, "conflicts": [item.id]}
            self._write(item, "update", actor)
            return {"result": "updated", "id": item.id}

        if item.supersedes:                         # explicit supersede
            old = self.get(item.supersedes)
            self._write(item, "create", actor)
            if old is not None and old.status == "active":
                self._supersede(old, item, actor)
            return {"result": "created", "id": item.id, "superseded": [item.supersedes]}

        peers = self.find(project=item.project, kind=item.kind, subject_key=item.subject_key, status="active")
        same = [p for p in peers if p.hash == item.hash]
        if same:                                    # identical content already active
            keep = same[0]
            if item.rank < keep.rank:               # more trusted source confirms it
                keep.rank = item.rank
                keep.source = item.source
                keep.evidence = list(dict.fromkeys((keep.evidence or []) + (item.evidence or [])))
                self._write(keep, "update", actor)
                return {"result": "updated", "id": keep.id}
            return {"result": "unchanged", "id": keep.id}

        beaten = [p for p in peers if item.rank <= p.rank]      # same or more trusted: newer wins
        conflicting = [p for p in peers if item.rank > p.rank]  # less trusted and different: needs review
        if conflicting and item.status == "active":
            item.status = "proposed"
        self._write(item, "create", actor)
        if item.status == "active":
            for p in beaten:
                self._supersede(p, item, actor)
        for p in conflicting:
            self._open_conflict(item.id, p.id, item.subject_key, item.project)
        return {"id": item.id,
                "result": "conflict" if conflicting else ("created" if not beaten else "superseded_others"),
                "superseded": [p.id for p in beaten] if item.status == "active" else [],
                "conflicts": [p.id for p in conflicting]}

    def set_status(self, item_id: str, status: str, actor: str = "manual") -> Item:
        with schema.immediate(self.db):
            item = self.get(item_id)
            if item is None:
                raise KeyError(item_id)
            item.status = status
            if status in ("retired", "superseded"):
                item.valid_to = now_iso()
            self._write(item, status if status in ("retired", "stale") else "update", actor)
        return item

    def confirm(self, item_id: str, actor: str = "manual") -> Dict[str, object]:
        """A person confirms an item: it becomes rank 1 and active; other active peers are superseded."""
        with schema.immediate(self.db):
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
        return {"id": item.id, "superseded": superseded}

    # ------------------------------------------------------------------ files changed outside kb
    def reconcile(self) -> Dict[str, object]:
        """Bring metadata and the change log in line with the files (hand edits, deletions, files added by hand).

        Cheap when nothing changed: only files whose mtime or size moved are read again.
        """
        known = {r["path"]: r for r in self.db.execute("SELECT id, path, hash, mtime, size FROM items")}
        seen, changed, errors = set(), [], []
        for f in self.kdir.rglob("*.md"):
            key = str(f)
            seen.add(key)
            st = f.stat()
            row = known.get(key)
            if row is not None and row["mtime"] == st.st_mtime and row["size"] == st.st_size:
                continue
            try:
                changed.append((f, row, Item.from_text(f.read_text(encoding="utf-8"))))
            except (ValueError, TypeError) as exc:
                errors.append(f"{f.name}: {exc}")
        gone = [row for path, row in known.items() if path not in seen]
        edited, added, removed = [], [], []
        if changed or gone:                         # take the write lock only when there is something to apply
            with schema.immediate(self.db):
                for f, row, item in changed:
                    h = item.content_hash()
                    self._meta(item, f, h)
                    if row is None:
                        self._log(item.id, "external_add", h, "file")
                        added.append(item.id)
                    elif row["hash"] != h:
                        self._log(item.id, "external_edit", h, "file")
                        edited.append(item.id)
                for row in gone:
                    self.db.execute("DELETE FROM items WHERE id=?", (row["id"],))
                    self._log(row["id"], "external_delete", None, "file")
                    removed.append(row["id"])
        return {"edited": edited, "added": added, "removed": removed, "errors": errors}

    # ------------------------------------------------------------------ maintenance
    def rebuild_meta(self) -> int:
        """Recreate the metadata table from the files (files are the source of truth)."""
        n = 0
        with schema.immediate(self.db):
            self.db.execute("DELETE FROM items")
            for f in self.kdir.rglob("*.md"):
                try:
                    it = Item.from_text(f.read_text(encoding="utf-8"))
                except (ValueError, TypeError):
                    continue
                self._meta(it, f, it.content_hash())
                n += 1
        return n

    def all_items(self) -> Iterable[Item]:
        for r in self.db.execute("SELECT path FROM items").fetchall():
            p = Path(r["path"])
            if p.exists():
                yield Item.from_text(p.read_text(encoding="utf-8"))

    def close(self) -> None:
        self.db.close()
