"""Gate experiment analysis: per-run metrics from transcripts, medians per task x arm, the decision rule.

    python bench/analyze.py                 # phase 1: compare arm c to arm a
    python bench/analyze.py --other b       # phase 2: compare arm b to arm a
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH.parent))
from agent_kb import transcript as tr  # noqa: E402

OBSERVE = ("snapshot", "screenshot", "wait_for", "console", "network", "evaluate")


def metrics(run_dir: Path) -> dict:
    res = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    row = {"task": res["task"], "arm": res["arm"], "rep": res["rep"], "success": bool(res["grade"]["success"]),
           "num_turns": res.get("num_turns"), "cost_usd": res.get("cost_usd"), "seconds": res.get("seconds")}
    t = run_dir / "transcript.jsonl"
    if not t.exists():
        return dict(row, missing_transcript=True)
    p = tr.parse(t)
    s = tr.summarize(p)
    events = tr.tool_events(p)
    browser = [e for e in events if e["category"] == "browser"]
    observe = [e for e in browser if any(k in e["tool"] for k in OBSERVE)]
    failed_acts = [e for e in browser if e not in observe and e["outcome"] == "error"]
    violations = [e for e in events if e["category"] in ("shell", "read") and
                  any(k in str(e.get("cmd_prefix") or e.get("file") or "") for k in ("sqlite", "shopdemo.db"))]
    if (BENCH / "tasks").exists() and res["task"].startswith("B"):
        violations += [e for e in events if e["category"] == "edit"]
    row.update(api_calls_main=s["api_calls"] - s["api_calls_sub"], tool_calls=s["tool_calls"],
               ctx_tokens=s["ctx_tokens"], out_tokens=s["out_tokens"], errors=s["errors"], denied=s["denied"],
               browser_calls=len(browser), explore=len(observe) + len(failed_acts), violations=len(violations))
    return row


def median(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return statistics.median(vals) if vals else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--other", default="c", choices=["b", "c"])
    args = ap.parse_args()
    rows = [metrics(d) for d in sorted((BENCH / "runs").glob("[BC][0-9]-*")) if (d / "result.json").exists()]
    (BENCH / "runs" / "metrics.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    tasks = sorted({r["task"] for r in rows})
    print(f"{'task':5} {'arm':3} {'n':>2} {'ok':>4} {'turns':>6} {'calls':>6} {'explore':>8} {'ctx_k':>7} {'cost$':>7}")
    better, gains = 0, {}
    for t in tasks:
        med = {}
        for arm in ("a", args.other):
            rs = [r for r in rows if r["task"] == t and r["arm"] == arm]
            if not rs:
                continue
            ok = sum(r["success"] for r in rs) / len(rs)
            med[arm] = {"ok": ok, "turns": median(rs, "api_calls_main"), "explore": median(rs, "explore")}
            ctx = median(rs, "ctx_tokens")
            print(f"{t:5} {arm:3} {len(rs):>2} {ok:>4.0%} {str(median(rs, 'num_turns')):>6} "
                  f"{str(med[arm]['turns']):>6} {str(med[arm]['explore']):>8} "
                  f"{(ctx or 0) / 1000:>7.0f} {median(rs, 'cost_usd') or 0:>7.3f}")
        if len(med) < 2 or med["a"]["turns"] is None or med[args.other]["turns"] is None:
            continue
        a, o = med["a"], med[args.other]
        if t.startswith("B"):
            gain = (a["explore"] - o["explore"]) / a["explore"] if a["explore"] else 0
            wins = gain >= 0.20
        else:
            gain = a["turns"] - o["turns"]
            wins = gain >= 1
        wins = wins and o["ok"] >= a["ok"]
        gains[t] = gain
        better += wins
        print(f"      -> {args.other} vs a: {'better' if wins else 'not better'} (gain {gain:.2f})")
    print(f"\n{args.other} better than a on {better}/{len(gains)} tasks; gate needs >= 4/6 "
          f"-> {'PASS' if better >= 4 else 'FAIL'}")
    v = sum(r.get("violations", 0) for r in rows)
    if v:
        print(f"warning: {v} rule violations in browser tasks (DB access or code edits); see runs/metrics.json")


if __name__ == "__main__":
    main()
