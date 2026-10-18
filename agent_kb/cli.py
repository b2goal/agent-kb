"""kb — command line for agent-kb. Every command is deterministic (no model calls)."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__


def _read_stdin_json() -> dict:
    try:
        data = sys.stdin.read()
        return json.loads(data) if data.strip() else {}
    except (ValueError, OSError):
        return {}


def _project(args) -> str:
    from .project import project_id
    return args.project_id or project_id(args.dir)


def cmd_hook(args) -> int:
    from .adapters import claude_code
    if args.harness != "claude":
        return 0
    return claude_code.handle_hook(_read_stdin_json())


def cmd_statusline(args) -> int:
    from .stats import statusline
    try:
        print(statusline(_read_stdin_json()))
    except Exception:
        print("kb")
    return 0


def cmd_setup(args) -> int:
    from .adapters import claude_code
    from .paths import write_default_config
    cfg = write_default_config()
    res = claude_code.setup(scope=args.scope, project_dir=args.dir, statusline=not args.no_statusline,
                            force_statusline=args.force_statusline, dry_run=args.dry_run)
    print(json.dumps(dict(res, config=str(cfg)), indent=2, ensure_ascii=False))
    return 0


def cmd_doctor(args) -> int:
    from .adapters import claude_code
    from .indexes import enabled_indexes
    from .paths import home, load_config
    from .telemetry import Telemetry
    ok = True

    def line(label: str, good: bool, note: str = "", warn: bool = False) -> None:
        nonlocal ok
        ok &= good or warn
        tag = "OK" if good else ("WARN" if warn else "FAIL")
        print(f"[{tag}] {label}{' — ' + note if note else ''}")

    line("python >= 3.9", sys.version_info >= (3, 9), sys.version.split()[0])
    line("kb home", home().exists() or True, str(home()))
    line("git", bool(shutil.which("git")), "project ids use the git remote")
    cdir = claude_code.claude_dir()
    line("Claude Code dir", cdir.exists(), str(cdir))
    sp = claude_code.settings_file("user")
    hooked = sp.exists() and claude_code.HOOK_MARK in sp.read_text(encoding="utf-8")
    line("hooks installed (user settings)", hooked, "run: kb setup claude" if not hooked else str(sp))
    spool = list((home() / "spool" / "claude").glob("*.jsonl")) if (home() / "spool" / "claude").exists() else []
    line("hook events received", bool(spool), f"{len(spool)} spool file(s)" + ("" if spool else
         " — normal right after setup; use Claude Code once, then re-run"), warn=True)
    t = Telemetry()
    n = t.db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    line("telemetry", True, f"{n} session(s) ingested")
    from .store import LocalStore
    for ix in enabled_indexes(load_config()):
        ix.update(LocalStore())
        h = ix.health()
        line(f"index {ix.name}", bool(h.get("ok")), f"{h.get('docs')} docs")
    return 0 if ok else 1


def cmd_ingest(args) -> int:
    from .adapters import claude_code
    from .telemetry import Telemetry
    from .tune import refresh_flag
    res = claude_code.ingest_all(recent=args.recent, force=args.force,
                                 project_dir=args.dir if args.only_project else None)
    tele = Telemetry()
    from . import browser
    for p in tele.projects():
        refresh_flag(tele, p)
        if tele.db.execute("SELECT 1 FROM tool_events WHERE project=? AND category='browser' LIMIT 1", (p,)).fetchone():
            res.setdefault("browser", {})[p] = browser.learn(p, tele)
    print(json.dumps(res))
    return 0


def cmd_stats(args) -> int:
    from .stats import render, summary
    from .telemetry import Telemetry
    from .tune import load_baseline
    proj = None if args.all_projects else _project(args)
    s = summary(Telemetry(), proj, args.days)
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2, default=str))
    else:
        print(render(s, load_baseline(proj) if proj else None))
    return 0


def cmd_tune(args) -> int:
    from . import tune
    from .store import LocalStore
    from .telemetry import Telemetry
    proj = _project(args)
    tele = Telemetry()
    if args.apply:
        boxes = tune.list_outbox(proj)
        if not boxes:
            print("Không có đề xuất nào trong outbox cho project này. Chạy `kb tune` trước.")
            return 1
        target = Path(boxes[0]["path"]) if args.apply == "latest" else Path(args.apply)
        sel = [int(x) for x in args.select.split(",")] if args.select else None
        res = tune.apply(target, args.dir, sel, args.target, include_review=args.include_review)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    ev = tune.evaluate(tele, proj, manual=True)
    existing = tune.export_claude_md(LocalStore(), proj)
    props = tune.proposals(ev["summary"], existing)
    path = tune.write_outbox(proj, ev, props) if props and not args.dry_run else None
    if args.json:
        print(json.dumps({"evaluation": {k: v for k, v in ev.items() if k != "summary"},
                          "proposals": props, "outbox": str(path) if path else None,
                          "summary": ev["summary"]}, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"Project: {proj}")
    print(f"{len(ev['fired'])} điều kiện vượt ngưỡng" + (f" ({ev['reason']})" if ev['reason'] else ""))
    for f in ev["fired"]:
        print(f"  - {f['name']}: {f['value']} (ngưỡng {f['threshold']}) — {f['note']}")
    if not props:
        print("Không có đề xuất.")
        return 0
    print("\nĐề xuất:")
    for p in props:
        flag = " [cần duyệt riêng]" if p.get("needs_confirm") else (" [cần model/người viết]" if p.get("needs_model") else "")
        what = p.get("rule") or p.get("text") or p.get("signature") or p.get("file")
        print(f"  {p['n']}. {p['type']}: {what} (bằng chứng: {p['evidence']}){flag}")
    if path:
        print(f"\nĐã lưu: {path}\nÁp dụng: kb tune --apply latest [--select 1,2] [--target local|shared]")
    return 0


def cmd_outbox(args) -> int:
    from .store import LocalStore
    from .tune import list_outbox
    proj = None if args.all_projects else _project(args)
    for d in list_outbox(proj):
        print(f"{d['id']}  {len(d['proposals'])} đề xuất  {d['created'][:16]}")
    conf = LocalStore().conflicts()
    for c in conf:
        if proj and c["project"] != proj:
            continue
        print(f"xung đột #{c['id']}: {c['item_id']} vs {c['other_id']} ({c['subject_key']}) — "
              f"giải quyết: kb confirm <id>")
    return 0


def cmd_search(args) -> int:
    from .indexes import Query
    from .query import search
    from .store import LocalStore
    proj = None if args.all_projects else _project(args)
    q = Query(text=" ".join(args.text), project=proj, kinds=args.kind.split(",") if args.kind else None,
              statuses=["active"] if not args.history else ["active", "superseded", "stale", "proposed", "retired"],
              limit=args.limit)
    res = search(LocalStore(), q)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        for r in res:
            print(f"{r['id']}  [{r['kind']}/{r['status']}/r{r['rank']}]  {r['title'] or r['subject_key']}")
        if not res:
            print("Không tìm thấy.")
    return 0


def cmd_get(args) -> int:
    from .store import LocalStore
    item = LocalStore().get(args.id)
    if not item:
        print("Không có mục này.")
        return 1
    print(item.to_text())
    return 0


def cmd_add(args) -> int:
    from .model import Item
    from .store import LocalStore
    body = args.body if args.body is not None else sys.stdin.read()
    proj = "global" if args.is_global else _project(args)
    item = Item(kind=args.kind, project=proj, subject_key=args.subject, title=args.title or args.subject,
                body=body, rank=1, source={"name": "manual"}, supersedes=args.supersedes,
                tags=args.tag or [])
    print(json.dumps(LocalStore().put(item, actor="kb add"), ensure_ascii=False))
    return 0


def cmd_confirm(args) -> int:
    from .store import LocalStore
    print(json.dumps(LocalStore().confirm(args.id), ensure_ascii=False))
    return 0


def cmd_retire(args) -> int:
    from .store import LocalStore
    LocalStore().set_status(args.id, "retired")
    print("retired", args.id)
    return 0


def cmd_index(args) -> int:
    from .indexes import enabled_indexes, load_index
    from .paths import load_config
    from .store import LocalStore
    store = LocalStore()
    if args.action == "rebuild":
        store.rebuild_meta()
        targets = [load_index(args.name)] if args.name else enabled_indexes(load_config())
        for ix in targets:
            print(ix.name, "rebuilt:", ix.build(store), "items")
    else:
        for ix in enabled_indexes(load_config()):
            print(ix.name, ix.health())
    return 0


def cmd_export(args) -> int:
    from .store import LocalStore
    from .tune import export_claude_md, write_managed_block
    block = export_claude_md(LocalStore(), _project(args))
    if args.write:
        write_managed_block(Path(args.dir) / "CLAUDE.md", block)
        print("written", Path(args.dir) / "CLAUDE.md")
    else:
        print(block)
    return 0


def cmd_browser(args) -> int:
    from . import browser
    proj = _project(args)
    if args.action == "learn":
        print(json.dumps(browser.learn(proj), ensure_ascii=False))
    elif args.action == "map":
        print(browser.mermaid(proj))
    elif args.action == "page":
        for p in browser.find_pages(proj, " ".join(args.query))[:5]:
            print(p.to_text())
    elif args.action == "path":
        print(json.dumps(browser.path(proj, " ".join(args.query), args.from_url), ensure_ascii=False, indent=2))
    return 0


def cmd_serve(args) -> int:
    from .server import serve
    serve(args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="kb", description="agent-kb: knowledge + telemetry for coding agents")
    ap.add_argument("--version", action="version", version=f"agent-kb {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def proj_opts(p, all_flag: bool = False):
        p.add_argument("--dir", default=os.getcwd(), help="project folder (default: current)")
        p.add_argument("--project-id", default=None, help="explicit project id instead of --dir")
        if all_flag:
            p.add_argument("--all-projects", action="store_true")

    p = sub.add_parser("hook", help="called by harness hooks (reads JSON on stdin)")
    p.add_argument("harness", choices=["claude"])
    p.set_defaults(fn=cmd_hook)
    p = sub.add_parser("statusline", help="one-line status for the harness status line")
    p.set_defaults(fn=cmd_statusline)
    p = sub.add_parser("setup", help="wire hooks + status line into a harness")
    p.add_argument("harness", choices=["claude"])
    p.add_argument("--scope", choices=["user", "project", "local"], default="user")
    p.add_argument("--dir", default=os.getcwd())
    p.add_argument("--no-statusline", action="store_true")
    p.add_argument("--force-statusline", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_setup)
    p = sub.add_parser("doctor", help="check installation")
    p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("ingest", help="read harness logs into telemetry")
    p.add_argument("--recent", type=int, default=None)
    p.add_argument("--force", action="store_true")
    p.add_argument("--only-project", action="store_true")
    p.add_argument("--dir", default=os.getcwd())
    p.set_defaults(fn=cmd_ingest)
    p = sub.add_parser("stats", help="statistics for a project")
    proj_opts(p, True)
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_stats)
    p = sub.add_parser("tune", help="evaluate triggers and write proposals; --apply after review")
    proj_opts(p)
    p.add_argument("--apply", nargs="?", const="latest", default=None)
    p.add_argument("--select", default=None, help="comma list of proposal numbers")
    p.add_argument("--target", choices=["local", "shared"], default="local")
    p.add_argument("--include-review", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_tune)
    p = sub.add_parser("outbox", help="pending proposals and conflicts")
    proj_opts(p, True)
    p.set_defaults(fn=cmd_outbox)
    p = sub.add_parser("search", help="search knowledge")
    proj_opts(p, True)
    p.add_argument("text", nargs="+")
    p.add_argument("--kind", default=None)
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--history", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_search)
    p = sub.add_parser("get", help="print one item")
    p.add_argument("id")
    p.set_defaults(fn=cmd_get)
    p = sub.add_parser("add", help="add knowledge (rank 1); body from --body or stdin")
    proj_opts(p)
    p.add_argument("kind")
    p.add_argument("subject")
    p.add_argument("--title", default=None)
    p.add_argument("--body", default=None)
    p.add_argument("--global", dest="is_global", action="store_true")
    p.add_argument("--supersedes", default=None)
    p.add_argument("--tag", action="append")
    p.set_defaults(fn=cmd_add)
    p = sub.add_parser("confirm", help="confirm an item (rank 1, supersedes peers, resolves conflicts)")
    p.add_argument("id")
    p.set_defaults(fn=cmd_confirm)
    p = sub.add_parser("retire", help="retire an item")
    p.add_argument("id")
    p.set_defaults(fn=cmd_retire)
    p = sub.add_parser("index", help="index maintenance")
    p.add_argument("action", choices=["rebuild", "health"])
    p.add_argument("name", nargs="?")
    p.set_defaults(fn=cmd_index)
    p = sub.add_parser("export", help="render guidance for a harness")
    p.add_argument("format", choices=["claude-md"])
    proj_opts(p)
    p.add_argument("--write", action="store_true", help="write the managed block into CLAUDE.md")
    p.set_defaults(fn=cmd_export)
    p = sub.add_parser("browser", help="page graph: learn | map | page <q> | path <q> [--from URL]")
    proj_opts(p)
    p.add_argument("action", choices=["learn", "map", "page", "path"])
    p.add_argument("query", nargs="*")
    p.add_argument("--from", dest="from_url", default=None)
    p.set_defaults(fn=cmd_browser)
    p = sub.add_parser("serve", help="local HTTP API on 127.0.0.1 (for a future dashboard)")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(fn=cmd_serve)
    return ap


def main(argv: Optional[List[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    sys.exit(args.fn(args) or 0)


if __name__ == "__main__":
    main()
