"""Parse Claude Code logs (transcripts in ~/.claude/projects, or stream-json) into
one session summary + normalized tool events. Verified against Claude Code 2.1.x logs:
an API response is split over several lines sharing message.id; usage repeats and grows.
"""
from __future__ import annotations

import json
import re
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from . import shellparse

CACHE_BREAK_MIN = 4096
CACHE_BREAK_RATIO = 0.5
URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")
DENY_TEXT = re.compile(r"(permission .*denied|requires approval|was denied|not allowed|blocked by)", re.I)


def category(tool: str) -> str:
    t = tool or ""
    low = t.lower()
    if t in ("Read", "NotebookRead"):
        return "read"
    if t in ("Grep", "Glob", "LS"):
        return "search"
    if t in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return "edit"
    if t in ("Bash", "PowerShell", "BashOutput"):
        return "shell"
    if t in ("Agent", "Task"):
        return "subagent"
    if t in ("TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet"):
        return "todo"
    if t == "Skill":
        return "skill"
    if t in ("WebFetch", "WebSearch"):
        return "web"
    if any(k in low for k in ("claude-in-chrome", "claude_browser", "browser", "playwright", "puppeteer")):
        return "browser"
    if low.startswith("mcp__"):
        return "mcp"
    return "other"


OBSERVE_HINT = ("screenshot", "read_page", "get_page_text", "find", "read_console", "read_network",
                "tabs_context", "snapshot", "zoom", "get_text", "inspect")


def browser_kind(tool: str, inp: dict) -> str:
    """'observe' (look at the page) or 'act' (change it). Used for the exploration metric."""
    low = (tool or "").lower()
    action = str((inp or {}).get("action") or "").lower()
    if any(h in low for h in OBSERVE_HINT) or action in ("screenshot", "zoom", "scroll", "wait", "mouse_move"):
        return "observe"
    return "act"


def iter_json(path: Path) -> Iterable[dict]:
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("{"):
                try:
                    yield json.loads(line)
                except ValueError:
                    continue


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


class Parsed:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.session_id: Optional[str] = None
        self.cwd: Optional[str] = None
        self.version: Optional[str] = None
        self.calls: "OrderedDict[str, dict]" = OrderedDict()
        self.tools: Dict[str, dict] = {}            # tool_use_id -> event
        self.result: Optional[dict] = None
        self.compactions = 0
        self.first_ts: Optional[str] = None
        self.last_ts: Optional[str] = None
        self.denied_ids = set()
        self.prompt: Optional[str] = None             # the first thing the person asked in this session

    def call(self, mid: str, agent: str, model: Optional[str], ts: Optional[str]) -> dict:
        c = self.calls.get(mid)
        if c is None:
            c = {"id": mid, "agent": agent, "model": model, "tools": [], "tool_ids": [],
                 "in": 0, "cr": 0, "cc": 0, "out": 0, "ts": ts}
            self.calls[mid] = c
        if model and not c["model"]:
            c["model"] = model
        return c

    @staticmethod
    def usage(c: dict, u: Optional[dict]) -> None:
        u = u or {}
        for key, field in (("in", "input_tokens"), ("cr", "cache_read_input_tokens"),
                           ("cc", "cache_creation_input_tokens"), ("out", "output_tokens")):
            c[key] = max(c[key], int(u.get(field) or 0))

    def assistant(self, msg: dict, agent: str, ts: Optional[str]) -> None:
        mid = msg.get("id") or f"anon-{len(self.calls)}"
        c = self.call(mid, agent, msg.get("model"), ts)
        self.usage(c, msg.get("usage"))
        for b in msg.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                bid = b.get("id") or f"{mid}-{len(c['tool_ids'])}"
                if bid not in c["tool_ids"]:
                    c["tool_ids"].append(bid)
                    c["tools"].append(b.get("name") or "?")
                    self.tools[bid] = {"tool_use_id": bid, "tool": b.get("name") or "?",
                                       "input": b.get("input") or {}, "agent": agent, "ts": ts,
                                       "outcome": "ok", "result": "", "call": mid}
        if ts:
            self.first_ts = self.first_ts or ts
            self.last_ts = ts

    def user(self, row_or_msg: dict, msg: dict) -> None:
        decision = row_or_msg.get("permissionDecision") or {}
        for b in (msg.get("content") or []) if isinstance(msg.get("content"), list) else []:
            if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                continue
            ev = self.tools.get(b.get("tool_use_id"))
            if ev is None:
                continue
            text = _text(b.get("content"))
            tur = row_or_msg.get("toolUseResult")
            if isinstance(tur, dict):
                extra = (tur.get("stdout") or "") + "\n" + (tur.get("stderr") or "")
                if extra.strip():
                    text = text + "\n" + extra
            ev["result"] = text
            ev["out_bytes"] = len(text.encode("utf-8", "ignore"))
            if decision.get("decision") == "accept" and decision.get("source") not in (None, "config"):
                ev["outcome"] = "approved_by_user"
            if b.get("is_error"):
                denied = decision.get("decision") not in (None, "accept") or bool(DENY_TEXT.search(text[:400]))
                ev["outcome"] = "denied" if denied else "error"


