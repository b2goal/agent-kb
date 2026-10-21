# Data model v3 — one flow, typed data, shared index registry

Status: agreed design, not implemented. Date: 2026-10-21.
Extends the Claude Docs design "Thiết kế chi tiết: agent-kb" (sections *Mô hình khái niệm v2*,
*Hợp đồng kind*, *Index và truy vấn*, *Tri thức browser / Sơ đồ trang v2*). Where the two disagree,
this file wins; § 10 lists what it supersedes.

Origin: a real run on SmartLender CLOS (`localhost:8080/clos`, an OFA/Struts app) showed that the
v0.1 page graph — keyed by URL path only — merges different screens, treats `Login.do` as Home,
labels every action `browser_batch`, and suggests opening URLs directly, which CLOS answers with
Access Denied. Fixing that for one site is easy; the goal here is a model where any new source or
kind of data plugs in without touching the core.

## 1. Decisions

| # | Decision |
|---|----------|
| 1 | One flow for everything: source → event → processor → write gate → data → builds → delivery. Sources, processors and builds are plug-ins in exactly one slot each. |
| 2 | Every source declares a **source contract** (7 questions, § 3). |
| 3 | The core stores only **data** (records of a kind). Relations are data too — no separate core concept for links. |
| 4 | Every field of a kind has a **field type**: `key`, `text`, `time`, `ref`. Indexes read field types, never kind names. |
| 5 | Indexes form one **registry** shared by all kinds. A kind declares which registry indexes it uses and maps its fields to them. |
| 6 | One **graph index** for all kinds. The page map is one application of it (`page` records + `reaches` relations), not its own database. |
| 7 | Relations: intrinsic positive relations are `ref` fields on the record; assertions about relations (agent, person, feedback, positive or **negative**) are records of kind `link` with `polarity`. |
| 8 | `status` (lifecycle, core) and `polarity` (content, `link` kind only) are separate. `status` gains the value `rejected`. |
| 9 | Every record can carry `evidence` (pointers to source events) and `conditions` (where it holds). `kb why <key>` traces a record back to its events. |
| 10 | Browser specifics live in data (`site_profile` records) and in the `page` processor, never in the core. |

## 2. The flow and its plug points

```
Source ─▶ Event ─▶ Processor ─▶ Write gate ─▶ Data ─▶ Builds (indexes, exports) ─▶ query() / delivery
  ▲                                                                                      │
  └──────────── use produces new events and re-verifies data (freshness loop) ────────────┘
```

- Branches only at the write gate (accept / conflict / proposal) and at delivery (agent or person,
  by scope and budget) — unchanged from v2.
- Plug points: **source** (adapter or connector), **processor** (pure rules: events → proposals),
  **build** (index, export file, widget).
- The core never branches on a kind name, a relation type or a field name. Sign of breakage: an
  `if kind == …` in store, query or events.

## 3. Source contract

A new source answers these before any code is written.

| # | Question | Declares |
|---|----------|----------|
| 1 | Where from? | Location (path, API URL, hook), format, default scope (project / global / personal) |
| 2 | How fetched? | Push (hook) or pull (poll, API); incremental cursor; auth; frequency; truncated / compressed input |
| 3 | How converted? | Mapping to the common event (§ 4 axes + `signals`); which kinds it produces, through which processor |
| 4 | Which indexes? | Not declared here — follows from the kinds it produces (§ 6). Only a new build (e.g. a time index for logs) is declared |
| 5 | Health? | What `kb doctor` checks (last event, read errors); one real sample file as a test fixture |
| 6 | Retention and filtering? | How long its events are kept; fields dropped before the write gate (passwords, form values, secrets) |
| 7 | Relations produced? | Relation types it emits, between which kinds, at which rank |

Examples:

| | Claude Code (exists) | Playwright MCP | Jira | Tomcat access log (CLOS) |
|---|---|---|---|---|
| 1 | `~/.claude/projects/*/*.jsonl` + hooks | Transcript of the harness calling it | REST API | `logs/localhost_access_log.*.txt` |
| 2 | Push (spool) + pull at SessionStart; cursor = size + mtime | Same as the harness; only a tool-name map is new | Poll `updated >= cursor`; API token | Pull, continue from offset |
| 3 | Tool call → event; `signals`: url, tab title | `browser_*` → observe / act; `signals`: title, url | Issue → `doc` / `decision`, rank 4, anchor = issue key | Request → event; `signals`: `X.do?event=`, session |
| 5 | Last event, transcripts waiting | New `browser_*` events | Last sync, API errors | Log size grows |
| 6 | 90 days; drop form values | Same | Follows the user's read permission | Drop parameters with personal data |
| 7 | `page reaches page` (observed) | Same | `issue changed page/file` (rank 4) | `page reaches page` (observed) |

## 4. Data

Two kinds of stored truth, as in v2: **events** (append-only) and **records** (claims about a
subject, never edited in place — a new version supersedes). Everything else is a build.

