"""Core tests: store precedence, index/query, shell parsing, transcript parsing, tune, CLI.

Run: python -m unittest discover -s tests -t .
Each test uses its own AGENT_KB_HOME and CLAUDE_CONFIG_DIR in a temp folder.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old = {k: os.environ.get(k) for k in ("AGENT_KB_HOME", "CLAUDE_CONFIG_DIR")}
        os.environ["AGENT_KB_HOME"] = str(self.root / "kb")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.root / "claude")
        from agent_kb import project
        project.project_id.cache_clear()

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def repo(self, remote="git@github.com:Me/Shop.git") -> Path:
        r = self.root / "repo"
        r.mkdir(exist_ok=True)
        subprocess.run(["git", "init", "-q", str(r)], check=True)
        subprocess.run(["git", "-C", str(r), "remote", "add", "origin", remote], check=True)
        return r


def item(**kw):
    from agent_kb.model import Item
    base = dict(kind="convention", project="github.com/me/shop", subject_key="tests", title="Run tests",
                body="pytest -q", rank=2, source={"name": "observed"})
    base.update(kw)
    return Item(**base)


class StoreTest(Env):
    def test_file_roundtrip(self):
        from agent_kb.model import Item
        a = item(body="line one\nline: two", extra={"k": [1, 2]}, tags=["x"])
        b = Item.from_text(a.to_text())
        self.assertEqual((b.body.strip(), b.extra, b.tags, b.hash), ("line one\nline: two", {"k": [1, 2]}, ["x"], a.hash))

    def test_same_rank_newer_supersedes(self):
        from agent_kb.store import LocalStore
        s = LocalStore()
        a, b = item(body="pytest -q"), item(body="python -m unittest")
        s.put(a)
        res = s.put(b)
        self.assertEqual(res["superseded"], [a.id])
        self.assertEqual(s.get(a.id).status, "superseded")
        self.assertEqual(s.get(a.id).superseded_by, b.id)

    def test_less_trusted_conflicts_instead_of_overwriting(self):
        from agent_kb.store import LocalStore
        s = LocalStore()
        a = item()
        s.put(a)
        c = item(body="make test", rank=4, source={"name": "jira"})
        res = s.put(c)
        self.assertEqual(res["result"], "conflict")
        self.assertEqual(s.get(c.id).status, "proposed")
        self.assertEqual(s.get(a.id).status, "active")
        s.confirm(c.id)
        self.assertEqual(s.get(c.id).status, "active")
        self.assertEqual(s.get(a.id).status, "superseded")
        self.assertEqual(len(s.conflicts()), 0)

    def test_duplicate_is_unchanged_or_upgraded(self):
        from agent_kb.store import LocalStore
        s = LocalStore()
        a = item()
        s.put(a)
        self.assertEqual(s.put(item())["result"], "unchanged")
        self.assertEqual(s.put(item(rank=1))["result"], "updated")
        self.assertEqual(s.get(a.id).rank, 1)

    def test_write_filter_can_drop(self):
        from agent_kb.store import LocalStore
        s = LocalStore()
        s.write_filters.append(lambda it: None)
        self.assertEqual(s.put(item())["result"], "dropped")

    def test_rebuild_meta_from_files(self):
        from agent_kb.store import LocalStore
        s = LocalStore()
        s.put(item())
        s.db.execute("DELETE FROM items")
        self.assertEqual(s.rebuild_meta(), 1)


class QueryTest(Env):
    def test_fts_follows_change_log_and_filters_status(self):
        from agent_kb.indexes import Query
        from agent_kb.query import search
        from agent_kb.store import LocalStore
        s = LocalStore()
        a = item(subject_key="login", title="Login flow", body="Use the SSO button")
        s.put(a)
        hits = search(s, Query(text="sso login", project="github.com/me/shop"))
        self.assertEqual([h["id"] for h in hits], [a.id])
        self.assertEqual(hits[0]["via"], ["fts"])
        s.put(item(subject_key="login", title="Login flow", body="Use the password form"))
        self.assertEqual(search(s, Query(text="sso", project="github.com/me/shop")), [])

    def test_broken_index_falls_back_to_scan(self):
        from agent_kb.indexes import Query
        from agent_kb.query import search
        from agent_kb.store import LocalStore
        s = LocalStore()
        s.put(item(title="Deploy", body="deploy with make release", subject_key="deploy"))
        cfg = {"indexes": {"fts": {"enabled": True, "class": "nope.module:Missing"}},
               "query": {"timeout_s": 1, "fusion_k": 60, "limit": 10}}
        hits = search(s, Query(text="deploy release"), cfg)
        self.assertEqual(hits[0]["via"], ["scan"])


class ShellTest(unittest.TestCase):
    def test_prefixes_and_compound(self):
        from agent_kb.shellparse import is_compound, prefixes, risk
        self.assertEqual(prefixes("cd x && npm test -- -u 2>&1 | tail -5"), ["npm test", "tail"])
        self.assertEqual(prefixes("sed -i 's/a;b/c/' f && python -m pytest -q"), ["sed -i", "python -m pytest"])
        self.assertEqual(prefixes("python - <<'E'\nimport os; os.system('x')\nE"), ["python"])
        self.assertTrue(is_compound("cd a; ls"))
        self.assertFalse(is_compound("python - <<'E'\na;b\nE"))
        self.assertEqual([risk(p) for p in ("rm", "git push", "python", "python -m pytest", "grep")],
                         ["never", "never", "review", "safe", "safe"])

    def test_error_signature_strips_values(self):
        from agent_kb.shellparse import error_signature
        sig = error_signature("Traceback\nshopkit.errors.ValidationError: bad sku: 'A' at /x/y.py line 12")
        self.assertEqual(sig, "ValidationError: bad sku: '…' at <path> line N")


def _transcript(path: Path, cwd: str) -> None:
    sid = "sess-1"

    def a(mid, blocks, usage):
        return {"type": "assistant", "sessionId": sid, "cwd": cwd, "timestamp": "2026-10-18T01:00:00Z",
                "message": {"id": mid, "model": "claude-sonnet", "content": blocks, "usage": usage}}

    def u(tid, text, err=False):
        return {"type": "user", "sessionId": sid, "cwd": cwd,
                "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": err}]}}

    use = lambda i, n, inp: {"type": "tool_use", "id": i, "name": n, "input": inp}  # noqa: E731
    rows = [
        a("m1", [use("t1", "Read", {"file_path": "a.py"}), use("t2", "Read", {"file_path": "b.py"})],
          {"input_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 20000, "output_tokens": 50}),
        u("t1", "x"), u("t2", "y"),
        a("m2", [use("t3", "Bash", {"command": "cd sub && wc -l $(git ls-files)"})],
          {"input_tokens": 5, "cache_read_input_tokens": 20000, "cache_creation_input_tokens": 500, "output_tokens": 30}),
        u("t3", "Permission for this tool use was denied. It requires approval", True),
        a("m3", [use("t4", "Bash", {"command": "python -m pytest -q"})],
          {"input_tokens": 5, "cache_read_input_tokens": 20500, "cache_creation_input_tokens": 400, "output_tokens": 30}),
        u("t4", "E   shopkit.errors.ValidationError: bad sku: 'A'", True),
        a("m4", [{"type": "text", "text": "done"}],
          {"input_tokens": 5, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 20900, "output_tokens": 10}),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


class TranscriptAndTuneTest(Env):
    def test_parse_summary_and_events(self):
        from agent_kb import transcript as tr
        f = self.root / "t.jsonl"
        _transcript(f, "/x")
        p = tr.parse(f)
        s = tr.summarize(p)
        self.assertEqual((s["api_calls"], s["tool_calls"], s["parallel_turns"], s["denied"], s["errors"]), (4, 4, 1, 1, 1))
        self.assertEqual(s["cache_breaks"], 1)          # m4 read far less from cache than m3's context
        ev = {e["tool_use_id"]: e for e in tr.tool_events(p)}
        self.assertEqual(ev["t3"]["compound"], 1)
        self.assertEqual(ev["t4"]["error_sig"], "ValidationError: bad sku: '…'")

    def test_ingest_stats_tune_apply(self):
        from agent_kb.adapters import claude_code
        from agent_kb import tune
        from agent_kb.stats import summary
        from agent_kb.telemetry import Telemetry
        r = self.repo()
        _transcript(self.root / "claude" / "projects" / "p" / "sess-1.jsonl", str(r))
        hook = {"hook_event_name": "PermissionRequest", "session_id": "sess-1", "tool_use_id": "t1", "tool_name": "Read"}
        claude_code.handle_hook(hook)
        self.assertEqual(claude_code.ingest_all()["ingested"], 1)
        self.assertEqual(claude_code.ingest_all()["ingested"], 0)          # cursor: unchanged file skipped
        tele = Telemetry()
        s = summary(tele, "github.com/me/shop", days=None)
        self.assertEqual((s["sessions"], s["denied"], s["denied_compound"], s["approved"]), (1, 1, 1, 1))
        ev = tune.evaluate(tele, "github.com/me/shop", manual=True)
        props = tune.proposals(ev["summary"])
        kinds = {p["type"] for p in props}
        self.assertIn("guidance", kinds)
        self.assertNotIn("error_convention", kinds)        # one error is not yet a pattern (needs >= 2)
        self.assertEqual(ev["summary"]["repeated_errors"][0]["signature"], "ValidationError: bad sku: '…'")
        box = tune.write_outbox("github.com/me/shop", ev, props)
        res = tune.apply(box, str(r), select=[p["n"] for p in props if p["type"] == "guidance"])
        md = (r / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("avoid `cd … &&`", md)
        self.assertNotIn("python -m pytest -q", md)       # only test commands that succeeded are proposed
        self.assertTrue(Path(res["baseline"]).exists())
        tune.write_managed_block(r / "CLAUDE.md", tune.export_claude_md(__import__("agent_kb.store").store.LocalStore(),
                                                                        "github.com/me/shop"))
        self.assertEqual((r / "CLAUDE.md").read_text(encoding="utf-8").count("agent-kb:start"), 1)

    def test_setup_is_idempotent_and_keeps_existing_statusline(self):
        from agent_kb.adapters import claude_code
        sp = self.root / "claude" / "settings.json"
        sp.parent.mkdir(parents=True)
        sp.write_text(json.dumps({"statusLine": {"type": "command", "command": "mine"}}))
        first = claude_code.setup()
        second = claude_code.setup()
        data = json.loads(sp.read_text())
        self.assertEqual(len(first["hooks_added"]), 5)
        self.assertEqual(second["hooks_added"], [])
        self.assertEqual(data["statusLine"]["command"], "mine")


class CliTest(Env):
    def run_kb(self, *args, stdin=""):
        out = io.StringIO()
        old_in = sys.stdin
        sys.stdin = io.StringIO(stdin)
        try:
            with redirect_stdout(out):
                from agent_kb.cli import main
                try:
                    main(list(args))
                except SystemExit as e:
                    code = e.code
        finally:
            sys.stdin = old_in
        return code, out.getvalue()

    def test_add_search_get_and_hook_never_fails(self):
        r = self.repo()
        code, out = self.run_kb("add", "convention", "login", "--dir", str(r), "--body", "Use SSO button")
        self.assertEqual(code, 0)
        item_id = json.loads(out)["id"]
        code, out = self.run_kb("search", "sso", "--dir", str(r))
        self.assertIn(item_id, out)
        code, out = self.run_kb("get", item_id)
        self.assertIn("Use SSO button", out)
        code, _ = self.run_kb("hook", "claude", stdin="not json at all")
        self.assertEqual(code, 0)
        code, out = self.run_kb("statusline", stdin=json.dumps({"cwd": str(r)}))
        self.assertTrue(out.startswith("kb"))


if __name__ == "__main__":
    unittest.main()


class BrowserTest(Env):
    def _session(self, r: Path) -> None:
        sid = "sess-b"
        base = "http://localhost:3000"

        def a(mid, name, inp):
            return {"type": "assistant", "sessionId": sid, "cwd": str(r), "timestamp": f"2026-10-18T02:00:{mid:02d}Z",
                    "message": {"id": f"m{mid}", "model": "claude-sonnet", "usage": {"input_tokens": 10, "output_tokens": 5},
                                "content": [{"type": "tool_use", "id": f"t{mid}", "name": name, "input": inp}]}}

        def u(mid, text, err=False):
            return {"type": "user", "sessionId": sid, "cwd": str(r),
                    "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{mid}", "content": text, "is_error": err}]}}

        nav, comp, read = "mcp__claude-in-chrome__navigate", "mcp__claude-in-chrome__computer", "mcp__claude-in-chrome__read_page"
        rows = [a(1, nav, {"url": base + "/login"}), u(1, "Navigated to " + base + "/login"),
                a(2, read, {}), u(2, "page " + base + "/login form"),
                a(3, comp, {"action": "left_click", "ref": "SSO button"}), u(3, "clicked"),
                a(4, read, {}), u(4, "now at " + base + "/orders/123"),
                a(5, comp, {"action": "left_click", "ref": "Export"}), u(5, "Error: element not found", True)]
        f = self.root / "claude" / "projects" / "p" / "sess-b.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8")

    def test_learn_pages_edges_and_path(self):
        from agent_kb import browser
        from agent_kb.adapters import claude_code
        from agent_kb.store import LocalStore
        self.assertEqual(browser.url_pattern("https://a.b:8080/orders/123/items/9f8e7d6c5b?x=1"),
                         "a.b:8080/orders/:id/items/:id")
        r = self.repo()
        self._session(r)
        claude_code.ingest_all()
        res = browser.learn("github.com/me/shop")
        self.assertEqual((res["pages"], res["edges"]), (2, 1))
        s = LocalStore()
        edge = s.find(project="github.com/me/shop", kind="edge")[0]
        self.assertEqual((edge.extra["from"], edge.extra["to"], edge.extra["action"]),
                         ("localhost:3000/login", "localhost:3000/orders/:id", "SSO button"))
        route = browser.path("github.com/me/shop", "orders", from_url="http://localhost:3000/login")
        self.assertEqual(route["via"], "graph")
        self.assertEqual(route["steps"][0]["action"], "SSO button")
        self.assertEqual(browser.learn("github.com/me/shop"), res)          # idempotent
        self.assertIn("-->|SSO button|", browser.mermaid("github.com/me/shop"))