def parse(path: Path) -> Parsed:
    """Auto-detects stream-json vs transcript; includes subagent transcripts when present."""
    p = Parsed(path)
    files = [path]
    sub = path.with_suffix("") / "subagents"
    if sub.is_dir():
        files += sorted(sub.glob("*.jsonl"))
    for f in files:
        default_agent = "main" if f == path else "sub:" + f.stem
        open_msg: Dict[str, str] = {}
        for row in iter_json(f):
            t = row.get("type")
            p.session_id = p.session_id or row.get("sessionId") or row.get("session_id")
            if f == path and row.get("cwd"):
                p.cwd = row["cwd"]          # last cwd wins: a session can move to another folder
            p.version = p.version or row.get("version") or row.get("claude_code_version")
            agent = row.get("parent_tool_use_id") or default_agent
            if default_agent == "main" and row.get("isSidechain"):
                agent = "sidechain"
            if t == "assistant":
                p.assistant(row.get("message") or {}, agent, row.get("timestamp"))
            elif t == "user":
                msg = row.get("message") or {}
                if f == path and p.prompt is None and not row.get("isMeta"):
                    content = msg.get("content")
                    if isinstance(content, str) or (isinstance(content, list) and not any(
                            isinstance(b, dict) and b.get("type") == "tool_result" for b in content)):
                        p.prompt = _text(content).strip()[:2000] or None
                p.user(row, msg)
            elif t == "stream_event":
                e = row.get("event") or {}
                if e.get("type") == "message_start":
                    m = e.get("message") or {}
                    if m.get("id"):
                        open_msg[agent] = m["id"]
                        p.usage(p.call(m["id"], agent, m.get("model"), None), m.get("usage"))
                elif e.get("type") == "message_delta":
                    mid = row.get("api_message_id") or open_msg.get(agent)
                    if mid:
                        p.usage(p.call(mid, agent, None, None), e.get("usage"))
            elif t == "result":
                p.result = row
                for d in row.get("permission_denials") or []:
                    p.denied_ids.add(d.get("tool_use_id"))
            elif t == "summary" or (t == "system" and "compact" in str(row.get("subtype", ""))):
                p.compactions += 1
    for tid in p.denied_ids:
        if tid in p.tools:
            p.tools[tid]["outcome"] = "denied"
    return p


def real_calls(p: Parsed) -> List[dict]:
    return [c for c in p.calls.values()
            if c["model"] != "<synthetic>" and (c["in"] + c["cr"] + c["cc"] + c["out"]) > 0]


