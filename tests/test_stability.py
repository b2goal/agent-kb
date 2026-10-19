"""Stage 1 (stability) tests: each reproduces a finding of the 2026-10-19 review.

P1-0 same-id precedence · P1-1 concurrent writers · P1-2 hand edits · P1-4 unknown kinds · P1-8 schema versions.
"""
import multiprocessing as mp
import os
import sqlite3
import time

from tests.test_core import Env, item


def _writer(n, start_at):
    from agent_kb.store import LocalStore
    from agent_kb.model import Item
    store = LocalStore()
    slow_write = store._write

    def _write(*args, **kw):                              # a slow disk widens the read-check-write window
        time.sleep(0.2)
        return slow_write(*args, **kw)
    store._write = _write
    time.sleep(max(0.0, start_at - time.time()))         # all processes write at the same moment
    store.put(Item(kind="convention", project="p", subject_key="tests", title="t", body=f"v{n}"))


class SameIdPrecedenceTest(Env):          # P1-0
    def test_lower_rank_cannot_rewrite_a_confirmed_item(self):
        from agent_kb.store import LocalStore
        s = LocalStore()
        it = item(rank=2, source={"name": "observed"})
        s.put(it, actor="browser")
        s.confirm(it.id)
        again = s.get(it.id)
        again.body = "observed again, different counters"
        again.rank = 2
        res = s.put(again, actor="browser")
        self.assertEqual(res["result"], "conflict")
        kept = s.get(it.id)
        self.assertEqual(kept.rank, 1)
        self.assertNotIn("different counters", kept.body)
        s.put(again, actor="browser")                    # repeated disagreement: still one open conflict
        self.assertEqual(len([c for c in s.conflicts() if c["item_id"] == it.id]), 1)

    def test_same_or_higher_rank_updates(self):
        from agent_kb.store import LocalStore
        s = LocalStore()
        it = item(rank=2)
        s.put(it)
        it.body = "newer"
        it.rank = 1
        self.assertEqual(s.put(it)["result"], "updated")
        self.assertIn("newer", s.get(it.id).body)


class ConcurrentWritersTest(Env):         # P1-1
    def test_parallel_writers_leave_one_active_item(self):
        from agent_kb.store import LocalStore
        LocalStore()                                      # create and migrate the database first
        ctx = mp.get_context("spawn")
        start_at = time.time() + 4
        procs = [ctx.Process(target=_writer, args=(n, start_at)) for n in range(6)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(60)
        self.assertEqual([p.exitcode for p in procs], [0] * 6)
        active = LocalStore().find_meta(project="p", subject_key="tests", status="active")
        self.assertEqual(len(active), 1)


class HandEditTest(Env):                  # P1-2
    def test_hand_edit_reaches_search(self):
        from agent_kb.indexes import Query
        from agent_kb.query import search
        from agent_kb.store import LocalStore
        s = LocalStore()
        it = item(body="deploy with make ship")
        s.put(it)
        self.assertTrue(search(s, Query(text="ship", project=it.project)))
        path = s.path_for(it)
        time.sleep(0.05)
        path.write_text(path.read_text(encoding="utf-8").replace("make ship", "make deliver"), encoding="utf-8")
        self.assertTrue(search(s, Query(text="deliver", project=it.project)))
        self.assertFalse(search(s, Query(text="ship", project=it.project)))

    def test_deleted_and_added_files(self):
        from agent_kb.store import LocalStore
        s = LocalStore()
        it = item()
        s.put(it)
        text = s.path_for(it).read_text(encoding="utf-8")
        s.path_for(it).unlink()
        self.assertEqual(s.reconcile()["removed"], [it.id])
        self.assertIsNone(s.get(it.id))
        s.path_for(it).write_text(text, encoding="utf-8")
        self.assertEqual(s.reconcile()["added"], [it.id])
        self.assertEqual(s.reconcile(), {"edited": [], "added": [], "removed": [], "errors": []})


class UnknownKindTest(Env):               # P1-4
    def test_unknown_kind_is_read_and_reported_not_dropped(self):
        from agent_kb.model import Item
        from agent_kb.store import LocalStore
        s = LocalStore()
        future = Item(kind="task", project="p", subject_key="login", title="Fix login", body="body")
        path = s.kdir / "p" / "task" / f"{future.id}.md"
        path.parent.mkdir(parents=True)
        path.write_text(future.to_text(), encoding="utf-8")
        s.reconcile()
        self.assertEqual(s.get(future.id).title, "Fix login")
        self.assertEqual(s.unknown_kinds(), {"task": 1})
        self.assertEqual(s.rebuild_meta(), 1)
        with self.assertRaises(ValueError):              # writing still needs a registered kind
            s.put(Item(kind="task", project="p", subject_key="x"))


class SchemaVersionTest(Env):             # P1-8
    def test_v1_database_is_upgraded(self):
        from agent_kb import paths, schema, store
        home = paths.ensure_home()
        conn = sqlite3.connect(str(home / "kb.db"))
        conn.executescript(store._SCHEMA_V1)               # a v0.1.0 database: tables, user_version 0
        conn.close()
        s = store.LocalStore()
        self.assertEqual(schema.version(s.db), len(store.STEPS))
        self.assertTrue(schema.has_column(s.db, "items", "mtime"))

    def test_newer_database_is_refused(self):
        from agent_kb import paths, schema, store
        home = paths.ensure_home()
        conn = sqlite3.connect(str(home / "kb.db"))
        conn.execute(f"PRAGMA user_version={len(store.STEPS) + 5}")
        conn.close()
        with self.assertRaises(schema.SchemaTooNew):
            store.LocalStore()
