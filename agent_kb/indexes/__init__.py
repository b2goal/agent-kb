"""Index plug-ins. Every index is derived from the store and can be dropped and rebuilt.

An index implements: build(store), update(store), query(q) -> [(item_id, score)], health().
Register new ones in REGISTRY or name them in config as "module:Class" (loaded lazily).
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, Tuple


@dataclass
class Query:
    text: str
    project: Optional[str] = None
    kinds: Optional[List[str]] = None
    statuses: List[str] = field(default_factory=lambda: ["active"])
    limit: int = 10


Hit = Tuple[str, float]


class Index(Protocol):
    name: str
    version: str

    def build(self, store) -> int: ...
    def update(self, store) -> int: ...
    def query(self, q: Query) -> List[Hit]: ...
    def health(self) -> Dict[str, object]: ...


def _registry() -> Dict[str, str]:
    return {"fts": "agent_kb.indexes.fts:FTSIndex"}


def load_index(name: str, spec: Optional[str] = None):
    target = spec or _registry().get(name)
    if not target:
        raise KeyError(f"unknown index {name!r}")
    module, cls = target.split(":")
    return getattr(importlib.import_module(module), cls)()


def enabled_indexes(config: dict) -> List[object]:
    out = []
    for name, opts in (config.get("indexes") or {}).items():
        if isinstance(opts, dict) and opts.get("enabled"):
            try:
                out.append(load_index(name, opts.get("class")))
            except Exception:      # a broken plug-in must never break queries
                continue
    return out