Common fields on every record (the four axes plus lifecycle and provenance):

| Field | Type | Meaning |
|-------|------|---------|
| `kind`, `subject_key`, `aliases` | key | What it is about; normalized key + alternative keys |
| `valid_from`, `valid_to` | time | Validity in the real world |
| `source`, `rank`, `approved_by` | — | Provenance: manual 1, observed 2, confluence 3, jira 4, model 5 |
| `scope` | — | project / global / personal; filtered at write time |
| `status` | — | `proposed` → `active` → `needs_review` / `stale` / `superseded` / `retired`; **new: `rejected`** |
| `anchors` | — | What in reality it depends on (file, URL pattern, page signature, config) |
| `verified_at` | time | Last time use confirmed it |
| `evidence` | ref | Pointers to source events (session, tool call, timestamp, result) |
| `conditions` | — | Where it holds: account / role, environment, app build or commit, tool, viewport… |

`rejected`: the record is not delivered, and the processor must not propose the same record
(same identity) again until new evidence crosses its threshold or an anchor changes.

Counts (uses, successes, failures) stay in the event log and daily aggregates — never in record
files ("observation is not understanding").

## 5. Kind contract changes

The v2 kind contract (9 questions) stays, with two changes:

- **Q8 "index needed"** becomes **"fields and their types"** (`key` / `text` / `time` / `ref`) plus the
  index mapping of § 6.
- **New Q10 "relations"**: which `ref` fields the kind has (relation type, target kinds) and whether
  it can be the subject of `link` records.

`kinds.py` must grow from 5 attributes (`name`, `description`, `source`, `review_days`, `delivered`)
to the full contract.

## 6. Index registry

kb ships a list of indexes. Each declares which field types it reads; each kind picks indexes from
the list and maps its fields. The core passes mapped values only — "this is text", "this is a ref".

| Index | Reads | Answers |
|-------|-------|---------|
| Key + alias | `key` | exact lookup |
| FTS (BM25) | `text` | words |
| Graph | `ref` (+ `link` records) | neighbours, routes, impact (reverse), context pack phase 2 |
| Time | `time` | ranges, latest |
| Vector (later) | `text` | meaning |

Example declarations:

```yaml
page:
  indexes:
    key:   { key: screen_key, alias: [url_pattern] }
    fts:   { text: [title, purpose] }
    graph: { ref: [reaches, implemented_by, tested_with] }
note:
  indexes:
    fts:   { text: [body] }
    graph: { ref: [about] }
    time:  { time: [created] }
link:
  indexes:
    graph: { from: from_key, to: to_key, type: rel, polarity: polarity }
    key:   { key: [from_key, to_key] }     # "which links touch X" for maintenance
```

Rules:

- A kind may only use indexes in the registry. A new index type is added to the registry, never to
  one kind.
- Default when a kind declares nothing: key + FTS.
- Adding an index to the registry needs no change to existing kinds; they opt in by declaration.
- `kb doctor` reports declarations that name unknown indexes or missing fields; `kb eval` decides
  whether turning an index on for a kind actually helps.
- Events use the same mechanism (mostly key + time).
- Unchanged from v2: indexes are rebuildable, isolated on failure (FTS / scan always remains),
  updated incrementally from `change_log` and the event-log offset, fused with RRF.

## 7. Relations

Where a relation comes from decides where it lives:

