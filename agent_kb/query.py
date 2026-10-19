"""The one query API every client uses: candidates from enabled indexes -> fusion -> filter.

Each index runs with a timeout; a failing or slow index is skipped. If every index fails,
a plain scan of the store answers, so queries always return something.
"""
from __future__ import annotations

import concurrent.futures as cf
from typing import Dict, List, Optional

from .indexes import Query, enabled_indexes
from .model import Item
from .paths import load_config

egress_filters: list = []   # filter_on_egress: empty in v1 (data leaving for an external model)


def _fallback(store, q: Query) -> List[tuple]:
    words = [w.lower() for w in (q.text or "").split() if len(w) > 1]
    hits = []
    for item in store.all_items():
        if q.statuses and item.status not in q.statuses:
            continue
        if q.project and item.project not in (q.project, "global"):
            continue
        if q.kinds and item.kind not in q.kinds:
            continue
        hay = f"{item.title} {item.subject_key} {item.body}".lower()
        score = sum(hay.count(w) for w in words)
        if score:
            hits.append((item.id, float(score)))
    return sorted(hits, key=lambda h: -h[1])[: q.limit]


def search(store, q: Query, config: Optional[dict] = None) -> List[Dict[str, object]]:
    config = config or load_config()
    timeout = float(config["query"]["timeout_s"])
    k = int(config["query"]["fusion_k"])
    indexes = enabled_indexes(config)
    store.reconcile()                  # pick up files edited by hand before any index answers
    rankings: List[List[tuple]] = []
    used: List[str] = []

    def run(ix):
        return ix.query(q)

    live = []
    for ix in indexes:                 # incremental update on this thread (store connection is not shared)
        try:
            ix.update(store)
            live.append(ix)
        except Exception:
            continue
    indexes = live
    if indexes:
        with cf.ThreadPoolExecutor(max_workers=len(indexes)) as pool:
            futs = {pool.submit(run, ix): ix for ix in indexes}
            for fut, ix in futs.items():
                try:
                    hits = fut.result(timeout=timeout)
                    rankings.append(hits)
                    used.append(ix.name)
                except Exception:
                    continue
    if not rankings:
        rankings = [_fallback(store, q)]
        used = ["scan"]

    fused: Dict[str, float] = {}
    for hits in rankings:                       # reciprocal rank fusion: scale-free across indexes
        for pos, (item_id, _score) in enumerate(hits):
            fused[item_id] = fused.get(item_id, 0.0) + 1.0 / (k + pos + 1)
    out = []
    for item_id, score in sorted(fused.items(), key=lambda kv: -kv[1])[: q.limit]:
        item: Item = store.get(item_id)
        if item is None or (q.statuses and item.status not in q.statuses):
            continue
        row = dict(item.summary(), score=round(score, 5), via=used)
        for f in egress_filters:
            row = f(row)
        out.append(row)
    return out