def summarize(p: Parsed) -> Dict[str, object]:
    calls = real_calls(p)
    main = [c for c in calls if c["agent"] == "main"]
    tool_turns = [c for c in calls if c["tools"]]
    read_turns = [c for c in calls if c["tools"] and all(category(t) in ("read", "search") for t in c["tools"])]
    ctx = sum(c["in"] + c["cr"] + c["cc"] for c in calls)
    first = calls[0] if calls else None
    breaks = 0
    seqs = defaultdict(list)
    for c in calls:
        seqs[c["agent"]].append(c)
    for seq in seqs.values():
        for a, b in zip(seq, seq[1:]):
            prev = a["in"] + a["cr"] + a["cc"]
            if prev >= CACHE_BREAK_MIN and b["cr"] < CACHE_BREAK_RATIO * prev:
                breaks += 1
    outcomes = Counter(e["outcome"] for e in p.tools.values())
    return {
        "api_calls": len(calls), "api_calls_sub": len(calls) - len(main),
        "tool_calls": len(p.tools), "tool_turns": len(tool_turns),
        "parallel_turns": sum(1 for c in tool_turns if len(c["tools"]) >= 2),
        "read_only_turns": len(read_turns), "single_read_turns": sum(1 for c in read_turns if len(c["tools"]) == 1),
        "ctx_tokens": ctx, "out_tokens": sum(c["out"] for c in calls),
        "cache_read": sum(c["cr"] for c in calls), "cache_write": sum(c["cc"] for c in calls),
        "first_ctx": (first["in"] + first["cr"] + first["cc"]) if first else 0,
        "cache_breaks": breaks, "compactions": p.compactions,
        "denied": outcomes.get("denied", 0), "approved": outcomes.get("approved_by_user", 0),
        "errors": outcomes.get("error", 0),
        "model": next((c["model"] for c in main if c["model"]), None),
        "started": p.first_ts, "ended": p.last_ts,
    }


def tool_events(p: Parsed) -> List[Dict[str, object]]:
    out = []
    for ev in p.tools.values():
        tool, inp, res = ev["tool"], ev["input"], ev.get("result") or ""
        cat = category(tool)
        row = {"tool_use_id": ev["tool_use_id"], "ts": ev["ts"], "tool": tool, "category": cat,
               "outcome": ev["outcome"], "out_bytes": ev.get("out_bytes", 0), "agent": ev["agent"],
               "cmd_prefix": None, "compound": 0, "url": None, "target": None, "error_sig": None,
               "file": None}
        if cat == "shell":
            cmd = str(inp.get("command", ""))
            pre = shellparse.prefixes(cmd)
            row["cmd_prefix"] = " | ".join(pre)[:200] or None
            row["compound"] = int(shellparse.is_compound(cmd))
        if cat in ("read", "edit"):
            row["file"] = str(inp.get("file_path") or inp.get("notebook_path") or "")[:300] or None
        if cat == "browser":
            url = inp.get("url") or (URL_RE.search(res).group(0) if URL_RE.search(res or "") else None)
            row["url"] = (url or "")[:300] or None
            tgt = inp.get("ref") or inp.get("selector") or inp.get("query") or inp.get("text") or inp.get("action")
            row["target"] = (browser_kind(tool, inp) + ":" + str(tgt or tool.split("__")[-1]))[:200]
        if ev["outcome"] == "error":
            row["error_sig"] = shellparse.error_signature(res) or f"{tool}: {res.strip()[:80]}"
        out.append(row)
    return out


def test_commands(p: Parsed) -> Counter:
    c: Counter = Counter()
    for ev in p.tools.values():
        if category(ev["tool"]) == "shell":
            cmd = shellparse.HEREDOC.sub(" ", str(ev["input"].get("command", "")))
            if shellparse.TEST_HINT.search(cmd) and ev["outcome"] == "ok":
                c[re.sub(r"\s+", " ", cmd).strip()[:160]] += 1
    return c
