# STATE — agent-kb build progress

Updated: 2026-10-18 (session 1). Design doc: "Thiết kế chi tiết: agent-kb" (Claude Docs).

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
- Packaging: `pyproject.toml`, `pip install -e .` verified, entry point `kb`

## Verified

- End-to-end on 20 real cc-bench logs: setup -> hook -> ingest -> stats -> tune -> apply -> CLAUDE.md / settings
- Hook event names checked against code.claude.com/docs/en/hooks (PostToolUse, PostToolUseFailure,
  PermissionRequest, PermissionDenied, SessionEnd; common fields session_id, transcript_path, cwd, hook_event_name)

- Real hook payloads (headless Claude Code 2.1.302): PostToolUse carries session_id, tool_name, tool_input,
  tool_response, tool_use_id, transcript_path, cwd; SessionEnd triggers ingest of transcript_path -> telemetry

## Not yet verified (needs a real interactive Claude Code session on the user's machine)

- Status line stdin fields (`cwd` / `workspace.current_dir` assumed; falls back to ".")
- Windows paths and `kb` on PATH via uv

## Next (in order)

1. Install on the user's machine, run one week, check `kb doctor` + `kb stats` match Claude Code's own numbers.
2. Phase 3 — browser knowledge (only if `kb stats` shows browser output share / exploration high):
   page/edge/flow/pitfall items from browser events, `kb path`, `kb page`, `kb flow`.
3. Adapter Codex (verify ~/.codex log format first) + `kb export agents-md`.
4. Backlog: cloud sync behind Store, dashboard/chat on `kb serve`, Confluence/Jira connectors,
   vector/graph/rerank indexes, safety filters.

## Resume checklist

- Code: /home/claude/agent-kb (also delivered as agent-kb.zip)
- Run tests: `python -m unittest discover -s tests -t .`
- Quota check used during the build: `./quota.sh` (one tiny Haiku call)
