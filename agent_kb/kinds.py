"""Kind registry: every kind of knowledge item is declared here against one contract.

Writing an item requires a registered kind. Reading never does: a file whose kind this version does not
know (written by a newer agent-kb, or by hand) is still loaded, indexed and searchable, and `kb doctor`
lists it, so nothing disappears silently.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


@dataclass(frozen=True)
class Kind:
    name: str
    description: str
    source: str = "file"                  # where the truth lives: file | derived (rebuilt from events)
    review_days: Optional[int] = None     # None = never expires
    delivered: bool = False               # exported into CLAUDE.md (always-loaded tier)


REGISTRY: Dict[str, Kind] = {k.name: k for k in [
    Kind("convention", "A project rule the agent must follow", delivered=True, review_days=90),
    Kind("command", "How to run something (tests, build, app)", delivered=True, review_days=90),
    Kind("guidance", "Working-style guidance produced by kb tune", delivered=True, review_days=90),
    Kind("doc", "Summary + link to a longer document"),
    Kind("note", "Free-form note"),
    Kind("page", "A page of a web app, keyed by URL pattern", review_days=30),
    Kind("edge", "A move between two pages (learned)", source="derived", review_days=30),
    Kind("flow", "A repeated chain of page moves (learned)", source="derived", review_days=30),
    Kind("pitfall", "An action that keeps failing on a page (learned)", source="derived", review_days=30),
]}


def valid_name(name: str) -> bool:
    return bool(NAME_RE.match(name or ""))


def is_known(name: str) -> bool:
    return name in REGISTRY


def require(name: str) -> Kind:
    if name not in REGISTRY:
        raise ValueError(f"unknown kind {name!r}; registered: {', '.join(REGISTRY)}")
    return REGISTRY[name]


def delivered() -> list:
    return [k.name for k in REGISTRY.values() if k.delivered]
