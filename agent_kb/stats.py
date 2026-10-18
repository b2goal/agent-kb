"""Deterministic statistics over telemetry (0 tokens) + the status line."""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from . import shellparse
from .paths import ensure_home
from .project import project_id, slug
from .telemetry import Telemetry


def _med(xs: List[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def summary(tele: Telemetry, project: Optional[str] = None, days: Optional[int] = 7,
            since: Optional[str] = None) -> Dict[str, object]:
    sessions = tele.sessions(project, days, since)
    sids = {s["session_id"] for s in sessions}
    events = [e for e in tele.events(project, None) if e["session_id"] in sids]
    s_sum = lambda k: sum((r[k] or 0) for r in sessions)            # noqa: E731
    ctx = s_sum("ctx_tokens")

    denied = [e for e in events if e["outcome"] == "denied"]
    approved = [e for e in events if e["outcome"] == "approved_by_user"]
    cand: Dict[str, Dict[str, int]] = defaultdict(lambda: {"denied": 0, "approved": 0})
    for e in denied + approved:
        for pre in (e["cmd_prefix"] or "").split(" | "):
            if pre:
                cand[pre]["denied" if e["outcome"] == "denied" else "approved"] += 1
    allow = sorted(({"prefix": k, "count": v["denied"] + v["approved"], **v, "risk": shellparse.risk(k),
                     "rule": f"Bash({k} *)"} for k, v in cand.items()), key=lambda a: -a["count"])

    per_tool: Dict[str, Dict[str, int]] = defaultdict(lambda: {"calls": 0, "errors": 0})
    for e in events:
        per_tool[e["tool"]]["calls"] += 1
        per_tool[e["tool"]]["errors"] += e["outcome"] == "error"
    sig_count, sig_sessions = Counter(), defaultdict(set)
    for e in events:
        if e["error_sig"]:
            sig_count[e["error_sig"]] += 1
            sig_sessions[e["error_sig"]].add(e["session_id"])
    reread = Counter()
    per_session_reads: Dict[tuple, int] = Counter((e["session_id"], e["file"]) for e in events if e["file"])
    for (sid, f), n in per_session_reads.items():
        if n >= 3:
            reread[f] += 1
    tests = Counter()
    for s in sessions:
        try:
            tests.update(json.loads(s["test_commands"] or "{}"))
        except ValueError:
            pass
    total_bytes = sum((e["out_bytes"] or 0) for e in events) or 0
    browser = [e for e in events if e["category"] == "browser"]
    observe = [e for e in browser if (e["target"] or "").startswith("observe:")]
    act = [e for e in browser if (e["target"] or "").startswith("act:")]
    per_url = defaultdict(lambda: [0, 0])
    for e in browser:
        if e["url"]:
            per_url[e["url"]][0 if (e["target"] or "").startswith("observe:") else 1] += 1
    return {
        "project": project, "days": days, "sessions": len(sessions),
        "api_calls_median": _med([s["api_calls"] for s in sessions]),
        "ctx_tokens_median": _med([s["ctx_tokens"] for s in sessions]),
        "first_ctx_median": _med([s["first_ctx"] for s in sessions]),
        "cache_hit": round(s_sum("cache_read") / ctx, 3) if ctx else None,
        "cache_breaks": s_sum("cache_breaks"),
        "parallel_ratio": round(s_sum("parallel_turns") / s_sum("tool_turns"), 3) if s_sum("tool_turns") else None,
        "single_read_ratio": (round(s_sum("single_read_turns") / s_sum("read_only_turns"), 3)
                              if s_sum("read_only_turns") else None),
        "tool_calls": len(events),
        "errors": sum(1 for e in events if e["outcome"] == "error"),
        "denied": len(denied), "denied_compound": sum(1 for e in denied if e["compound"]),
        "approved": len(approved),
        "allow_candidates": allow[:25],
        "tool_errors": sorted(({"tool": t, **v, "rate": round(v["errors"] / v["calls"], 3)}
                               for t, v in per_tool.items() if v["calls"]), key=lambda r: -r["errors"])[:15],
        "repeated_errors": [{"signature": k, "count": v, "sessions": len(sig_sessions[k])}
                            for k, v in sig_count.most_common(15)],
        "test_commands": tests.most_common(5),
        "reread_files": reread.most_common(10),
        "by_category": Counter(e["category"] for e in events).most_common(),
        "browser": {"calls": len(browser),
                    "failed": sum(1 for e in browser if e["outcome"] in ("error", "denied")),
                    "output_share": round(sum((e["out_bytes"] or 0) for e in browser) / total_bytes, 3)
                    if total_bytes else None,
                    "top_urls": Counter(e["url"] for e in browser if e["url"]).most_common(8),
                    "observe": len(observe), "act": len(act),
                    "observe_per_act": round(len(observe) / len(act), 2) if act else None,
                    "most_explored": sorted(([u, o, a] for u, (o, a) in per_url.items()),
                                            key=lambda r: -r[1])[:5]},
    }


def _fmt(x) -> str:
    if x is None:
        return "-"
    if isinstance(x, float) and x <= 1.0 and x >= 0:
        return f"{x * 100:.0f}%"
    x = float(x)
    if x >= 1e6:
        return f"{x / 1e6:.2f}M"
    if x >= 1e3:
        return f"{x / 1e3:.1f}k"
    return f"{x:.0f}"


def render(s: Dict[str, object], baseline: Optional[Dict[str, object]] = None) -> str:
    rows = [("Session", "sessions"), ("API calls / session (trung vị)", "api_calls_median"),
            ("Token đọc vào / session (trung vị)", "ctx_tokens_median"),
            ("Context lượt đầu ≈ phần cố định", "first_ctx_median"), ("Cache hit", "cache_hit"),
            ("Mất cache", "cache_breaks"), ("% lượt song song", "parallel_ratio"),
            ("% lượt chỉ đọc 1 file", "single_read_ratio"), ("Tool call", "tool_calls"), ("Lỗi", "errors"),
            ("Bị chặn", "denied"), ("…là lệnh ghép", "denied_compound"), ("Duyệt tay", "approved")]
    head = "| Chỉ số | Hiện tại |" + (" Baseline |" if baseline else "")
    out = [f"# kb stats — {s['project'] or 'mọi project'} ({s['days'] or 'toàn bộ'} ngày)", "", head,
           "|---|---|" + ("---|" if baseline else "")]
    for label, key in rows:
        line = f"| {label} | {_fmt(s.get(key))} |"
        if baseline:
            line += f" {_fmt(baseline.get(key))} |"
        out.append(line)
    if s["allow_candidates"]:
        out += ["", "## Lệnh bị chặn / phải duyệt", "", "| Rule | Bị chặn | Duyệt tay | Rủi ro |", "|---|---|---|---|"]
        out += [f"| `{a['rule']}` | {a['denied']} | {a['approved']} | {a['risk']} |" for a in s["allow_candidates"][:12]]
    if s["repeated_errors"]:
        out += ["", "## Lỗi lặp lại", ""]
        out += [f"- {e['count']}× ({e['sessions']} session) `{e['signature']}`" for e in s["repeated_errors"][:10]]
    bad = [t for t in s["tool_errors"] if t["errors"]]
    if bad:
        out += ["", "## Tỉ lệ lỗi theo tool", ""] + [f"- {t['tool']}: {t['errors']}/{t['calls']} ({_fmt(t['rate'])})"
                                                   for t in bad[:8]]
    if s["test_commands"]:
        out += ["", "## Lệnh test", ""] + [f"- `{c}` ({n} lần)" for c, n in s["test_commands"]]
    b = s["browser"]
    if b["calls"]:
        out += ["", "## Browser", "", f"- {b['calls']} thao tác, {b['failed']} thất bại, "
                f"chiếm {_fmt(b['output_share'])} output của tool",
                f"- Mò mẫm: {b['observe']} lần quan sát / {b['act']} lần thao tác "
                f"({b['observe_per_act'] if b['observe_per_act'] is not None else '-'} quan sát mỗi thao tác)"]
        out += [f"  - {u}: {o} quan sát, {a} thao tác" for u, o, a in b["most_explored"]]
    out += ["", "Loại tool: " + ", ".join(f"{k} {v}" for k, v in s["by_category"])]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------- status line
def flag_path(project: str) -> Path:
    d = ensure_home() / "outbox" / "flags"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{slug(project)}.json"


def statusline(payload: Dict[str, object]) -> str:
    """One line, fast: today's counts for this project + a warning when tuning is due."""
    ws = payload.get("workspace") or {}
    cwd = str(payload.get("cwd") or (ws.get("current_dir") if isinstance(ws, dict) else "") or ".")
    proj = project_id(cwd)
    tele = Telemetry()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = tele.db.execute("SELECT outcome, COUNT(*) n FROM tool_events WHERE project=? AND ts >= ? "
                           "GROUP BY outcome", (proj, today)).fetchall()
    counts = {r["outcome"]: r["n"] for r in rows}
    sid = str(payload.get("session_id") or "")
    if sid:   # live session not yet ingested: count from the spool
        from .adapters.claude_code import spool_events
        for ev in spool_events(sid):
            key = {"PostToolUse": "ok", "PostToolUseFailure": "error", "PermissionDenied": "denied"}.get(
                str(ev.get("event")))
            if key:
                counts[key] = counts.get(key, 0) + 1
    total = sum(counts.values())
    errs, den = counts.get("error", 0), counts.get("denied", 0)
    text = f"kb {total} tool · lỗi {errs / total:.0%} · chặn {den}" if total else "kb · chưa có dữ liệu hôm nay"
    fp = flag_path(proj)
    if fp.exists():
        try:
            flag = json.loads(fp.read_text(encoding="utf-8"))
            if flag.get("fired"):
                text += f" · ⚠ {len(flag['fired'])} điều kiện, chạy: kb tune"
        except ValueError:
            pass
    return text
