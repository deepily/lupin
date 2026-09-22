# Job Queues (jobs-pane) — Mutation-Gaps Close Plan

**Date**: 2026-06-26 (this session, for Rick)
**Status**: 🟡 **DRAFT for cascaded review** (run on Rick's dev `:7999`, not the laptop).
**Author**: build-plans corpus, plan 04 of 11 (accordion #9).
**Source audit refs**: doc `04-remaining-accordions-audit.md` §"#9 Job Queues → jobs-pane" (verdict ⚠️ PARTIAL — display present, mutations/controls missing).
**Decision-of-record refs**: TODO Decisions Log 2026-06-26 (total 13/13 parity through-line); ruling (g) "port ALL absent accordions / close all partials"; this plan executes the #9 partial→full close.

> Shared template + cross-cutting mandates live in [`00-plans-index.md`](00-plans-index.md). This plan inherits all 7 cross-cutting mandates (100% L/B/F · Layout-Parity Oracle T0–T4 · single-source CSS · venue routing · lane isolation · in-flight-crew coordination · doc touchpoints) by reference — they are NOT restated here.

---

## 1. Goal & parity target

The mux `jobs-pane` already **displays** the 5 buckets (todo / running / done / dead / history) with collapse, counts, aria, and single-shot history hydration — that half is a faithful port (audit §#9). This plan closes the remaining **mutation / control** gaps so a user can manage jobs from the mux exactly as in legacy `#section-queues`: per-job delete (enabled, correctly routed), per-bucket delete-all 🗑, history time-window selector (1/7/14/30/all days), history load-more pagination, and per-job retry. "Done" = every legacy `#section-queues` control has a working mux equivalent on the same endpoints, at 100% L/B/F, with the queues filter-badge landed as a **hidden static badge + TODO seam** (live plan-08 filter-store wiring is OUT of D1 scope — per F-Clay-B4).

## 2. Scope

**IN**
- W1 — **Enable** the already-half-wired per-job delete (template ships it disabled; renderer un-disables + handles clicks). Includes the **history-bucket routing fix** (see §4 / W1 — a latent bug today).
- W2 — Per-bucket **delete-all** 🗑 button on every `.jobs-bucket-header` (live buckets + history), confirm dialog, correct endpoint per bucket.
- W3 — History **time-window** selector (1 / 7 / 14 / 30 / all days) → re-hydrate history on change. Requires making `JobStore.hydrateHistory` parametrized + re-runnable.
- W4 — History **load-more** pagination (offset/limit append), with a Load-More affordance shown only when `loaded < total`.
- W5 — Per-job **retry** for failed/dead + history terminal jobs (`POST /api/job-history/{id}/retry`).
- W6 — `queues-filter-badge` **display hook** in the jobs-pane header (👤 Mine / 🌐 Others / 🔵 All), reflecting the shared filter mode.

**OUT** (explicit)
- The filter **store + mode-switch UI** itself — owned by **plan 08 (Filter Settings)**. W6 here only renders the badge bound to whatever store plan 08 lands. If plan 08 ships first, W6 wires to it; if this plan ships first, W6 lands a no-op-default badge (hidden) plus a TODO seam. **Hard cross-plan dependency — see §4.**
- `exclude_own_jobs` plumbing on the history/queue fetches — also plan 08 (the param is a filter-mode concern; `GET /api/job-history` has no `exclude_own_jobs` arg today, only admin-vs-owner scoping — queues.py:1314-1362).
- Server-side endpoint work — **all five endpoints already exist** (§3). This is a pure front-end (TS/CSS) plan.
- Pause/resume (`PATCH /api/queue/todo/{id}/pause|resume`) — not a legacy `#section-queues` control in the audited block; deferred.

The ratified ruling this executes: doc 04 §"Resolved" (g) — total 13/13 parity, no "obsolete" drops.

## 3. Source anchors

### Legacy reference behavior (read-only — DO NOT port verbatim; mirror semantics)
- **HTML** `static/html/notifications.html`:
  - `#section-queues` block **L910-1033**: `#queues-filter-badge` (L913-914), 5 `.queue-category` blocks each with `.queue-count-badge` + `.queue-delete-all-btn` 🗑 (todo L926-928, run L944-946, done L961-963, dead L978-980), `toggleQueueCategory` headers, history block L1001-1031 with `#history-time-window` `<select>` (1/7/14/30/all, L1007-1013), `#history-count-badge`, `#history-delete-all`, `#history-pagination` + `#history-load-more` (L1027-1030).
- **JS** `static/js/notifications.js`:
  - `loadJobHistory(append)` **L6519-6589** — builds `/api/job-history?days=&limit=20&offset=&exclude_ids=`; append vs replace; shows/hides `#history-pagination` when `jobs.length < total`.
  - `deleteJob`/history delete **L6695-6716** → `DELETE /api/job-history/{id}`.
  - `deleteQueueJob(jobId, queueName)` **L6717-6759** → `DELETE /api/queue/{queue}/{id}` (note `run`-vs-`running` label).
  - `deleteAllQueueJobs(queueName)` **L6760-6814** → `DELETE /api/queue/{queue}/all` (live) **OR** `DELETE /api/job-history/all?days={N}` (history); confirm with count + "interrupt active jobs" warning for `run`.
  - `retryHistoryJob(jobId, questionText)` **L6818-6855** → `POST /api/job-history/{id}/retry` body `{ websocket_id }`.
  - `onHistoryTimeWindowChange(value)` **L6856-6877**, `loadMoreHistory()` **L6878-6883**.
  - `setFilterMode(mode)` **L6197+**, `#queues-filter-badge` updates **L6247 / L6301-6315** (plan 08 territory; W6 reads).
  - `toggleQueueCategory(queueName)` **L6369+** (already ported as `toggleBucket` in jobBucket.ts).

### Server endpoints (all already mounted — `cosa/rest/routers/queues.py`)
- `DELETE /api/queue/{queue_name}/{job_id}` — **L1188** (per-job, live buckets). UI `running`→server `run`.
- `DELETE /api/queue/{queue_name}/all` — **L1112-1186** (delete-all, live buckets).
- `GET /api/job-history` — **L1308-1362**; params `limit (1-100, default 20)`, `offset`, `days (1-365)`, `exclude_ids`, `status`, `job_type`. Returns `{ jobs, total, filtered_by, limit, offset }`.
- `DELETE /api/job-history/all?days={N|all}` — **L1399-1452** (delete-all history).
- `DELETE /api/job-history/{job_id}` — **L1454+** (per-job history delete).
- `POST /api/job-history/{job_id}/retry` — **L1495-1556**; body `{ websocket_id }`; re-submits to todo.

### Mux targets (add / edit)
- `js/multiplexer/render/JobsPaneRenderer.ts` — **edit**. Already has `handleDeleteClick` (L396-430) + the `UI_STATUS_TO_SERVER_QUEUE` map (L96-101) + the `stripInertnessMarkers` hack (L330-339). W1 removes the hack & fixes history routing; W2/W3/W4/W5/W6 add delegated handlers.
- `js/multiplexer/stores/JobStore.ts` — **edit**. `hydrateHistory(api)` (L155-186) is once-only (`historyHydrated` guard, hardcoded `limit=100`, no `days`/`offset`). W3/W4 parametrize + make re-runnable + track `offset`/`total`. `delete(idHash)` (L192-212) already returns `{ restoreState }`.
- `js/multiplexer/render/templates/jobBucket.ts` — **edit**. Header (L88-100) gains 🗑 delete-all button; history bucket additionally gains the `<select>` time-window + Load-More affordance.
- `js/multiplexer/render/templates/jobCard.ts` — **edit**. `renderJobCard` (L241-267) ships the delete `<button>` with `aria-disabled="true" tabindex="-1" title="Delete coming in Phase 6b"` (L258) → render it **enabled**; add a Retry button on terminal (dead/history) cards.
- `css/multiplexer/jobs-pane.css` — **edit** (366 lines today). Add `.queue-delete-all-btn`, `.history-time-select`, `.history-load-more`, `.job-retry-button`, `.queues-filter-badge` rules — **extend the single shared surface, never fork** (mandate 3). Cherry-pick legacy class names verbatim per the file's existing Q-C convention.
- `js/multiplexer/render/templates/index.ts` / `boot.ts` — **edit** only if a new shared helper or the history-load button wiring (`.jobs-pane-history-load`, multiplexer.html L122-123, currently **unwired**) needs a mount-time bind.

## 4. Dependencies & prerequisites

- **Plan 08 (Filter Settings) — hard coupling for W6.** The `queues-filter-badge` reflects the own/others/all filter mode whose store + 3-button switch are plan 08's deliverables. **Sequencing call for reviewers**: either (a) land plan 08 first and W6 reads its store, or (b) land W6 here as a hidden default-Mine badge with a documented seam and let plan 08 light it up. Recommend (b) so this plan is not blocked. The `exclude_own_jobs` query-param plumbing stays entirely in plan 08.
- **Latent bug surfaced by W1 (must fix in W1, not defer):** the existing `handleDeleteClick` derives the server queue from `job.status` via `UI_STATUS_TO_SERVER_QUEUE` (4-value: todo/run/done/dead). A **history-bucket** card has `status` done/dead but the job is no longer in any live queue — deleting it would wrongly `DELETE /api/queue/done/{id}` (404 → silently treated as success per the 404-is-success branch, L419-421, masking the bug). W1 must **route by bucket, not status**: history-bucket → `DELETE /api/job-history/{id}`; live buckets → `DELETE /api/queue/{queue}/{id}`. Use `indexById`/`getById` bucket, not `job.status`.
- **`JobStore.hydrateHistory` is once-only today.** W3 (time-window change) and W4 (load-more) both require it to be re-runnable and parametrized (`days`, `limit`, `offset`, append-mode). This is the foundational store change — W3/W4 share it; do it first within this plan.
- **websocket / session id for W5 retry.** Legacy passes `{ websocket_id: this.queueSessionId }`. The mux equivalent must source the active session id from the transport layer (the same id the WS channel registers). Reviewers: confirm the canonical mux accessor (likely off the transport store / boot-wired session id) — **open question Q3**.
- **No INI keys** introduced. **No new endpoints.** **No new router** → the §DOCUMENTATION TOUCHPOINTS "new router" / "routers/*.py" rows do NOT fire. Doc updates are limited to the parity-tracking docs (§this rnd folder) + a note in `src/docs/rest-api-reference.md` only if a previously-undocumented endpoint is now surfaced (the 5 already exist; verify during impl).
- **Inherits** the Phase-6b delete contract already encoded in JobsPaneRenderer (optimistic delete + rollback + inline error stripe, Q-B10) — W2/W5 should reuse the same optimistic+rollback pattern where a single job moves; bulk delete-all is a refetch-after-2xx (no per-card optimistic rollback).

## 5. Work breakdown

Each task: **what · files · ACs (functional + structural) · Oracle tier(s)**.

### W1 — Enable per-job delete + fix history routing
- **What**: Render the delete button enabled; remove the renderer's `stripInertnessMarkers` post-render hack (it un-disables markers the template never should have shipped). Route delete by **bucket**: live → `/api/queue/{queue}/{id}`, history → `/api/job-history/{id}`.
- **Files**: `jobCard.ts` (L258 button attrs), `JobsPaneRenderer.ts` (drop L325-327 + L330-339 strip; rework `handleDeleteClick` L396-430 to branch on bucket).
- **ACs (functional)**: clicking `×` on a live-bucket card optimistically removes it + DELETEs the live queue endpoint; on 5xx it rolls back + shows the inline error stripe (existing Q-B10 path). Clicking `×` on a history card DELETEs `/api/job-history/{id}` (not `/api/queue/...`). Rapid double-click is a no-op (existing `deleteInFlight` guard). 404 → treated as success.
- **ACs (structural)**: `grep -c 'aria-disabled\|tabindex="-1"\|Delete coming in Phase 6b'` over `jobCard.ts` delete button = **0**. `stripInertnessMarkers` removed (no callers). Delete button class stays `.job-delete-button` (legacy parity).
- **Oracle**: T1 DOM-contract (button no longer `aria-disabled`); T0 CSS-hash (enabled-state styling unchanged vs legacy `.job-delete-button`).

### W2 — Per-bucket delete-all 🗑
- **What**: Add a `.queue-delete-all-btn` (🗑) to every `.jobs-bucket-header`; click (stopPropagation so it doesn't toggle collapse) → confirm dialog (count + the `run`/`running` "interrupt active jobs" warning) → live: `DELETE /api/queue/{queue}/all`; history: `DELETE /api/job-history/all?days={selected}` → on 2xx refetch that bucket.
- **Files**: `jobBucket.ts` (header template + per-bucket button), `JobsPaneRenderer.ts` (delegated `.queue-delete-all-btn` handler — dispatch BEFORE the header-toggle path, mirroring the existing delete-button ordering at L360-367), `jobs-pane.css`.
- **ACs (functional)**: confirm-cancel aborts (no fetch). Confirm → correct endpoint per bucket; `running` bucket maps to server `run`; history uses the current time-window's `days`. Empty bucket → button still present but confirms "0 jobs". On success the bucket re-renders empty.
- **ACs (structural)**: one `.queue-delete-all-btn[data-bucket]` per bucket; click does NOT flip `aria-expanded` (stopPropagation verified by unit test).
- **Oracle**: T1 (button present per bucket), T0/T2 (🗑 sizing/color vs legacy `.queue-delete-all-btn`), T3 geometry (header layout with the added button).

### W3 — History time-window selector
- **What**: Add the `<select.history-time-select>` (1/7/14/30/all, default 30 per legacy) to the **history** bucket header only; onChange → reset history bucket + re-hydrate with `days`. Requires `JobStore.hydrateHistory` to accept `{ days, limit, offset, append }` and to be re-runnable (drop/relax the `historyHydrated` once-guard, or add `rehydrateHistory`).
- **Files**: `jobBucket.ts` (history-only select), `JobStore.ts` (parametrize L155-186; track `timeWindow`/`offset`/`total`), `JobsPaneRenderer.ts` (delegated `change` handler), `jobs-pane.css`.
- **ACs (functional)**: changing the window clears the history bucket and refetches `GET /api/job-history?days={N}&limit=20&offset=0` (`all` → omit `days`). Count badge reflects `total`. Selector click does not toggle the header (stopPropagation).
- **ACs (structural)**: `hydrateHistory` no longer hardcodes `limit=100`; accepts a days param; second call with a new window actually refetches (not short-circuited by the guard). `CommonsActivityRenderer`'s existing time-window pattern (its `:6 / :358` selector) is the in-repo precedent to mirror for consistency.
- **Oracle**: T1 (select options + default), T0 (select styling vs legacy `.history-time-select`).

### W4 — History load-more pagination
- **What**: Switch history hydrate to `limit=20` + offset paging (legacy parity). Render a Load-More affordance under the history bucket when `loaded < total`; click appends the next page. (The unwired `.jobs-pane-history-load` button at multiplexer.html L122 can be repurposed as this affordance, or a new per-bucket one added — reviewers pick, **Q2**.)
- **Files**: `JobStore.ts` (append-mode + `offset`/`total` state), `jobBucket.ts` (Load-More element gated on `loaded < total`), `JobsPaneRenderer.ts` (handler), `jobs-pane.css`.
- **ACs (functional)**: first hydrate fetches 20; Load-More fetches the next 20 with `offset=loaded` and **appends** (no duplicate cards — keyed-merge by `data-id-hash` dedups). Affordance hidden when `loaded >= total`. exclude/dedup of in-session done/dead preserved (mux dedups via the existing `inSessionIds` set, L166-171 — keep that, it's the mux equivalent of legacy `exclude_ids`).
- **ACs (structural)**: store exposes `historyTotal`/`historyOffset`; Load-More absent at `loaded >= total`.
- **Oracle**: T1 (Load-More presence toggles on total), T3 (append doesn't reflow earlier cards).

### W5 — Per-job retry
- **What**: Add a `.job-retry-button` (↻) to terminal cards (dead bucket + history terminal jobs); click → confirm → `POST /api/job-history/{id}/retry` body `{ websocket_id }` → on 2xx refresh history + live buckets (the WS `job_state_transition` for the re-queued job will repopulate todo automatically).
- **Files**: `jobCard.ts` (conditional retry button), `JobsPaneRenderer.ts` (delegated handler + session-id source), `jobs-pane.css`.
- **ACs (functional)**: retry button appears ONLY on dead/history cards (not todo/running/done). Confirm-cancel aborts. Success path posts with the active session id. Failure → inline error stripe (reuse the W1/Q-B10 stripe).
- **ACs (structural)**: no retry button rendered for non-terminal statuses (unit-tested per status).
- **Oracle**: T1 (retry button present iff terminal), T0 (↻ styling).

### W6 — Queues filter-badge (static no-op seam; plan-08 live-wiring OUT of D1 scope)
- **What**: Render a `.queues-filter-badge` in the jobs-pane header as a **hidden static default-Mine badge** with a **TODO seam COMMENT** marking where plan 08 will later wire it. Per §4 + **F-Clay-B4**: the live plan-08 store-wiring (others/all states) is **OUT of D1 scope** — plan 08's filter store does not exist under D1, so W6 does NOT subscribe to it. D1's W6 deliverable is the static hidden badge + the seam comment ONLY.
- **Files**: `multiplexer.html` (jobs-pane-header span) or `jobBucket`/renderer, `jobs-pane.css`. **No plan-08 event subscription** (that store does not exist and is OUT of D1 scope) — a TODO seam COMMENT marks the future wire point.
- **ACs (functional, D1)**: badge renders **hidden by default** (mode = own) as a static element. **OUT of D1 scope — NOT an AC here (deferred to plan 08)**: the others/all store-driven text+visibility updates. That branch depends on a plan-08 store absent under D1, so it is **not built and not tested here** — this deliberately avoids an unreachable branch colliding with the 100% L/B/F mandate (no `c8 ignore` needed because the branch is never authored). No behavior change to fetches.
- **ACs (structural)**: `data-testid="queues-filter-badge"` present (legacy parity); no `exclude_own_jobs` logic in this file; a `// TODO(plan-08): wire to filter store when it lands` seam comment present.
- **Oracle**: T1 (testid present, badge hidden). T2/T3 for the live others/all states are OUT of D1 scope (deferred to plan 08).

## 6. Test strategy & venue routing

Inherits venue rubric from index mandate 4. This plan is **TS/CSS-only**; no server mutation in the unit layer (stubbed `api.delete`/`api.get`/`api.post`).

- **Unit (`:7999`, AI-discretionary)** — `src/tests/unit/multiplexer/render/jobs_pane_renderer.test.ts` (+ a new `job_bucket.test.ts` / extend `jobCard`/`JobStore` specs). Cover: W1 bucket-routing branches (live vs history vs 404 vs 5xx-rollback), W2 confirm-cancel + per-bucket endpoint + stopPropagation, W3 re-hydrate-on-change + days param, W4 append + Load-More gating + dedup, W5 terminal-only button + retry POST + session id, W6 badge renders default-hidden (static — the plan-08 store-driven others/all states are OUT of D1 scope, not authored, not tested → no unreachable branch). Mock `confirm`/`fetch`. **100% L/B/F** (`c8 --100`) — every new branch tested or `c8 ignore` + same-line reason (mandate 1).
- **WebSocket smoke (`:7999`)** — confirm a retried job's `job_state_transition` repopulates the todo bucket end-to-end via `run-websocket-smoke-tests.sh` (extend if a jobs-pane scenario doesn't exist).
- **E2E UI + visual (`:8000`, scheduled via `POST /api/test-suite/submit`)** — Playwright: click delete on a live + a history card, delete-all per bucket, change time-window, load-more, retry. Visual-regression snapshots for the new buttons/select (rebaseline — §7). Self-authorized on a verified-idle `:8000` per index mandate 4 / CLAUDE.local.md.
- **Integration (`:8000`, FINAL gate)** — the real `DELETE /api/queue/.../all`, `DELETE /api/job-history/all`, and `POST .../retry` against API+DB+auth (these mutate persistent state — :8000 only, never :7999, never curl). Add to `run-integration-tests.sh` if a job-mutation workflow isn't already covered.

100%-coverage statement: **lines AND branches AND functions = 100%** on all touched TS via `c8 --100`; no "≥95%".

## 7. Oracle & visual parity

Tiers exercised: **T0** (CSS-hash on the cherry-picked legacy classes — `.queue-delete-all-btn`, `.history-time-select`, `.history-load-more`, `.queues-filter-badge`, enabled `.job-delete-button`), **T1** (DOM-contract: each new control present/absent per bucket + per status), **T2** (computed-style on the 🗑/↻/select), **T3** (geometry: bucket-header layout with the added 🗑 + history-header with select + badge), **T4** pixel backstop only on the history header (densest new layout).

**New golden captures needed** (legacy `:8000` capture cost): the legacy `#section-queues` header rows with delete-all buttons + the history header with the time-window select + pagination. Rebaseline mux snapshots for jobs-pane after each W lands. Methodology per `2026.06.19-…/01-layout-parity-methodology.md`.

## 8. Risks & open questions (for reviewers)

- **Q1 (sequencing)**: land plan 08 first (W6 reads its store) or land W6 here as a hidden-seam badge? Recommend the hidden seam so this plan isn't blocked. — see §4.
- **Q2 (load-more affordance)**: repurpose the existing-but-unwired `.jobs-pane-history-load` button (multiplexer.html L122) as the Load-More, or add a per-bucket Load-More under the history bucket (closer to legacy `#history-pagination`)? Recommend per-bucket for legacy parity + retire/repurpose the orphan header button.
- **Q3 (retry session id)**: confirm the canonical mux accessor for the active WS/session id to send as `websocket_id` in the retry POST. Legacy used `this.queueSessionId`.
- **Risk — history delete-all `days` semantics**: legacy `DELETE /api/job-history/all?days={N}` deletes within the **currently-selected** window. The mux must read the live `<select>` value at click time (not a stale store copy) to avoid deleting more/less than the user sees. Mitigated by reading the DOM select in the handler.
- **Risk — optimistic-delete vs bucket re-render race**: W1 keeps the existing Q-B10 optimistic path (single card); W2 delete-all is refetch-after-2xx (no optimistic removal) to avoid a 5-card rollback storm. Keep the two patterns distinct; don't unify.
- **Risk — `historyHydrated` guard removal (W3)** could re-trigger duplicate hydration on unrelated re-renders. Gate re-hydration strictly on the explicit time-window change / load-more, never on `store_jobs_changed`.
- **Latent-bug note (already in §4)**: today's history-card delete silently 404s through the success branch — W1's bucket-routing fix is mandatory, not optional.

## 9. Lane decomposition & estimate

The five mutation work-items all touch the **same four files** (`JobsPaneRenderer.ts`, `JobStore.ts`, `jobBucket.ts`, `jobCard.ts`) + the one CSS — so lane-level parallelism has heavy convergence overlap. Recommend a **mostly-serial single lane** with one internal ordering, rather than 5 worktrees fighting over the same files:

1. **W3-store-foundation** (parametrize/re-run `hydrateHistory` + offset/total state) — unblocks W3 & W4. Convergence file: `JobStore.ts`.
2. **W1** (enable delete + history routing fix) — smallest, removes the strip hack; do early to clean the renderer.
3. **W2** (delete-all) + **W4** (load-more UI) — build on the store + renderer delegation pattern.
4. **W5** (retry) — depends on Q3 resolution.
5. **W6** (filter-badge seam) — depends on Q1; can land last / in parallel with plan 08.

If parallelized anyway, the **convergence files** (`JobsPaneRenderer.ts`, `JobStore.ts`, `jobBucket.ts`, `jobCard.ts`, `jobs-pane.css`) are all **manager-serial-merged** per index mandate 5 — no lane merges them independently.

**Rough size**: ~250-350 LOC TS (renderer handlers + store paging) + ~60-90 LOC CSS + ~300-450 LOC tests for 100% L/B/F. Net medium; the heaviest sub-task is the store paging + its branch coverage.

**In-flight-crew coordination** (mandate 6): no direct overlap with Tiberius full-parity (`704c71b2`) or Rachel's section-toolbar branch — jobs-pane mutation surface is untouched by those. Plan 01's B1 (`4b33ceb7`) does not touch jobs-pane. The only cross-plan seam is **plan 08** (§4 / Q1).

**Doc touchpoints** (mandate 7): update this rnd folder's #9 discrepancy tracker on completion; verify the 5 endpoints are reflected in `src/docs/rest-api-reference.md` (no new router → `/docs` auto-coverage already applies). No INI, no websocket-events, no notification-api changes.
