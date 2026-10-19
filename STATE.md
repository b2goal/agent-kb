# STATE — agent-kb build progress

Updated: 2026-10-19 (session 2, stage 1 done on branch p1/stability). 31 unit tests passing on Windows. Design doc: "Thiết kế chi tiết: agent-kb" (Claude Docs).

## Done (v0.1.0, 14 unit tests passing)

- Core: config (`paths.py`), knowledge item + file format (`model.py`), project id from git remote (`project.py`)
- Store: files as source of truth, one write path with dedupe, precedence by rank, supersede, conflicts,
  change log, `rebuild_meta`; `write_filters` hook (empty) (`store.py`)
- Indexes: plug-in protocol + registry + config-declared classes; FTS5 index following the change log (`indexes/`)
- Query: incremental index update, parallel query with timeout, RRF fusion, scan fallback, `egress_filters` (`query.py`)
- Telemetry DB: sessions, tool_events, ingest cursor, trigger state, retention prune (`telemetry.py`)
- Transcript parser (Claude Code transcript + stream-json, subagents, partial messages), tool categories,
  browser observe/act, error signatures, test commands (`transcript.py`, `shellparse.py`)
- Claude Code adapter: hook handler -> spool, SessionEnd ingest, spool merge (denied / approved / failure),
  discovery, `setup` (idempotent, backup, keeps an existing status line), Windows-safe command (`adapters/claude_code.py`)
- Stats + status line incl. browser exploration metric (`stats.py`)
- Tune: triggers (manual = never blocked; automatic = min sessions + cooldown), proposals, outbox,
  background mode (deterministic draft), apply (allow-list + guidance items + managed CLAUDE.md block + baseline) (`tune.py`)
- CLI `kb` (setup, doctor, hook, statusline, ingest, stats, tune, outbox, search, get, add, confirm, retire,
  index, export, serve) and local HTTP API (`cli.py`, `server.py`)
- Skill v2 `skills/session-tuner/SKILL.md` using `kb`
- Phase 3 v0 browser knowledge (`browser.py`): URL patterns, pages + edges learned from browser events at
  ingest (observed rank, stale after repeated failures), Dijkstra route + direct-URL fallback, Mermaid map;
  `kb browser learn|map|page|path|flows`; CLAUDE.md block points to it when pages exist
- Phase 3 follow-ups done: flows (transition chains repeated in >= 3 sessions), pitfalls (same action failing
  >= 2 times on a page)
- Packaging: `pyproject.toml`, `pip install -e .` verified, entry point `kb`

## Verified

- End-to-end on 20 real cc-bench logs: setup -> hook -> ingest -> stats -> tune -> apply -> CLAUDE.md / settings
- Hook event names checked against code.claude.com/docs/en/hooks (PostToolUse, PostToolUseFailure,
  PermissionRequest, PermissionDenied, SessionEnd; common fields session_id, transcript_path, cwd, hook_event_name)

- Real hook payloads (headless Claude Code 2.1.302): PostToolUse carries session_id, tool_name, tool_input,
  tool_response, tool_use_id, transcript_path, cwd; SessionEnd triggers ingest of transcript_path -> telemetry

- Windows (session 2, user's laptop): `install.ps1` uses `uv tool install -e .` -> `kb.exe` in ~/.local/bin on PATH;
  `kb setup claude` writes plain `kb hook claude` / `kb statusline` into ~/.claude/settings.json (re-run is idempotent);
  live PostToolUse hooks from a Claude Code desktop session land in ~/.agent-kb/spool/claude/<session>.jsonl.
  Fixes: UTF-8 stdio in `kb` (cp1252 console crashed `kb stats`), tests close SQLite before temp cleanup.

## Stage 1 (stability), done 2026-10-19 on branch p1/stability

- P1-8 `schema.py`: WAL, busy timeout, `user_version` migrations for kb.db / telemetry.db / FTS; a DB newer
  than the code is refused (`SchemaTooNew`). Live kb.db migrated to v2 (backup in %TEMP%/agent-kb-backup-*).
- P1-4 `kinds.py`: kind registry; unknown kinds are read, indexed and reported by doctor; writing needs a registered kind.
- P1-1 every store write runs in `BEGIN IMMEDIATE` (test: 6 writers -> 1 active; 6 without the lock).
- P1-0 same-id writes follow source rank; a lower rank opens one conflict instead of overwriting.
- P1-2 `LocalStore.reconcile()` picks up hand edits / additions / deletions (mtime+size, then hash) before search/export.
- P1-3 SessionStart hook ingests transcripts whose SessionEnd never ran (5 s budget); `telemetry.exclude_dirs`
  skips transcript folders (bench runs excluded in the live config).
- doctor: config errors, schema versions, pending transcripts, unregistered kinds, conflicts, missing hook events.
- Gate experiment (branch bench/gate-experiment): phase 1 passed, oracle pack beat CLAUDE.md-only on 5/6 tasks,
  -38% model calls, -28% cost. Next: phase 2 (`kb pack` prototype, arm b vs a).

## Not yet verified (needs a real interactive Claude Code session on the user's machine)

- Status line stdin fields (`cwd` / `workspace.current_dir` assumed; falls back to ".") — needs a restart to see it
- SessionEnd ingest from a real Windows session (first one ends when this session closes)

## Next (in order)

1. (Installed 2026-10-18.) Run one week, check `kb doctor` + `kb stats` match Claude Code's own numbers.
2. Browser on real data: check URL patterns and observe/act classification against the user's actual
   browser tools; add page state (modal / role / login) to page keys only if SPAs need it.
3. Adapter Codex — BLOCKED on a real sample: public write-ups disagree (tool calls under response_item vs
   event_msg; newer rollouts may be .jsonl.zst). Need one file from ~/.codex/sessions on the user's machine,
   then write adapters/codex.py + `kb export agents-md`.
4. Backlog: cloud sync behind Store, dashboard/chat on `kb serve`, Confluence/Jira connectors,
   vector/graph/rerank indexes, safety filters.

## Resume checklist

- Code: D:\projects\agent-kb (git restored from agent-kb.bundle)
- Run tests: `python -m unittest discover -s tests -t .`
- Quota check used during the build: `./quota.sh` (one tiny Haiku call)
