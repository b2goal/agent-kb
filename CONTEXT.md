# CONTEXT — agent-kb handoff

Handoff from a Claude cloud session (2026-10-18) so work can continue in Claude Code on this machine.
Read this first, then STATE.md (build status) and README.md (usage).

## 1. Who / how to work

- User: software engineer. Tasks are mostly complex coding + browser control/automation. Windows laptop
  (projects in `D:\projects`). Uses Claude Code; also has Codex, Antigravity, Cline, Gemini dirs in home.
- Language: Vietnamese in chat; code, comments and file names in English.
- Working rules the user set:
  - Close gaps yourself; only ask when a real decision is needed. Don't tell the user to compute or check
    things you can do.
  - Don't over-scope ("ôm đồm"): keep v1 small, push extras to backlog.
  - Measure before building; decisions from data.
  - Respect the 5-hour quota: stop around 90%, write state, resume after reset.
  - Safety rules (redaction etc.) are out of scope for now — keep empty hook points only.

## 2. What we learned (cc-bench, Sonnet, ~156 runs, small Python fixture)

| Finding | Evidence |
|---|---|
| Extra turns come mostly from failures, not lack of planning | 48/48 denied commands were compound (`cd … &&`, `;`, `$(...)`); test convention mistakes (SKU format) caused fix loops |
| CLAUDE.md with project conventions + no permission blocks is the biggest turn saver | turns ~7 → ~4 on 3 of 4 tasks |
| Cutting unused tools is the biggest token saver | input tokens −35…40%, every turn |
| Concrete batching rules beat "plan as a graph" | rule "all reads in one response, all edits + test in one response" → 78% parallel turns, minimum turns; graph vs no graph: no measurable difference |
| Skills are not reliably self-invoked | 0/12 runs invoked a skill holding the same instructions → put workflow rules in always-loaded files |
| Read/Edit batching vs Bash scripts | Bash-script edits cheapest (~−40% cost, sandbox only); Read/Edit batching keeps reviewable diffs, ~same cost as baseline+env |
| Expected gain for normal coding | ~30% fewer turns, ~15–25% less quota |

Benchmark harness: `cc-bench` (separate zip delivered in chat) — fixture `shopkit`, 4 tasks with hidden tests,
variants A–K, `run_bench.py`, `analyze.py`.

## 3. Design (full doc: Claude Docs "Thiết kế chi tiết: agent-kb")

Data model v3 (2026-10-21, agreed, not implemented): `docs/design/data-model-v3.md` — source contract,
typed fields (`key`/`text`/`time`/`ref`), shared index registry, one graph for all kinds, `link` records
with polarity, `rejected` status, evidence + conditions + `kb why`, site profiles for the page map.
Where it disagrees with the points below, v3 wins.

- **Principle:** knowledge belongs to the user, harnesses are thin adapters. Split by layer:
  collectors per harness → one write gate → local store → rebuildable indexes → one query API → clients.
- **Store** `~/.agent-kb/` (env `AGENT_KB_HOME`): knowledge = Markdown files (source of truth, history);
  `kb.db` metadata/change log/conflicts (rebuildable); `telemetry.db`; `index/`; `outbox/`; `baselines/`; `spool/`.
- **Project id** = normalized git remote (`github.com/org/app`), not the folder path.
- **Items**: kind (convention, command, guidance, page, edge, flow, pitfall, doc, note), subject_key, status
  (proposed → active → superseded/stale/retired), supersedes, valid_from/to, source, rank, evidence, hash.
- **Source rank** (lower = more trusted): manual 1, observed 2, confluence 3, jira 4, model 5. Same/higher rank
  and newer supersedes; lower rank that disagrees → conflict for review, never silent overwrite.
- **Indexes** are plug-ins (build/update/query/health), FTS5 now; vector/graph/reranker later; RRF fusion;
  failing index skipped; FTS/scan always fallback; shadow-evaluate before switching.
- **Telemetry → triggers → proposals → outbox → apply after approval → baseline → re-measure.**
  Default mode: notify only (0 tokens). Never inject into a running session.
- **Browser knowledge**: page graph (URL patterns), edges, flows (seen ≥3 sessions), pitfalls (same action
  failing ≥2 times); `kb browser path` gives known routes so the model explores less. Lives in the same
  store; CLAUDE.md only points to `kb`.
- **Tech**: Python ≥3.9 stdlib only, SQLite; install via `uv tool install` / `pip -e`; `kb setup claude`.

## 4. Status (v0.1.0, 4 commits, 17 tests pass)

Done: core store, FTS index, query, telemetry, Claude Code adapter (hooks → spool, SessionEnd ingest,
transcript parser), stats + status line, tune/outbox/apply/baseline, browser graph + flows + pitfalls,
CLI `kb`, local HTTP API `kb serve`, skill `skills/session-tuner/SKILL.md`, Windows `install.ps1`.
Verified: end-to-end on real logs; real hook payload fields (headless Claude Code 2.1.302).

Not yet verified on this machine: Windows install, hook command quoting under Claude Code on Windows,
status line stdin fields, real browser tool names/URLs.

## 5. Next steps (in order)

1. Install: `cd D:\projects\agent-kb` → `powershell -ExecutionPolicy Bypass -File .\install.ps1`.
   Fix whatever breaks on Windows (paths, hook command, PATH for `kb`). Restart Claude Code.
2. Use normally ~1 week. Check `py -m agent_kb doctor`, `stats` numbers vs Claude Code's own usage.
3. `kb tune` → review → `kb tune --apply latest --select …` (or `/session-tuner`).
4. Browser: check URL patterns and observe/act classification against real browser tools; add page state
   (modal/role/login) only if SPAs need it.
5. Codex adapter — blocked until a real sample from `~/.codex/sessions` is inspected (format reports
   conflict; may be `.jsonl.zst`). Then `adapters/codex.py` + `kb export agents-md`.

## 6. Backlog (explicitly deferred)

Cloud sync (behind `Store`), dashboard + chat box on `kb serve` (model provider pluggable, OpenAI-compatible;
DeepSeek was only a placeholder), Confluence/Jira connectors, vector/graph/rerank indexes, safety filters
(`write_filters`, `egress_filters`), converting verified browser flows into Playwright tests, per-harness
benchmark runner (to decide whether to switch harness, e.g. Antigravity).

## 7. Open questions

- Trigger mode: notify (default, 0 tokens) or background drafts?
- Page node granularity: URL pattern only, or + state?
- May the model write knowledge directly (rank 5, proposed) or read-only?
- Record browser form input values or skip from the start? (recommended: skip)
- Search scope default: per project or cross-project?
