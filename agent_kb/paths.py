"""Locations and configuration. Everything lives under one local home (AGENT_KB_HOME)."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict

DEFAULT_CONFIG: Dict[str, Any] = {
    "version": 1,
    "indexes": {"fts": {"enabled": True}},
    "query": {"timeout_s": 2.0, "fusion_k": 60, "limit": 10},
    # Lower number = more trusted. Used when two sources disagree about one subject.
    "rank": {"manual": 1, "observed": 2, "confluence": 3, "jira": 4, "model": 5},
    "triggers": {
        "mode": "notify",                 # notify | background
        "min_sessions": 5,                # sessions since last tuning before a trigger may fire
        "cooldown_days": 7,
        "window_days": 7,
        "denied_total": 5,
        "denied_same_prefix": 3,
        "repeated_error": 3,
        "repeated_error_sessions": 2,
        "tool_error_rate": 0.10,
        "tool_error_min_calls": 20,
        "single_read_ratio": 0.25,
        "fixed_context_tokens": 25000,
        "fixed_context_growth": 0.20,
        "browser_output_share": 0.40,
    },
    "telemetry": {"raw_retention_days": 60},
    "harnesses": ["claude"],
}


def home() -> Path:
    """Read the env var on every call so tests and multiple homes work."""
    return Path(os.environ.get("AGENT_KB_HOME") or (Path.home() / ".agent-kb"))


def ensure_home() -> Path:
    h = home()
    for sub in ("knowledge", "index", "baselines", "outbox", "spool"):
        (h / sub).mkdir(parents=True, exist_ok=True)
    return h


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> Dict[str, Any]:
    path = home() / "config.json"
    user: dict = {}
    if path.exists():
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            user = {}
    return _merge(DEFAULT_CONFIG, user)


def write_default_config() -> Path:
    path = ensure_home() / "config.json"
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
    return path
