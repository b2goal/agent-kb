"""Context pack (prototype): what past sessions on this project suggest for a new task. No model calls.

Phase 1 of retrieval: find the past sessions whose request and touched files/pages best match the new
request (BM25 over a small in-memory FTS5 table). Phase 2: aggregate what those sessions used: files edited
or read, the test command that passed, errors met, pages visited and actions that failed there.
Everything here is derived from telemetry (learned, unverified), so the pack says so.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter, OrderedDict
from typing import Dict, List, Optional
from urllib.parse import urlparse

from .browser import url_pattern
from .telemetry import Telemetry

TOP_SESSIONS = 3
MIN_RELATIVE_SCORE = 0.5        # keep a related session only if it scores at least half of the best one
MAX_LINES = 20
MAX_PAGES = 6
PAGES_PER_SESSION = 2
URL_IN_TEXT = re.compile(r"https?://\S+")


def _rel(path: Optional[str], cwd: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        rel = os.path.relpath(path, cwd) if cwd else path
    except ValueError:                          # another drive on Windows
        rel = path
    rel = rel.replace("\\", "/")
    return None if rel.startswith("..") else rel


def _words(text: str) -> List[str]:
    return [w for w in re.findall(r"\w+", (text or "").lower(), flags=re.UNICODE) if len(w) > 1]


def related_sessions(tele: Telemetry, project: str, prompt: str, top: int = TOP_SESSIONS) -> List[dict]:
    """Past sessions of this project ranked by how well their request + touched files/pages match `prompt`."""
    sessions = [s for s in tele.sessions(project) if s["prompt"]]
    words = _words(prompt)
    if not sessions or not words:
        return []
    db = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE ep USING fts5(sid UNINDEXED, prompt, things, "
               "tokenize='unicode61 remove_diacritics 2')")
    events: Dict[str, list] = {}
    for s in sessions:
        evs = tele.events(session_id=s["session_id"])
        events[s["session_id"]] = evs
        things = set()
        for e in evs:
            rel = _rel(e["file"], s["cwd"])
            if rel:
                things.add(rel.replace("/", " ").replace("_", " ").replace(".py", ""))
            pat = url_pattern(e["url"] or "")
            if pat:
                things.add(pat.replace("/", " ").replace(":", " "))
        db.execute("INSERT INTO ep VALUES (?,?,?)", (s["session_id"], s["prompt"], " ".join(sorted(things))))
    match = " OR ".join(f'"{w}"' for w in dict.fromkeys(words))
    rows = db.execute("SELECT sid, bm25(ep, 0.0, 2.0, 1.0) AS score FROM ep WHERE ep MATCH ? ORDER BY score LIMIT ?",
                      (match, top)).fetchall()
    by_id = {s["session_id"]: s for s in sessions}
    return [dict(session=by_id[sid], events=events[sid], score=-score) for sid, score in rows]


def _test_command(cmd: str) -> str:
    """The runner part of a recorded command: no 'cd <session dir> &&', no pipes or redirections."""
    parts = [p.strip() for p in re.split(r"&&|;", cmd)]
    runner = next((p for p in parts if re.search(r"unittest|pytest|npm test|go test|cargo test", p)), parts[-1])
    return re.sub(r"\s*2>&1", "", runner.split("|")[0]).strip()


def _destinations(evs: List[dict]) -> List[str]:
    """Pages a session ended up on, most recent first: full URLs (query kept), minus login/logout and bare roots."""
    seen: "OrderedDict[str, None]" = OrderedDict()
    for e in evs:
        if e["category"] != "browser" or not e["url"] or e["outcome"] == "error":
            continue
        u = urlparse(e["url"])
        path = u.path.rstrip("/")
        if not path or re.search(r"(log|sign)[-_]?(in|out)$", path, re.I):
            continue
        full = f"{u.scheme}://{u.netloc}{u.path}" + (f"?{u.query}" if u.query else "")
        seen.pop(full, None)
        seen[full] = None
    return list(reversed(seen))


def _relogged(evs: List[dict]) -> bool:
    """The session logged out and in again (typically: the first account lacked access)."""
    urls = [str(e["url"] or "") for e in evs if e["category"] == "browser"]
    out = next((i for i, u in enumerate(urls) if re.search(r"(log|sign)[-_]?out", u, re.I)), None)
    return out is not None and any(re.search(r"(log|sign)[-_]?in", u, re.I) for u in urls[out + 1:])


def build(prompt: str, project: str, tele: Optional[Telemetry] = None, max_lines: int = MAX_LINES) -> str:
    tele = tele or Telemetry()
    related = related_sessions(tele, project, prompt)
    if not related:
        return ""
    related = [r for r in related if r["score"] >= MIN_RELATIVE_SCORE * related[0]["score"]]
    browser_task = bool(URL_IN_TEXT.search(prompt)) or any(
        e["category"] == "browser" for e in related[0]["events"])
    files: Counter = Counter()
    edited: set = set()
    tests: Counter = Counter()
    errors: Counter = Counter()
    pages: List[str] = []
    failed: Counter = Counter()
    relogged = False
    for rank, r in enumerate(related):
        w = 1.0 / (rank + 1)
        s, evs = r["session"], r["events"]
        for name, n in json.loads(s["test_commands"] or "{}").items():
            tests[_test_command(name)] += n * w
        pages += [u for u in _destinations(evs) if u not in pages][:PAGES_PER_SESSION]   # every related session gets a say
        relogged = relogged or _relogged(evs)
        for e in evs:
            rel = _rel(e["file"], s["cwd"])
            if rel and e["category"] == "edit":
                files[rel] += 3 * w
                edited.add(rel)
            elif rel and e["category"] == "read":
                files[rel] += w
            if e["error_sig"] and e["outcome"] == "error" and e["category"] != "browser":
                errors[e["error_sig"][:120]] += w
            if e["category"] == "browser" and e["outcome"] == "error" and (e["target"] or "").startswith("act:"):
                failed[f"{url_pattern(e['url'] or '') or 'a page'}: {e['target'][4:60]}"] += 1
    lines = [f"Context for this task (agent-kb, learned from {len(related)} related past session(s); "
             "unverified, check before relying on it):"]
    lines.append("- Related past requests: " + " | ".join(
        f"\"{(r['session']['prompt'] or '').splitlines()[0][:90]}\"" for r in related))
    code = [f for f, _ in files.most_common() if not f.startswith("tests/")][:6]
    if code:
        lines.append("- Files that mattered: " + ", ".join(f + (" (edited)" if f in edited else "") for f in code))
    test_files = [f for f, _ in files.most_common() if f.startswith("tests/")][:3]
    if test_files or tests:
        t = "- Tests: " + ", ".join(test_files)
        if tests:
            t += (" · " if test_files else "") + "run: " + tests.most_common(1)[0][0]
        lines.append(t)
    for sig, _ in errors.most_common(2):
        lines.append(f"- Error met there: {sig}")
    if browser_task and pages:
        lines.append("- Pages those sessions ended on, latest first (open directly instead of browsing menus):")
        lines += [f"  - {u}" for u in pages[:MAX_PAGES]]
    if browser_task and relogged:
        lines.append("- A related session had to log out and in again with another account to reach its page.")
    if browser_task:
        for what, n in failed.most_common(3):
            lines.append(f"- Failed action seen {n}x on {what}")
    return "\n".join(lines[:max_lines])


def hook_output(payload: Dict[str, object]) -> Optional[str]:
    """UserPromptSubmit hook: returns the hook JSON with the pack as additional context, or None."""
    from .project import project_id
    prompt = str(payload.get("prompt") or "")
    cwd = str(payload.get("cwd") or ".")
    text = build(prompt, project_id(cwd)) if prompt.strip() else ""
    if not text:
        return None
    return json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}},
                      ensure_ascii=False)