| Origin | Example | Stored? | Rank / status |
|--------|---------|---------|---------------|
| Intrinsic to a record | `page.implemented_by = ref(file:…)` | Yes, as a `ref` field of that record | The record's |
| Person adds it | "this screen is tested with role RM" | Yes, `link` record (or the record's `ref` field) | 1, `active` |
| Agent proposes it | "this screen reads table CUSTOMER" | Yes, `link` record | 5, `proposed` or `active` by policy |
| Feedback | `kb feedback`: link useful / wrong / missing | Updates score and `verified_at`; may create or reject a `link` | — |
| Learned from events | screen X then edit file Y in ≥3 independent sessions | Proposal only (outbox / `link` `proposed`) | 2, `proposed` |
| Derived from code | `event=list_my_portfolio` → Action → forward → JSP | **No** — a processor recomputes it at build time; anchor = the config file | by source |

`link` record: `from_key`, `rel`, `to_key` (identity), `polarity` (`+` / `−`), `reason`, plus the
common fields. Graph build:

```
edges = ref fields (+) ∪ derived (+) ∪ learned (+) ∪ link records with polarity +
for each link record with polarity − matching (from, rel, to) and status active:
    rank(−) ≤ rank(+) number-wise (as trusted or more) → drop the edge; keep it as a warning
                                                          returned when a query touches it
    otherwise                                          → open a conflict for review
link − with status proposed → lower the edge weight only
```

Edge weight = f(rank, status, freshness, feedback score); for `reaches` also success rate and cost.

Status vs polarity:

| | `+` | `−` |
|---|---|---|
| active | My Portfolio is handled by `CustomerSearchAction` | Opening My Portfolio by URL → Access Denied |
| proposed | Agent guesses the screen uses table CUSTOMER | Agent saw demo_gh1 denied once |
| rejected | Person: "this screen does not use that file" — blocks the same proposal | Person: "demo_gh1 can enter; that was an expired session" |
| needs_review | The Action file changed | The role's permissions changed |

Cross-kind queries need nothing extra: endpoints are subject keys (`page:list.portfolio`,
`file:src/…/CustomerSearchAction.java`), never temporary URLs or refs. A missing endpoint flags the
relation `needs_review` instead of deleting it. Scope is filtered before traversal (no `personal`
nodes in project answers). Traversal has a depth (default ≤ 2) and line budget.

## 8. Traceability (negatives first)

A negative is usually true only under conditions. Seen on CLOS: on 2026-10-20 `find "My Portfolio"`
on Home found refs and the click worked; on 2026-10-21 the same call found nothing and every menu
ref was "outside the viewport". A negative written from the second run alone would be wrong.

Store, per record (mandatory for negatives, available to all):

- `evidence`: the source events (session, time, tool call, result).
- `conditions`: account / role, environment, app build, tool, viewport.
- error class from the error signature: **real** (Access Denied, permission) vs **transient**
  (expired session, app down, page still loading).
- `recheck`: short reproduction steps or a probe.

Rules:

- Transient errors never become negatives; the processor classifies by error signature first.
- A negative needs ≥ 2–3 independent sessions or a person's confirmation; one failure is an event.
- State the conditions in the claim ("demo_gh1 denied on screen X, local env"), not a global claim.
- Agent-written negatives default to `proposed` and are delivered with their count and conditions.
- Counter-evidence: a later success matching (from, rel, to) under the same conditions moves the
  negative to `needs_review` (conflict if the negative has the higher rank). Anchor drift does the same.
- `kb why <key>` prints: claim → evidence events → session / transcript → who approved → history.
  Works for every record.

## 9. Page map as an application

What the CLOS run showed, and where each fix lives:

| Gap in v2 | Fix | Lives in |
|-----------|-----|----------|
| URL does not identify the screen (`Login.do` = Home; posts show bare `X.do`; Home is also `HomePage.do`) | Screen key from a site profile; fallback chain: app key → URL + kept params → tab title (stripped) → heading | `site_profile` data + `page` processor |
| "Prefer opening the URL" breaks session-bound apps | `direct_url: allowed \| login_only \| never` + an `anchor` screen; routes for `login_only` are login → anchor → clicks | `site_profile` data + graph query |
| Query string dropped (`?event=` distinguishes screens) | `keep_params` / drop list (`jsessionid`, timestamps) | `site_profile` data + `page` processor |
| Page signature and title: no source defined | Adapter reads the tab title from "Tab Context" (free); an agent probe returns small JSON for the app key / signature | adapter + probe convention |

`site_profile` kind: rank 1, written by a person; key = host + base path; aliases for staging /
production; fields `screen_key`, `title_strip`, `keep_params`, `direct_url`, `anchor`.

```yaml
# site_profile  localhost:8080/clos
screen_key: js:globalCurrentPageForward   # verified: home.main.page, list.portfolio
title_strip: " - Time left.*"
keep_params: [event]
direct_url: login_only
anchor: home.main.page
```

Probe convention (any harness that runs JS): return `{"__kb_screen": {"key", "title", "url",
"signature"}}`; the adapter recognises the marker. Run it on unknown screens only.

Action labels: from `action_summary` or the locator (`a[href=…]`, role + name), never
`browser_batch`, refs or coordinates.

## 10. What this supersedes in the Claude Docs design

- *Sơ đồ trang v2*: the page-only graph database (`index/graph-v1.db`) → the one graph index of § 6;
  "prefer opening the URL directly" → the site profile's `direct_url`.
- *Hợp đồng kind* Q8 → § 5.
- Open question "may the model write knowledge directly?" → yes, at rank model, through the write
  gate, status by policy (§ 7).
- Open question "page node: URL pattern only or + state?" → screen key from the site profile with the
  fallback chain of § 9.

## 11. Code gaps (v0.1 → this model)

| Gap | Now | Target |
|-----|-----|--------|
| Events | `tool_events` with fixed `url`, `target` | Common event with the four axes + open `signals` |
| Sources | `adapters/claude_code.py` parses and processes | Adapter / connector interface (§ 3) |
| Processors | Page learning inside `browser.py`, writes items itself | `processors/*` return proposals; the write gate decides |
| Kinds | 5 attributes | Full contract incl. field types and relations (§ 5) |
| Indexes | FTS only; page graph separate in `browser.py` | Registry with field-type mapping; one graph index |
| Record fields | no `conditions`; `evidence` not linked to events | § 4 |
| Status | no `rejected` | § 4 |
| Commands | no `kb why` | § 8 |
