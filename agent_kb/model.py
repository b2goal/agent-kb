"""Knowledge items and their file format.

A knowledge item is one Markdown file with a front matter block. Each front matter line is
`key: <JSON value>`, which is also valid YAML (flow style), so files stay readable by any tool
while parsing needs nothing outside the standard library.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

KINDS = ("convention", "command", "guidance", "page", "edge", "flow", "pitfall", "doc", "note")
STATUSES = ("proposed", "active", "superseded", "stale", "retired")
FRONT_KEYS = ("id", "kind", "project", "subject_key", "title", "status", "rank", "supersedes",
              "superseded_by", "valid_from", "valid_to", "source", "evidence", "tags", "extra", "hash",
              "schema")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id(kind: str) -> str:
    return f"{kind[:4]}-{uuid.uuid4().hex[:12]}"


@dataclass
class Item:
    kind: str
    project: str
    subject_key: str
    title: str = ""
    body: str = ""
    status: str = "active"
    rank: int = 1
    source: Dict[str, Any] = field(default_factory=lambda: {"name": "manual"})
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    valid_from: str = field(default_factory=now_iso)
    valid_to: Optional[str] = None
    evidence: List[Any] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)
    id: str = ""
    hash: str = ""
    schema: int = 1

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown kind {self.kind!r}; expected one of {KINDS}")
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}")
        if not self.id:
            self.id = new_id(self.kind)

    # ------------------------------------------------------------------ content hash
    def content_hash(self) -> str:
        """Hash of what the item says (not of its bookkeeping), used for dedupe and change tracking."""
        payload = json.dumps([self.kind, self.project, self.subject_key, self.title, self.body.strip(),
                              self.extra], sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    # ------------------------------------------------------------------ file format
    def to_text(self) -> str:
        self.hash = self.content_hash()
        data = asdict(self)
        lines = ["---"]
        for key in FRONT_KEYS:
            lines.append(f"{key}: {json.dumps(data[key], ensure_ascii=False)}")
        lines += ["---", "", self.body.rstrip(), ""]
        return "\n".join(lines)

    @classmethod
    def from_text(cls, text: str) -> "Item":
        if not text.startswith("---"):
            raise ValueError("missing front matter")
        _, front, body = text.split("---", 2)
        data: Dict[str, Any] = {}
        for line in front.strip().splitlines():
            if not line.strip() or ":" not in line:
                continue
            key, raw = line.split(":", 1)
            raw = raw.strip()
            try:
                data[key.strip()] = json.loads(raw)
            except ValueError:
                data[key.strip()] = raw          # tolerate hand-edited plain scalars
        data["body"] = body.lstrip("\n").rstrip() + ("\n" if body.strip() else "")
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def summary(self) -> Dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "project": self.project, "subject_key": self.subject_key,
                "title": self.title, "status": self.status, "rank": self.rank,
                "source": (self.source or {}).get("name"), "valid_from": self.valid_from}
