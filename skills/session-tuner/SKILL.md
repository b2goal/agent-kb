---
name: session-tuner
description: Tune this project's Claude Code workflow from agent-kb telemetry - propose CLAUDE.md notes and permission allow rules that remove wasted turns, and write conventions for repeated errors. Use when the user runs /session-tuner, when the status line says "kb tune", or when the user asks to optimize their workflow, permissions or CLAUDE.md.
---

# Session tuner (agent-kb)

All numbers come from `kb` (deterministic, no model calls). Your job is the part that needs judgment:
turning repeated errors and re-read files into one-line conventions, and presenting choices.

## 1. Collect evidence

Run each as ONE plain command (no `cd`, no `;`/`&&` chains):

```
kb ingest --recent 50
kb tune --json
```

If `kb` is missing, tell the user to install agent-kb (`uv tool install …` then `kb setup claude`) and stop.
If the summary shows fewer than 5 sessions, say the numbers are still noisy.

## 2. Turn `needs_model` items into convention lines

- `error_convention`: read the signature. If it shows a project convention the model did not know (data
  format, helper to use, import path, env var, build step), write ONE line stating the convention.
  Look at the code only if the signature alone is not enough. Never write bug-specific fixes or secrets.
- `module_map`: for a file re-read many times, one line saying what lives there.

## 3. Present and confirm

Show a 4–6 line evidence summary (numbers from the JSON), then the numbered proposals from the outbox plus
your convention lines. Ask which to apply and where allow rules go: `local` (personal, default) or
`shared` (team). Use AskUserQuestion when available. Apply nothing before the user answers.

## 4. Apply

- Proposals from the outbox: `kb tune --apply latest --select <numbers> --target local|shared`
  (add `--include-review` only for review-level rules the user approved by name).
- Each convention line you wrote and the user approved:
  `kb add convention <short-subject> --body "<the line>"`, then `kb export claude-md --write`.

`kb tune --apply` saves a baseline. Tell the user the status line will flag the next round when the
data justifies it, and `kb stats` shows the change against the baseline.
