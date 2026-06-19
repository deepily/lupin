# Task Store — Daily-Use Adoption-Gaps Inventory

**Date**: 2026.06.15 (EDT)
**Author / owner**: Krishna 🦚 — session `7e8fb0d6` (living R&D findings doc)
**Status**: SURVEY (read-only) — surfacing gaps that block *daily* adoption of the unified task store. Closes nothing; each fix is gated on Rick's direction.
**Hub-spoke**: this is the **spoke** (what's broken). The **hub** — `planning-is-prompting → workflow/task-store-discipline.md` (owner: María 🌸, v0.3→v1.0) — cites it from a "Known gaps & friction" pointer section. Kept separate so the prescriptive how-to stays clean and this inventory can churn without version-bumping the conventions doc (María's call, 2026-06-15).
**Context**: build is DONE + held + reviewer-approved (`01-build-plan.md`; held commit `ab40b62b`); the 4 MCP tools are LIVE on `:7999`. The gap is **adoption**, not capability.

---

## How this was found
- **Live E2E hand-run** on `:7999` (probe `c5ba4603`) walking all 4 tools through every gate (receipts verbatim in `01-build-plan.md`).
- **Discoverability grep** of project + global `CLAUDE.md` (0 hits).
- **Read** of the live discipline doc (`task-store-discipline.md` v0.3) + the wrapper transport (`src/lupin_mcp/task_store_tools.py`).

The capability surface is sound. Every gap below is an **adoption friction** — a reason a real session won't reach for the store, or will stumble when it does.

---

## Owned by the conventions doc (María) — cross-ref only, NOT my action

- **Receipt-shape scope-prefix** — `→done` `receipt_refs` `doc_path`/`log_line` must be `<registered-scope>/<rel-path>[:lineno]` (a bare `src/...` 422s: *"receipt path scope 'src' is not a registered repo scope"*). Folding into discipline-doc §4 + §10.1 "Rejection B".
- **`task_correlate` vs `receipt_refs` conflation** (Rick hit it) — "cite a commit/PR/DM" = `receipt_refs` at `→done`; `task_correlate` = cross-session respawn adoption. Folding into discipline-doc §10 (split §10.1 cite-to-commit / §10.3 adopt-across-sessions).

These two are captured + owned by María (v1.0). Listed so the inventory is complete; no duplication.

---

## MY gaps (priority order)

### A — Discoverability: zero CLAUDE.md pointer (HIGHEST — blocks all adoption)

**Finding**: the task store, the 4 tools (`task_create`/`task_query`/`task_transition`/`task_correlate`), and the discipline doc are referenced in **neither the project `CLAUDE.md` nor the global `~/.claude/CLAUDE.md`** (grep: 0 hits). The discipline doc applies to "any session in a repo where the task-store is live" — but **nothing tells a session it's live**.

**Why it blocks daily use**: a fresh session has no in-context signal the store exists or that it should write to it. The tools are MCP-listable, but the *discipline* (when to create, the receipts gate, cross-session adoption) is invisible. Without this pointer, every other gap is moot — sessions never start.

**Fix (low-risk — recommend closing first)**: add a `## UNIFIED TASK STORE` pointer block to project `CLAUDE.md` — one paragraph + link to `task-store-discipline.md` + the 4-tool one-liner + the managers-first note + the §DOCUMENTATION TOUCHPOINTS row. Mirrors the existing CJ Flow / cost-model pointer pattern. **Code-free, reversible, single file.**

### E — Chase consumer is flag-OFF + unwired: the "no pending-X graves" promise isn't live

**Finding**: `task store chase enabled` defaults **False**, and `TaskChaseConsumer.start()` is **not wired into server boot** (Item E shipped activation as "the deliberate opt-in step, NOT done here"). A `→blocked` item with a valid `next_chase_ts` is recorded correctly but **nothing chases it**.

