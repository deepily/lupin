# Multiplexer Parity — Build-Plans Corpus (index + shared template)

**Date**: 2026-06-26 (this session, for Rick)
**Status**: 🟢 ALL 11 DRAFTS WRITTEN (2026-06-26) — ready for the **cascaded review** process (run on
Rick's dev server, not the laptop). See §Cross-cutting for the F0 shared foundation + the review agenda.
**Purpose**: a complete, self-contained plan per accordion covering ALL ratified parity work, so the
set can be fed to cascaded review one at a time. Decisions of record: doc `00-index.md` (a/b/c, B4
mechanism), doc `04` §Resolved (d/e/f/g), TODO Decisions Log 2026-06-26. Reconciliation + the
`4b33ceb7` conflict: doc `02`.

> These are DRAFTS — intentionally not yet ratified. Cascaded review is the gate before any
> implementation (mirrors the 06.22 full-parity build's process: plan → cascaded review → execute).

## The corpus (build sequence = review order)

| # | Plan | Accordion | Nature | Status |
|---|------|-----------|--------|--------|
| 01 | [CC-session B1–B5](01-cc-session-B1-B5.md) | Notifications (#5) | keystone — #1 priority | DRAFT |
| 02 | [Action Required funnel restore](02-action-required-funnel.md) | #3 | partial → full restore | DRAFT |
| 03 | [TTS Queue full restore](03-tts-queue-full-restore.md) | #4 | partial → full restore | DRAFT |
| 04 | [Job Queues mutation gaps](04-job-queues-mutation-gaps.md) | #9 | partial → close gaps | DRAFT |
| 05 | [Q&A Interface](05-absent-qa-interface.md) | #1 | absent → build | DRAFT |
| 06 | [Submit Agentic Jobs](06-absent-submit-agentic-jobs.md) | #2 | absent → build (heaviest) | DRAFT |
| 07 | [Time Saved](07-absent-time-saved.md) | #10 | absent → build | DRAFT |
| 08 | [Filter Settings](08-absent-filter-settings.md) | #8 | absent → build | DRAFT |
| 09 | [Direct TTS Test](09-absent-direct-tts-test.md) | #12 | absent → build | DRAFT |
| 10 | [Debug Info](10-absent-debug-info.md) | #13 | absent → build | DRAFT |
| 11 | [System Status](11-absent-system-status.md) | #11 | absent → build | DRAFT |

Fleet Status (#6) and Task List (#7) need **no build plan** — already at parity (Task List as an
accepted superset per ruling (f); only the read-only-contract doc note + a live-render check remain).

## Cross-cutting mandates (every plan inherits — do NOT restate, reference here)

1. **100% coverage L/B/F** — Python `pytest --cov-fail-under=100`; TS `c8 --100`. `# pragma: no cover` /
   `c8 ignore` only for genuinely-unreachable defensive branches with a same-line reason. (CLAUDE.md §100% COVERAGE MANDATE.)
2. **Layout-Parity Oracle, Tiers 0–4** (methodology `2026.06.19-…/01-layout-parity-methodology.md`):
   T0 CSS-hash → T1 DOM-contract → T2 computed-style → T3 geometry → T4 pixel backstop. Each plan names
   which tiers gate which nodes + any new golden captures needed (legacy `:8000` capture cost).
3. **Single-source CSS** — style from `css/shared/notifications-surface.css`; never fork a copy. New
   styles extend the shared sheet; legacy links it before its monolith.
4. **Venue routing** (CLAUDE.md §TESTING VENUES): unit/inline-smoke/WS-smoke → **:7999** (AI-discretionary);
   integration / E2E-UI+visual / proxy / regression → **:8000** scheduled via `POST /api/test-suite/submit`
   (self-authorized on a verified-idle server; never side-door).
5. **Manage-don't-build / lane isolation** — parallel lanes in worktrees; convergence files
   (`boot.ts`, `multiplexer.html`, `EventBus` union, `StorageService`, shared CSS) **manager-serial-merged**.
6. **Coordinate with in-flight crews** — Tiberius full-parity build (`704c71b2`, Foundation `3a5d87eb`);
   Rachel section-toolbar branch `mux-section-toolbar-accordion-toggle` (commit-held); focus-bar work
   committed `4b33ceb7` (**push held for Rick**). Plan 01's B1 restructures `4b33ceb7` — coordinate.
7. **Doc touchpoints** (CLAUDE.md §DOCUMENTATION TOUCHPOINTS) — name any docs each plan must update.

## Shared plan template (every NN-*.md follows this section order)

```
# <Accordion> — <Build|Restore> Plan
**Date / Status (DRAFT for cascaded review) / Author / Source audit refs / Decision-of-record refs**

## 1. Goal & parity target           — 1–2 sentences; what "done" looks like vs legacy.
## 2. Scope                          — IN / OUT bullets; the ratified ruling this executes.
## 3. Source anchors                 — legacy file:line (reference behavior) + mux target files (add/edit).
## 4. Dependencies & prerequisites   — cross-plan prereqs (e.g. AudioStore multi-item; B1↔4b33ceb7),
                                        carves inherited, INI keys, endpoints.
## 5. Work breakdown                 — numbered tasks/buckets. Each: what · files · ACs (functional +
                                        structural) · which Oracle tier(s) gate it.
## 6. Test strategy & venue routing  — unit/smoke (:7999) + integration/E2E/visual (:8000 scheduled);
                                        new fixtures; 100% L/B/F statement.
## 7. Oracle & visual parity         — tiers exercised; golden captures/rebaseline needed.
## 8. Risks & open questions         — for the reviewers; anything genuinely ambiguous.
## 9. Lane decomposition & est.      — suggested parallel lanes + convergence-file callouts + rough size.
```

Keep each plan self-contained enough to review in isolation; cross-reference rather than duplicate.

---

## Cross-cutting: shared foundation + convergence (READ before scheduling lanes)

### F0 — Shared `AudioStore` foundation (build FIRST; gates plans 01, 02, 03, 05)

Four plans independently hit the **same** gap: `js/multiplexer/stores/AudioStore.ts` tracks only coarse
state (idle/playing/paused) over a single PCM stream — it exposes neither (a) the **per-notification id
currently being spoken**, nor (b) a **multi-item queue** model.

- **Plan 01 (B4)** needs the active notification id to gate `is-playing-current` on the right bubble.
- **Plan 02 (Action Required)** needs live countdown gated to the active item only.
- **Plan 03 (TTS Queue)** needs a multi-item queue layer (`enqueue/advance/removeById/clear/current/pending`).
- **Plan 05 (Q&A metrics)** needs a submit→answer→`playing` correlation.

**Recommendation**: land an `AudioStore` extension (active-id emission + item-queue layer) as a single
**foundational lane F0 before** the 01/02/03/05 feature work. It is the keystone shared dependency of the
whole corpus and should be the first thing cascaded review scopes.

### Convergence files & crew collisions

- `render/templates/sectionToolbar.ts` — plans **02, 05, 07, 10, 11** each add a `SECTION_TOGGLES` entry
  → all collide with Rachel's commit-held `mux-section-toolbar-accordion-toggle` branch. Serialize + coordinate.
- `boot.ts`, `multiplexer.html`, `shared/types.ts`, shared CSS, store/render barrels — touched by nearly
  every plan → **manager-serial-merge** (no parallel edits to these).
- **Plan 01 (B1)** restructures push-held `4b33ceb7`; per-card-collapse ownership (DFB Lane B vs Rachel's
  branch) must be confirmed first.

### New design questions for Rick (surfaced during drafting — the cascaded-review agenda)

These are **not** blockers to the drafts; they gate specific plans' execution.

| Q | Plan(s) | Question |
|---|---|---|
| **e′** | 03 | TTS "reordering": legacy is **strict FIFO, NO drag-reorder**. Confirm FIFO-with-resync (legacy-faithful, recommended) vs a net-new pending-queue drag-reorder feature? |
| **h** | 05 | Q&A TTT/TTFA/RTT metrics: ship the DOM contract **inert** for parity + live numbers as a fast-follow, vs block the pane on the answer-correlation seam? |
| **i** | 08, 04 | Live job buckets are **WS-push (user-centric)**, not polled — faithful `others`/`all` for LIVE jobs needs a server WS-scope ruling; `/api/job-history` has no own/others/all param. Accept the history-only limitation (matches legacy) or add backend? |
| **j** | 09, 10, 11 | Dev/diagnostic panes (Direct-TTS, Debug, System-Status): **visible vs debug-gated vs admin-gated**? Does "present-but-hidden" satisfy total parity (g)? (legacy hid them behind collapsed sections.) |
| **k** | 11 | System Status: full port, or a user-facing **subset** (auth/user/missed only) with health + config-reload/logout sliced off? |
| **l** | 06 | Submit-Jobs `websocket_id`: unify the mux's single queue-session id, or preserve legacy's `sessionId`-vs-`queueSessionId` distinction (server may treat differently)? |
| **m** | 04 | **Latent bug to fix on the way**: per-job delete routes by `job.status` not bucket → deleting a history card wrongly hits `/api/queue/done/{id}` and silently 404s. Route history deletes to `/api/job-history/{id}`. |

### Backend-touch flags (not pure front-end)

Most plans are front-end-only on existing endpoints, EXCEPT: plan 08 (history own/others/all param — Q i),
plan 05 (answer-correlation seam if live metrics chosen — Q h). Reviewers should route these to a backend lane.
