"""Browser knowledge: a page graph learned from browser tool events.

Node = page (kind "page"), keyed by a URL pattern (/orders/123 -> /orders/:id).
Edge = a transition (kind "edge"): an action on page A followed by being on page B.
Both are knowledge items from the "observed" source (rank 2), so a person's notes (rank 1) win,
and an edge that keeps failing becomes "stale".
"""
from __future__ import annotations

import hashlib
import heapq
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .model import Item, now_iso
from .paths import load_config
from .store import LocalStore
from .telemetry import Telemetry

ID_SEG = re.compile(r"^(\d+|[0-9a-f]{8,}|[0-9a-f-]{32,36}|[A-Za-z0-9_-]{20,})$", re.I)


def url_pattern(url: str) -> Optional[str]:
    if not url or not re.match(r"^https?://", url):
        return None
    u = urlparse(url)
    segs = [(":id" if ID_SEG.match(s) else s) for s in u.path.split("/") if s]
    host = u.hostname or ""
    if u.port:
        host += f":{u.port}"
    return host + "/" + "/".join(segs)


def _sid(prefix: str, *parts: str) -> str:
    return f"{prefix}-" + hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def _action_label(target: str) -> Tuple[str, str]:
    kind, _, rest = (target or "act:?").partition(":")
    return kind, rest or "?"


def learn(project: str, tele: Optional[Telemetry] = None, store: Optional[LocalStore] = None) -> Dict[str, int]:
    """Rebuild page/edge observations for a project from its browser events (idempotent)."""
    tele = tele or Telemetry()
    store = store or LocalStore()
    rank = int(load_config()["rank"].get("observed", 2))
    rows = [r for r in tele.events(project) if r["category"] == "browser"]
    by_session: Dict[str, List] = defaultdict(list)
    for r in rows:
        by_session[r["session_id"]].append(r)

    pages: Dict[str, Dict[str, object]] = {}
    edges: Dict[Tuple[str, str, str], Dict[str, object]] = {}
    failures: Dict[Tuple[str, str], Dict[str, object]] = {}          # (page, action) -> count, sessions
    walks: List[List[Tuple[str, str, str]]] = []                     # per session: edges in order
    for evs in by_session.values():
        walk: List[Tuple[str, str, str]] = []
        evs.sort(key=lambda r: (r["ts"] or "", r["id"]))
        current: Optional[str] = None
        pending: Optional[Tuple[str, str, bool]] = None     # (from_page, action, ok) waiting for the next page
        for r in evs:
            pat = url_pattern(r["url"] or "")
            kind, label = _action_label(r["target"] or "")
            ok = r["outcome"] in ("ok", "approved_by_user")
            if pat:
                p = pages.setdefault(pat, {"url": r["url"], "observe": 0, "act": 0, "fail": 0, "sessions": set()})
                p["sessions"].add(r["session_id"])
                if pending and pending[0] != pat:
                    key = (pending[0], pat, pending[1])
                    e = edges.setdefault(key, {"ok": 0, "fail": 0, "last": None})
                    e["ok" if pending[2] else "fail"] += 1
                    e["last"] = r["ts"]
                    if pending[2]:
                        walk.append(key)
                    pending = None
                current = pat
            if current:
                pg = pages[current]
                pg["observe" if kind == "observe" else "act"] += 1
                pg["fail"] += 0 if ok else 1
                if kind == "act" and not ok:
                    f = failures.setdefault((current, label[:80]), {"n": 0, "sessions": set()})
                    f["n"] += 1
                    f["sessions"].add(r["session_id"])
                if kind == "act":
                    action = "navigate" if "navigate" in (r["tool"] or "").lower() else label
                    if action == "navigate" and pat and pat != current:
                        pass                                     # navigate events carry the new url themselves
                    pending = (current, action[:80], ok)
        walks.append(walk)

    out = {"pages": 0, "edges": 0, "stale": 0, "flows": 0, "pitfalls": 0}
    for pat, p in pages.items():
        it = Item(kind="page", project=project, subject_key=pat, title=pat, rank=rank,
                  source={"name": "observed", "via": "kb browser learn"},
                  body=f"Example URL: {p['url']}\nObserved in {len(p['sessions'])} session(s).",
                  extra={"url": p["url"], "observe": p["observe"], "act": p["act"], "fail": p["fail"],
                         "sessions": len(p["sessions"])},
                  id=_sid("page", project, pat))
        store.put(it, actor="kb browser learn")
        out["pages"] += 1
    for (a, b, action), e in edges.items():
        status = "stale" if e["fail"] >= 2 and e["fail"] > e["ok"] else "active"
        it = Item(kind="edge", project=project, subject_key=f"{a} -> {b}", title=f"{action}", rank=rank,
                  status=status, source={"name": "observed", "via": "kb browser learn"},
                  body=f"On {a}: {action} -> {b}",
                  extra={"from": a, "to": b, "action": action, "ok": e["ok"], "fail": e["fail"], "last": e["last"]},
                  id=_sid("edge", project, a, b, action))
        store.put(it, actor="kb browser learn")
        out["edges"] += 1
        out["stale"] += status == "stale"

    # pitfalls: the same action failing on the same page again and again
    for (page, action), f in failures.items():
        if f["n"] >= 2:
            it = Item(kind="pitfall", project=project, subject_key=f"{page} :: {action}", title=f"{action} fails on {page}",
                      rank=rank, source={"name": "observed", "via": "kb browser learn"},
                      body=f"On {page}, action '{action}' failed {f['n']} time(s) in {len(f['sessions'])} session(s). "
                           f"Check for a modal, a loading state or a changed label before retrying.",
                      extra={"page": page, "action": action, "fails": f["n"], "sessions": len(f["sessions"])},
                      id=_sid("pitf", project, page, action))
            store.put(it, actor="kb browser learn")
            out["pitfalls"] += 1

    # flows: chains of 2+ successful transitions repeated in >= 3 sessions
    seen: Dict[Tuple, set] = defaultdict(set)
    for i, walk in enumerate(walks):
        for n in range(2, min(6, len(walk)) + 1):
            for j in range(len(walk) - n + 1):
                chain = tuple(walk[j:j + n])
                if all(chain[k][1] == chain[k + 1][0] for k in range(n - 1)):
                    seen[chain].add(i)
    for chain, sess in seen.items():
        if len(sess) >= 3:
            steps = [{"on": a, "action": act, "to": b} for a, b, act in chain]
            it = Item(kind="flow", project=project, subject_key=f"{chain[0][0]} => {chain[-1][1]}",
                      title=f"{chain[0][0]} => {chain[-1][1]}", rank=rank,
                      source={"name": "observed", "via": "kb browser learn"},
                      body="\n".join(f"{k + 1}. On {st['on']}: {st['action']} -> {st['to']}" for k, st in enumerate(steps)),
                      extra={"steps": steps, "sessions": len(sess)},
                      id=_sid("flow", project, *[f"{a}|{b}|{c}" for a, b, c in chain]))
            store.put(it, actor="kb browser learn")
            out["flows"] += 1
    return out