**Why it blocks daily use**: the discipline doc §4 sells `→blocked` as "says what it waits ON and when it will be chased / no pending-X graves." Until the flag flips + boot-wiring lands, the *chase* half is aspirational — a user who blocks a task trusting it'll be nudged is let down. This is the single biggest gap between the doc's promise and live behavior.

**Fix (DECISION for Rick — go/no-go)**: flip `task store chase enabled = true` + wire `start()` into server boot (flag-gated). Outbound-notification blast radius is *why* Item E shipped OFF — this is a deliberate go/no-go, not a silent default. If GO: needs the boot-wire + a chase-fires integration test on `:8000`.

### D — Query ergonomics: no any-open set, no combined owner/accountable, no title search

**Finding**: `task_query` `status` takes a **single** value. Common daily queries are awkward:
- "All my OPEN work" = `queued` ∪ `in_progress` ∪ `blocked` → **3 calls** (or no-arg + client filter).
- "Everything I own OR am accountable for" → no combined filter (two calls).
- "Find the task about X" → no title substring search.

**Why it blocks daily use**: the no-arg manager glance works, but targeted owed-work queries need multiple round-trips, discouraging the quick-check habit the store depends on.

**Fix (CODE — needs Rick's go)**: add `status__in` (CSV → SQL `IN`) and/or an `open=true` convenience (server expands to the non-terminal set); optionally `title_contains`. Server-side, bounded (`Query(...)`), additive; 100% L/B on the new branches. Lower priority than A/E.

### F — Write scope still managers-first: worker self-tracking not yet live

**Finding**: writes are **managers-first** (social + audit, not gated). The "widening rider" (discipline-doc §2.1, Rick double-anchored) widens writes to ALL sessions **after Phase 1–2 prove out** — we are now past Phase 2.1 green. Until widened, a worker's cross-session obligations only enter via manager/DM **auto-create (T4)** — which is **deferred (Item F, Phase 2.2)**.

**Why it blocks daily use**: a non-manager session today cannot durably self-track a cross-session obligation through the store; it falls back to markdown. The store's fleet-wide value (not just managers) is gated on this.

**Fix (DECISION for Rick — go/no-go)**: is Phase-2.1-green enough to trigger the widening rider now (mostly a practice/doc change — enforcement was always social), or does it wait for T4 auto-create (Phase 2.2)? Either way, document the call explicitly so the rider "doesn't get lost" (the doc §2.1's own warning).

---

## Recommended sequencing

| # | Gap | Type | Gate | Recommend |
|---|---|---|---|---|
| A | CLAUDE.md discoverability pointer | doc (Lupin) | low-risk | **Close first** on Rick's nod |
| E | Chase consumer flag-on + boot-wire | code + decision | **Rick decision** | go/no-go (biggest promise gap) |
| D | Query ergonomics filters | code | Rick's go | backlog — after A/E |
| F | Write-scope widening rider | decision | **Rick decision** | go/no-go (policy) |
| (B,C) | receipt scope-prefix / correlate clarity | doc (María) | none | folding into v1.0 — not mine |

**Division of labor**: A is a Lupin `CLAUDE.md` edit I can do on Rick's nod. D is a bounded code task. E + F are Rick decisions (blast-radius / policy) — surfaced, not taken. B + C are María's.

**Companion deliverable** (separate, for María's §9 v1.1): the **exhaustive legal-transition-edge matrix** — every non-terminal→every-other edge accept + terminal/no-op rejects, each with verbatim server response, probed self-cleaning on `:7999`. Handed to María directly.

---

## Cross-references
- Build plan + receipts: `01-build-plan.md` (this dir)
- Conventions doc (owner: María): `planning-is-prompting → workflow/task-store-discipline.md` (v0.3 WIP)
- Design of record: `planning-is-prompting → src/rnd/2026.06.11-unified-task-store-design.md` (v0.4.1)
- Wrapper transport: `src/lupin_mcp/task_store_tools.py`
- Held E2E suite: `src/tests/integration/test_task_store_integration.py` (`TestTaskStoreWrapperE2E`, commit `ab40b62b`)