def _match_page(pages: List[Item], query: str) -> List[Item]:
    q = (query or "").lower().strip()
    pat = url_pattern(query) if re.match(r"^https?://", query or "") else None
    if pat:
        exact = [p for p in pages if p.subject_key == pat]
        if exact:
            return exact
    words = [w for w in re.split(r"[\s/]+", q) if w]
    scored = []
    for p in pages:
        hay = f"{p.subject_key} {p.title} {p.body}".lower()
        s = sum(hay.count(w) for w in words)
        if s:
            scored.append((s, p))
    return [p for _, p in sorted(scored, key=lambda t: -t[0])]


def find_pages(project: str, query: str, store: Optional[LocalStore] = None) -> List[Item]:
    store = store or LocalStore()
    return _match_page(store.find(project=project, kind="page", status="active"), query)


def path(project: str, to_query: str, from_url: Optional[str] = None,
         store: Optional[LocalStore] = None) -> Dict[str, object]:
    """Cheapest reliable route. Weight = 1 per step + failure penalty; opening a known URL directly
    is offered as a one-step route when the target page has an example URL."""
    store = store or LocalStore()
    pages = store.find(project=project, kind="page", status="active")
    targets = _match_page(pages, to_query)
    if not targets:
        return {"found": False, "reason": f"no known page matches {to_query!r}"}
    target = targets[0]
    direct = {"found": True, "target": target.subject_key,
              "steps": [{"action": "navigate", "url": target.extra.get("url"), "to": target.subject_key}],
              "note": "open the URL directly (needs the same login/session state)"}
    start = url_pattern(from_url) if from_url else None
    if not start or start == target.subject_key:
        return direct
    graph: Dict[str, List[Tuple[float, str, Item]]] = defaultdict(list)
    for e in store.find(project=project, kind="edge", status="active"):
        ok, fail = int(e.extra.get("ok", 0)), int(e.extra.get("fail", 0))
        w = 1.0 + 2.0 * fail / max(ok + fail, 1)
        graph[e.extra["from"]].append((w, e.extra["to"], e))
    best = {start: 0.0}
    heap = [(0.0, start, [])]
    while heap:
        cost, node, steps = heapq.heappop(heap)
        if node == target.subject_key:
            return {"found": True, "target": node, "cost": round(cost, 2), "via": "graph",
                    "steps": [{"on": s.extra["from"], "action": s.extra["action"], "to": s.extra["to"],
                               "ok": s.extra.get("ok"), "fail": s.extra.get("fail")} for s in steps],
                    "alternative": direct["steps"]}
        if cost > best.get(node, float("inf")):
            continue
        for w, nxt, e in graph.get(node, []):
            nc = cost + w
            if nc < best.get(nxt, float("inf")):
                best[nxt] = nc
                heapq.heappush(heap, (nc, nxt, steps + [e]))
    return dict(direct, via="direct (no known click path)")


def mermaid(project: str, store: Optional[LocalStore] = None) -> str:
    store = store or LocalStore()
    ids: Dict[str, str] = {}
    lines = ["flowchart LR"]
    for i, p in enumerate(store.find(project=project, kind="page", status="active")):
        ids[p.subject_key] = f"p{i}"
        lines.append(f'  p{i}["{p.subject_key}"]')
    for e in store.find(project=project, kind="edge", status=["active", "stale"]):
        a, b = ids.get(e.extra["from"]), ids.get(e.extra["to"])
        if a and b:
            style = "-.->" if e.status == "stale" else "-->"
            lines.append(f'  {a} {style}|{e.extra["action"][:30]}| {b}')
    return "\n".join(lines) + "\n"
