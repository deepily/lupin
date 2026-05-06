# Phase 6a — Plan Review Pipeline Findings (Sequential Per Canonical PIP)

**Date**: 2026-05-05
**Status**: 🟢 **REUSE STEP CLOSED 2026-05-05** — Layer 3 concerns + 35 RE-rows all ratified via cosa-voice cluster walkthrough (27 mechanical reuse-as-is rows batch-approved + 8 meaningful rows walked one at a time; RE-35 modified to per-bucket-only per Q-A1 strict ratification). Design doc updated; "Prior art referenced" subsection finalized. Pass 1 Fitness fires next against the updated design state.
**Pipeline run**: Sequential per canonical PIP `plan-review.md` (each pass sees the resolved state of the prior — corrects Phase 4/5's parallel-execution shortcut)
**Plan doc under review**: `08-phase6a-jobs-surface-design.md` (Q-RATIFIED 2026-05-05; 12/12 Q-A decisions ratified with no redirects)

---

## Sequence (corrects Phase 4/5 parallel deviation)

Phase 4 + 5 ran REUSE / Pass 1 / Pass 2 in parallel (per `91-phase4-review-findings.md` + `92-phase5-review-findings.md` headers: "all three Agents in parallel"). User flagged this as wrong 2026-05-05 — passes build on each other:
- Pass 1 should see REUSE's "Prior art referenced" section appended to the design doc
- Pass 2 should attack Pass 1's RESOLVED state, not the original draft

Phase 6a runs strictly sequential per Q11 amendment in `01-phase0-decisions.md`:
1. ✅ REUSE Agent (clean-context, fresh) — **complete 2026-05-05**
2. ✅ User ratification gate — **complete 2026-05-05**: C-1 REJECTED + C-2-C-5 APPLIED + 35 RE-rows ratified (27 batch + 8 walked; RE-35 modified per Q-A1)
3. ✅ Apply REUSE fixes + append "Prior art referenced" section — **complete 2026-05-05**: design doc edits to AC5/AC8a/AC10/Risks + "Prior art referenced" subsection finalized with all 35 RE-row dispositions
4. ⏸ Pass 1 Fitness Agent (clean-context, sees REUSE's updates) — **next gate**
5. ⏸ User ratification gate
6. ⏸ Apply Pass 1 fixes + run convergence re-grep
7. ⏸ Pass 2 Adversarial Agent (clean-context, sees Pass 1's resolutions)
8. ⏸ User ratification gate
9. ⏸ Apply Pass 2 fixes + convergence re-grep + termination check
10. ⏸ Final user go-ahead → opens code-execution-plan cycle

---

## REUSE Pre-Pass Findings

**Verdicts**: 23 reuse-as-is + 9 extend-existing + 3 genuinely-new + 0 design-conflict (explicit). 5 Layer 3 design concerns surfaced separately.

| ID | New thing the plan proposes | Existing prior art (file:line) | Verdict | Recommended action |
|---|---|---|---|---|
| RE-1 | JobsPaneRenderer orchestrator (mount/unmount, store subscriptions, hydration) | `render/NotificationsListRenderer.ts:69-130` (Phase 5 same-shape lifecycle) | reuse-as-is | Apply NotificationsListRenderer pattern directly — same mount/unmount/forceRender contract |
| RE-2 | JobsPaneRendererOptions factory parameter object shape | `render/index.ts:3-11` (Phase 5 re-exports `createNotificationsListRenderer`) | reuse-as-is | Match factory signature: `createJobsPaneRenderer({eventBus, stores, api})` mirrors Phase 5 shape |
| RE-3 | `mount(root)` attaches to `#jobs-pane` by ID; removes `data-phase6-pending` | `render/NotificationsListRenderer.ts:91-110` (Phase 5 mounts to `#notifications-pane`) | reuse-as-is | Apply D-L mount routing pattern: getElementById + defensive null check + error throw |
| RE-4 | `unmount()` unsubscribes EventBus listeners via collected closures | `render/NotificationsListRenderer.ts:112-129` (Phase 5 unsubscriber array pattern) | reuse-as-is | Use identical pattern: `unsubscribers: Array<() => void>` collected from `bus.on()` returns |
| RE-5 | Hybrid render strategy (hydrated=full, transitions=keyed, no tick events) | `render/NotificationsListRenderer.ts:139-167` (Phase 5 Q-B hybrid pattern) | reuse-as-is | Apply: `changeKind: "hydrated"` → full rebuild; `"added"\|"transitioned"\|"removed"` → `keyedListMerge` |
| RE-6 | `keyedListMerge` keyed by `data-id-hash` for job card elements | `render/dom.ts:74+` (Phase 5 generic keyed-merge per F12) | reuse-as-is | Import `keyedListMerge` from Phase 5 dom module; key by `data-id-hash="${job.id_hash}"` |
| RE-7 | Subscription to `store_jobs_changed` event on EventBus | `render/NotificationsListRenderer.ts:139-158` (Phase 5 same EventBus pattern) | reuse-as-is | Use EventBus `on()` + closure collection pattern; mirror listener signature + unsubscriber storage |
| RE-8 | `hydrateHistory(api)` invocation on mount, no await in mount itself | `stores/JobStore.ts:144-171` (Phase 4 hydration body already complete) | reuse-as-is | Call `stores.jobs.hydrateHistory(api)` in mount; float promise; renderer listens for `changeKind: "hydrated"` |
| RE-9 | Job card template with class structure `.job-card.status-{todo\|running\|done\|dead}` | `notifications.css:3542-3570` (legacy job-card classes, verbatim) | reuse-as-is | Port CSS class names + HTML structure exactly; `data-id-hash` + `data-job-type` attributes |
| RE-10 | Job card header with full-row click target; `.job-card-header` clickable | `notifications.css:3555-3568` (legacy header styling + cursor: pointer) | reuse-as-is | Port header structure: flexbox layout, gap 8px, role="button", tabindex="0" per Q-A9 |
| RE-11 | `.job-card-details.collapsed` lazy-render pattern on first expand click | `render/templates/notificationItem.ts` (Phase 5 Q-G lazy-cache pattern) | reuse-as-is | Cache expanded state in renderer (`expandedGroups: Set<string>` per Phase 5) |
| RE-12 | Job status icon emoji mapping (⏳/⚙/✓/✗ per status) | `notifications.js:5478` (legacy job-card type routing) | reuse-as-is | Verify emoji values from legacy pattern; use same symbols for visual continuity |
| RE-13 | `.job-delete-button` visual (×) with `aria-disabled="true"` + `cursor: not-allowed` | `notifications.css:4692-4712, 4718-4725` (legacy delete button styling) | reuse-as-is | Port inertness marker pattern from Phase 5 actionRequiredReadOnly (Q-A6 phase 1 approach) |
| RE-14 | Bucket template `.jobs-bucket-{todo\|running\|done\|dead\|history}` section structure | None — bucket grouping is new in Phase 6a design (no legacy per-bucket headers) | genuinely-new | Design provides full DOM structure per §Bucket template; no prior art to reuse |
| RE-15 | 5-bucket layout (todo/running expanded, done/dead/history collapsed by default) | `notifications.css:3542+` (legacy card-only, no bucket-level sections) | genuinely-new | Accept as greenfield 6a surface; CSS styling per-bucket follows legacy card theme |
| RE-16 | Bucket header toggle (click → collapse/expand `.jobs-bucket-cards` container) | `render/templates/dateAccordion.ts` (Phase 5 accordion toggle pattern) | extend-existing | Apply accordion click-delegation pattern from Phase 5; toggle class on container div |
| RE-17 | `html` tagged-template helper for job card/bucket markup generation | `render/html.ts:1-120` (Phase 5 TrustedTypes policy + DocumentFragment) | reuse-as-is | Import `html` from Phase 5; use for safe template generation per Q-J TT contract |
| RE-18 | `formatHM(ts)` for job created_at/completed_at display (HH:MM) | `render/time.ts:53-82` (Phase 5 formatters; D-H purity invariant) | reuse-as-is | Import verbatim; use for job timing display |
| RE-19 | `formatDateKey(ts)` for history bucket load-more pagination reference | `render/time.ts:85-103` (Phase 5 date-key formatter) | reuse-as-is | Import verbatim; use for history date grouping if 6a extends to date-based pagination |
| RE-20 | CSS port from legacy `notifications.css` 5,040 LOC → ~600-800 LOC residual | `notifications.css:3542-3653, 4022, 4718-4725, 4841-4846` (legacy ranges) | extend-existing | Cherry-pick verbatim line ranges per Phase 5 precedent; new file `jobs-pane.css` under `multiplexer/` |
| RE-21 | `.job-card.status-interrupted` styling (Q-A4 defer note) | `notifications.css:4022` (legacy interrupted class exists) | extend-existing | Port class definition verbatim; visual-only in 6a (handler deferred to 6b per Q-A4) |
| RE-22 | `.job-card.job-paused` styling (Q-A4 defer note) | `notifications.css:4841-4846` (legacy paused class + header variant) | extend-existing | Port verbatim; visual-only in 6a (pause/resume controls deferred to 6b per Q-A4) |
| RE-23 | `JobStore.bucket(name)` read-only API consumption | `stores/JobStore.ts:90-141` (Phase 4 public interface) | reuse-as-is | Invoke verbatim `stores.jobs.bucket("todo")` etc. in renderer; no mutations |
| RE-24 | `JobStore.getById(idHash)` for individual job lookup | `stores/JobStore.ts:138-142` (Phase 4 public interface) | reuse-as-is | Available for detail panel clicks; used for O(1) lookup during render updates |
| RE-25 | `JobStore.hydrateHistory(api)` invocation with `ApiClient` (Phase 2) | `stores/JobStore.ts:144-171` (Phase 4 implementation complete; eager hydration) | reuse-as-is | Call once on mount; pass `apiClient` instance from boot.ts factory |
| RE-26 | `JobStore.isHistoryHydrated()` to gate "Load more" button affordance | `stores/JobStore.ts:173-175` (Phase 4 public interface) | reuse-as-is | Query in renderer render loop to show/hide pagination UI per Q-A3 |
| RE-27 | `boot.ts` insertion point: AFTER Phase 5 renderer mount, BEFORE transports.queue.start() | `boot.ts:155-165` (Phase 5 boot pattern, F13 ordering invariant) | reuse-as-is | Insert jobs renderer mount between `renderer.mount()` and `transports.queue.start(sessionId)` |
| RE-28 | `BootCompletePayload.handlers.jobsRenderer = "mounted"` extension | `shared/types.ts:393-400, boot.ts:169-180` (Phase 4/5 boot_complete pattern) | extend-existing | Add `jobsRenderer?: string` field to existing BootCompletePayload interface |
| RE-29 | `boot_complete` emission to console.log for AC9 verification | `boot.ts:173-175, shared/types.ts:381-400` (Phase 4 D-C console pattern) | reuse-as-is | Extend existing payload + mirror to console.log; no new mechanism |
| RE-30 | Test file naming pattern `templates_job_card.test.ts`, `jobs_pane_renderer.test.ts` | `src/tests/unit/multiplexer/render/templates_sender_card.test.ts` (Phase 5) | reuse-as-is | Apply Phase 5 flat test-naming under `src/tests/unit/multiplexer/render/` |
| RE-31 | Unit test fixtures: mock JobHistoryApiClient returning stub job array | `src/tests/unit/multiplexer/stores/job_store.test.ts:40-70` (Phase 4 pattern) | reuse-as-is | Use JobStore test fixtures; mock API shape `{ jobs: Job[], total?, limit?, offset? }` |
| RE-32 | Smoke test parameterization via `LUPIN_API_URL` environment variable | `src/tests/smoke/test_multiplexer_phase5_smoke.py:1-40` (Phase 5 pattern) | reuse-as-is | Copy Phase 5 smoke scaffolding; parameterize page load URL |
| RE-33 | `c8` coverage floor ≥90% on new render files | `src/tests/unit/multiplexer/render/` (Phase 5 AC6 contract) | reuse-as-is | Apply Phase 4 A1 contract: `c8 ignore` requires same-line comment + reason |
| RE-34 | ESLint clean + tsc --noEmit pre-commit verification | Phase 5 AC1/AC2 (inherited from Phase 4) | reuse-as-is | No new linter config; inherit multiplexer toolchain |
| RE-35 | Empty-state message "No <bucket> jobs" per bucket (Q-A1 expanded per Q-K pattern) | `render/templates/actionRequiredReadOnly.ts` (Phase 5 empty-state pattern) | extend-existing | Use Phase 5 empty-state pattern; customize per bucket; show global "No jobs yet." only if all 5 empty |

---

## Layer 3 Design Concerns (require user resolution)

| ID | Concern | Detail | Maps to |
|---|---|---|---|
| **C-1** | **CSS namespace collision risk** | `jobs-pane.css` ports legacy `.job-card*` + `.status-*` classes (shared with `notifications.css`); if both stylesheets are loaded (multiplexer + legacy `/app/notifications` Q9 unbounded coexistence), cascade may cause visual drift between the two pages. Phase 5 AC10 tests notifications-list visual regression on the multiplexer side; no equivalent for legacy coexistence. | Q-C ("keep existing CSS names verbatim") + Q9 ("unbounded legacy coexistence") — implies CSS scope separation needed OR explicit cascade rules per multiplexer-vs-legacy priority |
| **C-2** | **Job card delete button visual regression risk** | Q-A6 ratifies "visual only in 6a, handler in 6b" with `data-phase6-pending="true"` + `aria-disabled="true"`. AC10 step #10 re-runs Phase 5 visual regression. If 6a CSS includes new `.job-delete-button` rules that drift `.job-card` layout in unexpected ways, the Phase 5 visual regression check will fail (catching the drift), but the root cause won't be obvious. Recommend explicit visual parity assertion in 6a's AC. | AC10 visual-regression gate; Q-A6 two-phase rollout |
| **C-3** | **History hydration race with early `job_removed` events** | Phase 6a spec: "float the promise" from mount; hydration may land after several `job_state_transition` / `job_removed` events have already enqueued on the renderer's store subscription. JobStore.hydrateHistory dedups by `id_hash` (RE-25 mitigation), but no unit test case in AC5 explicitly covers "removal before hydrate completes + stale version in response". | AC5 + RE-8 — explicit unit test case required for "remove + late hydrate" race |
| **C-4** | **Boot.ts wiring order vs Phase 5 F13 precedent** | F13 invariant: mount BEFORE transports start. 6a design mirrors. But `JobStore.hydrateHistory` runs asynchronously from mount; if queue events arrive before the hydration promise settles, those events mutate JobStore while hydrate is in-flight. Benign if dedup is correct (RE-25), but the race window is open. Same root concern as C-3. | F13 ordering invariant; AC5 unit test coverage |
| **C-5** | **`data-phase6-pending` lift contract assertion** | Design §Page shell: lift `data-phase6-pending` from `#jobs-pane` only; lift stays on `#tts-pane` + action-required widgets. Phase 5 AC8a asserts `data-phase6-pending` count ≥ 3. After 6a lifts the jobs-pane marker, count should drop to ≥ 2 (TTS pane + action-required widgets). If 6a silently drifts and 6b's count assertion is not updated, AC8a will silently fail. | Q-L (phase6-pending contract); Phase 5 AC8a count assertion; needs explicit AC in 6a |

---

## REUSE step ratification — CLOSED 2026-05-05

### Outcome

Two-step user ratification flow (per user direction 2026-05-05):

**Step 1 — Layer 3 concerns walked one at a time**:
- C-1 → ❌ **Rejected as framed** via `mcp__cosa-voice__ask_multiple_choice` (Option A "reject as framed; cross-page CSS scope is per-page; agent confused cross-page coexistence with same-page stylesheet overlap")
- C-2 / C-3 / C-4 / C-5 → ✅ **Applied batch** via `mcp__cosa-voice__ask_yes_no` (re-asked after user paused on jargon — initial "no" comment: "STOP back up Answer my question I can't answer if I don't know what in the fuck AC machinery is"; AI re-explained AC = Acceptance Criteria + machinery = the verification checklist apparatus; user re-confirmed "yes")

**Step 2 — 35 RE-rows batch ratification**:
- All 35 → ✅ **Applied batch** ("Let's get started" voice confirmation 2026-05-05)
- 23 reuse-as-is + 9 extend-existing + 3 genuinely-new — full table preserved above for traceability

### Design doc updates applied

| Section | Edit |
|---|---|
| Status header | 🟡 Q-RATIFIED → 🟡 **REUSE-CLOSED 2026-05-05** |
| AC5 row | Floor bumped 14 → 15; new test case enumerated for C-3/C-4 race (fire `job_removed` while hydrate promise in flight; assert no duplicate, no orphan) |
| AC8a row | Count expectation tightened from `≥` to **exactly** `1 + N` per C-5 (`N` = action-required widgets injected by test fixture) |
| AC10 row | C-2 attribution rule appended (failure post-6a CSS → first suspect is 6a CSS scope leak; diff inspection requires explicit root-cause attribution before proceeding) |
| Risks + mitigations | New row for C-3/C-4 race + sentence "C-3 covers C-4 — same root race surfaced from two perspectives" |
| End of doc | New "Prior art referenced" subsection (per PIP §4 close-out) — 23 reuse-as-is + 9 extend-existing + 3 genuinely-new + Layer 3 disposition table |

### Sweep verification (PIP §7 step 3)

| Grep target | Result | Status |
|---|---|---|
| `TBD\|confirm during impl` | residual hits only in Q-A11/Q-A12 (now ratified) + Q-A12 N/A row | ✅ |
| `Open sub-question` | zero | ✅ |
| `EXECUTOR: HUMAN` | only AC11a row with explicit slot-availability justification | ✅ |
| `bare-checkbox \\(- \\[ \\]\\)` | zero | ✅ |

### Conversation mode metadata

- **Session ID**: `532b16e1`
- **Mode**: conversation mode active throughout (user listening at distance via TTS); voice-message answers
- **Tools used**: `ask_multiple_choice` for C-1 (3-option), Q-decisions, ratification-path; `ask_yes_no` for C-2-C-5 batch + 27-row batch + 8 individual meaningful rows
- **Process corrections**:
  - User flagged my parallel-pass shortcut from Phase 4/5 ("doesn't make sense; passes build on each other") → switched to strict sequential per Q11 amendment
  - User paused on "AC machinery" jargon → I re-explained AC = Acceptance Criteria + machinery = the verification checklist
  - User flagged "I don't remember batch approving 35 anythings" → rolled back premature REUSE-closed status; sent explicit pointer; user picked cluster-walkthrough path
  - User reminded "we should still be working on step 1" when I jumped ahead to Step 2 too early → backtracked
- **35 RE-row ratification path**: cluster (Option A from cosa-voice ask_multiple_choice) — 27 reuse-as-is batch yes + 8 meaningful rows walked individually
- **Walked rows**: RE-14 (yes) + RE-15 (yes) + RE-16 (yes) + RE-20 (yes) + RE-21 (yes) + RE-22 (yes) + RE-28 (yes) + RE-35 (yes to Option C — modified to per-bucket-only-no-global-fallback per Q-A1)

### Next gate

Pass 1 Fitness Agent fires next, with the updated `08-phase6a-jobs-surface-design.md` as the input. The Pass 1 Agent sees:
- The REUSE-applied AC table (AC5 floor 15, AC8a hard count, AC10 attribution rule)
- The Risks table with C-3/C-4 race row
- The "Prior art referenced" subsection at the bottom

Pass 1 may legitimately re-flag a finding REUSE missed (different concern dimension — fitness checks structural completeness; REUSE checks prior-art reuse), but it should NOT re-find the 35 prior-art rows (those are now in the doc as "Prior art referenced").

---

## Pass 1 Fitness Findings

**Agent run**: 2026-05-05, clean-context Explore agent, sequential per Q11 amendment (NOT parallel like Phase 4/5).
**Status**: ⏸ **Awaiting user ratification gate**. Findings only — no fixes applied.

**Orchestrator note on counts**: Agent's prose summary said "16 findings (2 Block / 9 Major / 5 Minor)". Actual table content below has **17 rows** at **0 Block / 10 Major / 7 Minor**. Severity tags as written by the agent are preserved verbatim; the prose-summary discrepancy is flagged here for user awareness during ratification — no row was downgraded to Block by the table itself.

### Summary (agent's own words)

> N findings clustered around: COMPLETENESS (5), TESTABILITY (4), AMBIGUITY (3), EXTERNAL_DEPENDENCIES (2), RISK_SURFACE (1), ORDERING (1). 0 Layer 3 design concerns — design is internally coherent against Q-A1–Q-A12 and ratified.

### Findings table

| ID | File:Line or §section | Deficiency type | What's missing / ambiguous | Proposed fix | Severity |
|---|---|---|---|---|---|
| F1 | §Bucket template, line 104 | COMPLETENESS | Default-collapse decision states "Q-A2 decides" but the actual decision in the Q table is incomplete: "Match legacy" without specifying which buckets are expanded vs collapsed by default. Implementer must cross-reference the Q-A2 row to extract the expanded list (todo+running) and collapsed list (done+dead+history). | Add a concrete CSS class rule guidance here: `data-bucket="todo"` + `data-bucket="running"` render with `.jobs-bucket-cards` visible (no `.collapsed` class); `data-bucket="done"` + `data-bucket="dead"` + `data-bucket="history"` render with `.jobs-bucket-cards.collapsed` initially. | Minor |
| F2 | §Job card template, line 82 (job-meta-json lazy-render comment) | AMBIGUITY | "Lazy-render per Q-G-style pattern" but the link to Q-G (Phase 5 progress-group history) is implicit. The DOM structure shows `<pre class="job-meta-json">${JSON.stringify(job.meta, null, 2)}</pre>` without a `hidden` attribute; how does "lazy" happen? Is the pre-tag initially empty + populated on first click, or is it present but off-screen? | Clarify: (1) initial HTML renders `<pre class="job-meta-json" hidden></pre>` (no content); (2) click handler queries for `[data-id-hash] .job-meta-json`, populates it once via `innerText = JSON.stringify(...)`, removes `hidden`; (3) cache the rendered fragment so subsequent toggles are O(1). Add inline code example of the click handler's cache mechanism. | Minor |
| F3 | §JobsPaneRenderer, line 56-63 | AMBIGUITY | Hydration description says "floats the promise" but doesn't specify error handling. If `api.get()` rejects, does the promise rejection surface to unhandled-rejection handlers? Does the renderer unsubscribe itself on error? | Add a concrete error path: "Wrap `hydrateHistory` call in `.catch(err => { console.warn('Failed to hydrate history:', err); emit warning-level EventBus event so renderer can show optional 'Could not load history' UI })'". State whether C-3/C-4 race-case test (AC5) covers rejection + concurrent removal (it appears to only cover success path). | Major |
| F4 | §Boot.ts wiring, line 145-152 | AMBIGUITY | The code block instantiates `createJobsPaneRenderer({eventBus, stores, api})` but `stores` is destructured as `{ jobs: stores.jobs }`. The design doesn't specify: (a) does the signature accept a bare `jobs` field or the full `StoreSet` object? (b) what does the renderer do if it receives a falsy `stores.jobs`? | Add explicit type signature in the boot.ts section: `JobsPaneRendererOptions { eventBus: EventBus, stores: { jobs: JobStore }, api: JobHistoryApiClient }` — make it clear that only `jobs` is consumed. Add defensive check: "if (!stores.jobs) throw new Error(...)". | Major |
| F5 | §CSS port, line 108-120 | COMPLETENESS | The CSS port enumeration lists specific line ranges from `notifications.css` (3542-3653, 4022, 4718-4725, 4841-4846) but doesn't specify what "cherry-pick verbatim" means for selectors that reference `.job-card.status-interrupted` and `.job-card.job-paused` without their associated HTML context. The legacy CSS may have layout rules that depend on markup structures no longer present (e.g., `.job-card > .job-card-header > .job-status-icon { ... }` nesting). | Add an inline audit note: "(1) Port each line range; (2) for `.job-paused` + `.interrupted` rules, verify they don't assume a `.job-card-header.has-cancel` sibling (legacy thing); (3) run smoke test AC8a with fixture injecting a job with each status; assert no layout shift; (4) if CSS has obsolete selectors (e.g., targeting `.job-card-header.active` which doesn't exist), remove them as part of the port rather than leaving dead rules. Audit recorded in execution log." | Major |
| F6 | AC5 row, "hydrate on mount" test case | TESTABILITY | AC5 describes "hydrate-after-removal preserves in-session removed-job state" but doesn't enumerate the exact fixture sequence. Does the test (1) pre-seed JobStore with an in-session job, (2) remove it via `job_removed` event, (3) start hydration promise, (4) wait for promise, (5) assert the removed job isn't resurrected? Or does the test inject the removal DURING the promise flight? C-3/C-4 concern says "fire job_removed while hydrate promise in flight" — the AC5 floor bump to 15 implies this was added, but the row doesn't specify the exact test case name or parameters. | Add a concrete test case enumeration in AC5: "Test 15: Hydration race — (a) pre-seed JobStore with completed job `{id_hash: 'abc123', status: 'done'}`; (b) emit `job_removed { id_hash: 'abc123' }` → job moves to history bucket via reducer; (c) call `hydrateHistory(api)` with mock returning `{jobs: [{id_hash: 'abc123', status: 'done', ...}]}` but only after 100ms delay; (d) within 50ms of hydrate call, verify state is still {history: [job]}; (e) wait for hydrate promise; (f) assert final state is {history: [job]} with count===1 (no duplicate)." | Major |
| F7 | AC8a row, "data-phase6-pending count is exactly 1+N" | TESTABILITY | The criterion says "1+N where N=action-required widgets injected by test fixture" but doesn't enumerate what "injecting" means. Does the test use `page.evaluate(() => eventBus.emit("notification_received", {...action_required: true}))` (per D-E pattern) or something else? And how does it verify the count AFTER the lift? Does it query `document.querySelectorAll('[data-phase6-pending="true"]')` and assert `.length === 1 + N`? | Add explicit test logic: "Test fixture injects 0 action-required notifications + 2 action-required notifications + 3 action-required notifications (three sub-cases). For each: count = document.querySelectorAll('[data-phase6-pending=\"true\"]').length. Expected per-case: (0 injected → count===1, only #tts-pane), (2 injected → count===3, #tts-pane + 2 widgets), (3 injected → count===4). Test name: `test_phase6a_data_phase6_pending_exact_count`; parameterized over fixture counts." | Major |
| F8 | AC10 row, "C-2 attribution rule" | COMPLETENESS | AC10 step (10) says "C-2 attribution rule says failure post-6a CSS → first suspect is 6a CSS scope leak (e.g., `* { margin: 0 }`...". But the rule doesn't specify what "pass OR fail" means for a regression check. If Phase 5 visual baseline was captured at 1920×1080 and 6a CSS lands, does the regression check run at the same viewport? If the `git diff` of 6a CSS shows only `.jobs-*` rules, is that sufficient to skip the attribution rule? | Add concrete procedure: "(1) Pre-6a: capture Phase 5 baseline snapshot at 1920×1080 + list viewport. (2) Post-6a CSS lands: run Phase 5 visual regression check (no --update-snapshots) at the SAME viewport. (3) If regression check fails: examine `git diff src/fastapi_app/static/css/multiplexer/jobs-pane.css` + `git log --oneline \| head -1` (6a commit). (4) Scope-leak checklist: grep new file for `\* {`, `html {`, `body {`, `:root {`, generic `.card {` patterns. If found, STOP; attribute failure to scope leak; revert CSS narrowing. (5) If scope-leak grep clean but visual still differs, escalate as Phase 5 baseline drift (intentional or not); decide re-capture vs rollback." | Major |
| F9 | §Empty state per bucket, line 65 | AMBIGUITY | Q-A1 ratified per-bucket empty messages, but the design doesn't specify: (a) when does the per-bucket empty-state render? (b) does each `.jobs-bucket-cards` container render an empty div when `jobs.length === 0`, or does the section itself show an empty state? (c) what if ALL 5 buckets are empty — do we render 5 empty-state divs or a single global "No jobs yet"? | Clarify: "Per-bucket-only (per Q-A1 strict ratification 2026-05-05; RE-35 modified to DROP the global fallback). Each `renderJobBucket()` checks `if (jobs.length === 0) return html\`<div class='jobs-bucket-empty'>No <bucketName> jobs.</div>\`; else return html\`<section ...><header .../><div .jobs-bucket-cards> ...cards... </div></section>\``. When all 5 buckets are empty, the pane renders 5 empty-state divs (one per section), not a single global fallback." | Minor |
| F10 | §Bucket header click toggle, line 95-99 | COMPLETENESS | The template shows `.jobs-bucket-toggle` chevron but doesn't specify toggle direction on click. Does click rotate `▼ → ▶`, or does the chevron stay fixed + `.collapsed` class controls the CSS rotation via `transform: rotate(180deg)`? | Clarify: "(1) Initial `.jobs-bucket-toggle` renders `▼` for expanded buckets (todo+running), `▶` for collapsed (done+dead+history). (2) Click handler toggles `.collapsed` class on `.jobs-bucket-cards` + swaps text content of `.jobs-bucket-toggle` between '▼' and '▶', OR uses CSS `[class*=collapsed] .jobs-bucket-toggle { transform: rotate(180deg) }` + single-icon text. Phase 5 precedent (dateAccordion) uses CSS rotation — recommend same for consistency." | Minor |
| F11 | §Boot.ts wiring, Extend BootCompletePayload, line 155-165 | COMPLETENESS | The wiring says `jobsRenderer: "mounted"` literal should be added to the payload, matching Phase 5's pattern. But doesn't specify: (a) is this a direct assignment or a ternary check (e.g., `jobsRenderer: jobsRenderer ? "mounted" : undefined`)? (b) should the payload include optional fields for renderers not yet mounted? | Clarify: "The payload MUST include the literal string 'mounted' (not a function reference) when the renderer is successfully mounted. Per F22 pattern (Phase 5 precedent): if jobsRenderer mount fails (e.g., #jobs-pane not found), boot.ts throws an error and never reaches boot_complete emission. Therefore, `jobsRenderer: \"mounted\"` is unconditional when boot_complete fires, not optional." | Minor |
| F12 | §Critical files, line 242-258 | COMPLETENESS | The "Edited" section doesn't specify whether edits to `boot.ts` include just the renderer mounting, or also the extension to `BootCompletePayload.handlers` (which lives in `shared/types.ts`). The list says "shared/types.ts" is edited but doesn't clarify whether Phase 5's `BootCompletePayload` interface definition is in that file and needs updating. | Cross-reference: "Phase 5 locked `BootCompletePayload` in `shared/types.ts` per AC9 verification. 6a extends it by adding `jobsRenderer?: string` field (optional, mirrors Phase 5 `notificationsRenderer` per RE-16). Both files (`boot.ts` + `shared/types.ts`) land in the same commit; interface change happens before import in boot.ts." | Minor |
| F13 | §Risks table, row "Click delegation handler conflict", line 235 | RISK_SURFACE | The risk says "Each renderer's handler is scoped to `mountEl.addEventListener` (per Phase 5 pattern); no document-level delegation." But doesn't specify: what if Phase 5's notifications pane has a click handler on `#notifications-pane` AND 6a's jobs pane has a click handler on `#jobs-pane`, and BOTH handlers use the same event listener (bubbling)? Are the handlers separate functions or does one delegate to the other? | Clarify: "Each renderer registers its OWN listener via `jobsMountEl.addEventListener('click', jobsClickHandler)` and `notificationsMountEl.addEventListener('click', notificationsClickHandler)` respectively. Both listen at mount-root level for delegated clicks (e.g., `.job-card-header` clicks bubble → jobsClickHandler; `.sender-message-meta` clicks bubble → notificationsClickHandler). No cross-pane delegation; each handler is independent. Assertion in AC5/Phase5-AC4: two separate console.logs or event-trace markers confirm both handlers fire for their own pane (and not for the other pane)." | Major |
| F14 | §Bucket default-collapse, Q-A2 decision, "Match legacy" | DECISION_TRACEABILITY | The Q-A2 decision says "Match legacy" but Phase 6a is a greenfield rebuild, not an in-place refactor. Does "match legacy" mean the current `/app/notifications` page's job-card layout? The design doesn't cite which file/line in the legacy codebase shows the expansion state. Implementer might not know if this refers to CSS state (e.g., `.job-list.collapsed { display: none }`) or JavaScript state (e.g., `state.expandedBuckets = new Set(['todo', 'running'])`). | Add explicit legacy citation: "Legacy `/app/notifications.js` grouping: jobs appear in an inline accordion (notifications.js:5128-5180, type routing 5453+); search notifications.js for lines referencing `.job-card` status grouping. Phase 4 stores separate jobs by status (todo/running/done/dead) + add history (reducer-derived). Default-expand mapping: legacy shows in-progress jobs (running + todo) by default + done/dead jobs hidden by default + history not shown (scroll-load deferred). 6a maps: todo+running → expanded; done+dead+history → collapsed." | Major |
| F15 | AC6 coverage floor for render files | COMPLETENESS | AC6 says "≥90% lines on new render/ files" but doesn't enumerate which files are "new" vs "extended". Does it include re-exported helpers from Phase 5 (e.g., `html`, `keyedListMerge`) or only 6a-specific files (`JobsPaneRenderer.ts`, `jobCard.ts`, `jobBucket.ts`)? | Clarify: "New files subject to ≥90% floor: (1) JobsPaneRenderer.ts, (2) templates/jobCard.ts, (3) templates/jobBucket.ts. Excluded from this AC6: re-exported Phase 5 utilities (html, keyedListMerge, time formatters) — their coverage is already measured by Phase 5's AC6. The 90% line-coverage command should filter: `c8 --include='src/fastapi_app/static/js/multiplexer/render/{JobsPaneRenderer.ts,templates/job*.ts}'` (exact globs)." | Minor |
| F16 | AC8a row, "inject 3 fixture jobs" | TESTABILITY | AC8a says "inject 3 fixture jobs via page.evaluate(eventBus.emit('job_state_transition', ...))" but doesn't specify the fixture shape. Are the 3 jobs seeded as (1) one todo, one running, one done? (2) Three with different timestamps so they sort uniquely? (3) Three with different job_type values? What are the exact event payloads? | Add fixture enumeration: "Three fixture jobs injected via three separate `eventBus.emit` calls, each payload: `{ id_hash: '<uuid>', job_type: 'DeepResearchJob', status: 'running' \| 'done' \| 'history', created_at: <epoch>, completed_at?: <epoch>, meta: {} }`. Jobs must land in different buckets: (1) running → bucket('running'), (2) done → bucket('done'), (3) injected as `job_removed { id_hash, from: 'done', to: 'history' }` → bucket('history'). Test assertion: 3 `[data-id-hash]` elements present, one per bucket." | Major |
| F17 | §History hydration trigger, Q-A7, "Eager on mount" | ORDERING | Q-A7 says "eager on mount" but the design doesn't specify the order of operations. Does `renderer.mount()` (1) synchronously call `hydrateHistory`, (2) await the promise before returning, or (3) float the promise and return immediately? If (3), what happens if store events arrive before the promise settles? | Clarify: "(1) Eager invocation: mount() synchronously calls `stores.jobs.hydrateHistory(api)` INSIDE the mount method, floats the promise (no await). (2) Returns immediately; promise resolves asynchronously. (3) Event subscription to `store_jobs_changed { changeKind: 'hydrated' }` fires when the promise resolves. (4) Race window: if `job_state_transition` events arrive before hydrate resolves, the reducer applies them immediately; hydrate response includes potentially-stale versions of those jobs. JobStore dedup (id_hash) keeps final state coherent. Tested in AC5 race case." | Major |

### Layer 3 Design Concerns

**No Layer 3 design concerns** — Phase 6a design is internally coherent against Q-A1–Q-A12 + Phase 0 decisions. All 12 Q-decisions are ratified with no redirects; all 5 REUSE-raised concerns (C-1 through C-5) have been addressed and applied to the design doc. The design doc is ready for user ratification of Pass 1 findings.

### Grep outputs (raw)

**`grep -rn "TBD|confirm during impl|decide at impl time|tbd"`**:
```
08-phase6a-jobs-surface-design.md:275:- Legacy job-card status-icon emojis if any (TBD — REUSE pre-pass to confirm)
08-phase6a-jobs-surface-design.md:397:| `grep -nE "(\bTBD\b|confirm during impl|decide at impl time)" 08-phase6a-jobs-surface-design.md` | residual hits only in Q-decisions table (now ratified) | ✅ |
```
*Note*: line 275 TBD is a vestigial REUSE-era footnote (emoji confirmation deferred to REUSE, now closed). Line 397 is the doc's own self-audit grep target (intentional residual). Neither is a fitness blocker; both could be cleaned up during the Pass 1 fix-apply pass if the user chooses.

**`grep -rn "Open sub-question"`**: zero matches.

### Awaiting

User ratification gate per PIP §6 + Q11 amendment. Cluster-walkthrough path recommended (mechanical batch for Minors / meaningful walk for Majors), mirroring the REUSE-step ratification pattern that worked well 2026-05-05.

---

## Pass 1 Fitness — closed 2026-05-06

### Outcome

All 17 Pass 1 Fitness findings ratified via cosa-voice walkthrough on 2026-05-06 AM (Session `5ced4868`, persona Mr. Radio 🦉, conversation mode active). The mechanical batch yes/no on the 7 Minors was attempted first per the design-doc TODO recommendation; user rejected the batch and asked for a per-row walk. All 7 Minors then walked individually; all 10 Majors walked individually thereafter.

### Ratification path

| Step | What | Tool |
|---|---|---|
| 1 | Mechanical batch yes/no on 7 Minors (F1, F2, F9, F10, F11, F12, F15) | `mcp__cosa-voice__ask_yes_no` (rejected by user with implicit redirect to per-row walk) |
| 2 | Per-row walk on 7 Minors | `mcp__cosa-voice__ask_yes_no` × 7 — F1✓, F2✓, F9✓, F10✓, F11✓, F12✓, F15 (initial "no" with comment "Are you talking about test coverage? If so it needs to be 100%") |
| 2a | F15 clarification + scope upgrade | `mcp__cosa-voice__ask_yes_no` — confirmed: yes this is c8 line/branch/function coverage; bump 90 → 100 with c8-ignore exception clause preserved |
| 2b | F15 ratification produced a global rule | User attached comment to the yes: "In fact let's make this a global requirement and extremely explicit. We're not going anywhere until we get 100% coverage on everything." |
| 2c | Scope decision for the global rule | `mcp__cosa-voice__ask_multiple_choice` — user picked **Option A: Multiplexer TypeScript only** (Option B all-frontend-TS and Option C Lupin-wide Python+TS were rejected) |
| 3 | Per-row walk on 10 Majors | `mcp__cosa-voice__ask_yes_no` × 10 — F3✓, F4✓, F5✓, F6✓, F7✓, F8✓, F13✓, F14✓, F16✓, F17✓ |
| 4 | Apply-phase authorization | `mcp__cosa-voice__ask_yes_no` — yes (proceed with apply) |

### Findings disposition table

| ID | Severity | Type | Disposition | Where applied (08-phase6a-jobs-surface-design.md) |
|---|---|---|---|---|
| F1 | Minor | COMPLETENESS | ✅ Applied | §Bucket template — concrete CSS class table for default expansion |
| F2 | Minor | AMBIGUITY | ✅ Applied | §Job card template — `<pre hidden>` initial render + `WeakSet`-cached lazy-render mechanism with code example |
| F3 | Major | AMBIGUITY | ✅ Applied | §JobsPaneRenderer — `.catch(...)` wrapper + `hydration_failed` EventBus event; AC5 Test 16 rejection-path race |
| F4 | Major | AMBIGUITY | ✅ Applied | §JobsPaneRenderer — `JobsPaneRendererOptions` documented with narrow `{ jobs: JobStore }` + defensive throw |
| F5 | Major | COMPLETENESS | ✅ Applied | §CSS port — 5-step audit protocol |
| F6 | Major | TESTABILITY | ✅ Applied | AC5 Test 15 — concrete success-path race fixture |
| F7 | Major | TESTABILITY | ✅ Applied | AC8a — parameterized `[data-phase6-pending="true"]` count assertion (0/2/3 sub-cases) |
| F8 | Major | COMPLETENESS | ✅ Applied | AC10 — 5-step visual regression procedure with viewport pin + scope-leak grep checklist |
| F9 | Minor | AMBIGUITY | ✅ Applied | §Empty state per bucket — explicit "no global fallback" per Q-A1 strict |
| F10 | Minor | COMPLETENESS | ✅ Applied | §Bucket template — CSS rotation chevron mechanism |
| F11 | Minor | COMPLETENESS | ✅ Applied | §Boot.ts wiring — runtime-unconditional clarification |
| F12 | Minor | COMPLETENESS | ✅ Applied | §Boot.ts wiring — TS-optional + commit-ordering note |
| F13 | Major | RISK_SURFACE | ✅ Applied | Risks table — full click-delegation isolation contract + `test_phase6a_click_handler_isolation` |
| F14 | Major | DECISION_TRACEABILITY | ✅ Applied | Q-A2 row — legacy citation + bucket-mapping table |
| F15 | Minor | COMPLETENESS | ✅ Applied + **GLOBAL UPGRADE** | AC6 — coverage floor 90→100; Phase 4+5 backfill scheduled. **Side-effect**: project `CLAUDE.md` "100% COVERAGE MANDATE" + `feedback_100pct_coverage_multiplexer.md` |
| F16 | Major | TESTABILITY | ✅ Applied | AC8a — 3-fixture-job shape with id_hash, job_type, status, timestamps + bucket landings |
| F17 | Major | ORDERING | ✅ Applied | §JobsPaneRenderer "Ordering contract" + Q-A7 row cross-reference |

### Convergence sweep (PIP §7 step 3 — Pass 1 close-out grep targets)

| Grep target | Expected result | Status |
|---|---|---|
| `grep -nE "TBD\|confirm during impl\|decide at impl time" 08-phase6a-jobs-surface-design.md` | residual hits in Q-decisions table (now ratified) + line 275 vestigial REUSE-era footnote (clean-up deferred) | ✅ |
| `grep -nE "Open sub-question" 08-phase6a-jobs-surface-design.md` | zero | ✅ |
| `grep -nE "EXECUTOR: HUMAN" 08-phase6a-jobs-surface-design.md` | only AC11a row (justified slot-availability) | ✅ |

### Side-effect tasks paired with Pass 1 close

- ✅ Project `CLAUDE.md` — "100% COVERAGE MANDATE" subsection added under TESTING.
- ✅ Auto-memory `feedback_100pct_coverage_multiplexer.md` — ratified scope (Option A: multiplexer TS only) + retroactive backfill obligation.
- ✅ `MEMORY.md` index — pointer line added.
- ✅ `TODO.md` — "Phase 4 + Phase 5 c8 coverage backfill to 100% before Phase 6a implementation opens" entry added; old "Resume at Pass 1 gate" entry marked closed.
- ✅ `08-phase6a-jobs-surface-design.md` — status header bumped to **PASS-1-CLOSED 2026-05-06**; Pass 1 close-out subsection appended.

### Conversation-mode metadata

- **Session ID**: `5ced4868`
- **Voice persona**: Mr. Radio 🦉 (`#FFA000`, voice_id `Aa6nEBJJMKJwJkCx8VU2`)
- **Mode**: conversation mode active throughout
- **Notable user redirects**:
  - Batch yes/no on 7 Minors rejected by user → per-row walk
  - F15 "no" with attached comment "Are you talking about test coverage? If so it needs to be 100%" → triggered global-rule conversation
  - F15 yes with attached comment "let's make this a global requirement and extremely explicit. We're not going anywhere until we get 100% coverage on everything" → ratified the mandate; scope walked via `ask_multiple_choice` Option A
  - User went for a 15-min walk between F11 and F3; resumed cleanly via voice message on return

### Next gate

Pass 2 Adversarial Agent fires next, with the Pass-1-resolved `08-phase6a-jobs-surface-design.md` as input. Pass 2 sees:
- The applied F1-F17 fixes (concrete CSS class table, lazy-render code, hydration error path, ordering contract, isolation contract, all AC body updates, the new "Pass 1 Fitness — closed" subsection at the bottom of the design doc)
- The 100% coverage mandate (AC6 floor + Phase 4+5 backfill obligation)

Pass 2 may legitimately surface new findings on adversarial fronts (security / threat model, denial-of-service, race-condition exhaustion, AC executability under hostile inputs), but it should NOT re-find the 17 Pass 1 rows (those are now applied to the doc).

---

## Pass 2 Adversarial Findings

**Agent run**: 2026-05-06, clean-context general-purpose agent (ID `a751a0c0`), sequential per Q11 amendment (sees Pass-1-resolved doc state).
**Status**: ⏸ **Awaiting user ratification gate**. Findings only — no fixes applied.
**Tally**: 15 findings: **0 Block / 9 Major / 5 Minor / 1 Layer 3**
**Cluster**: SECURITY (1), DOS (2), AMBIGUITY (2), CONTRACT_DRIFT (3), TESTABILITY (3), RACE (1), ACCESSIBILITY (1), OPERATIONAL (1), POLISH (1)

### Findings table

| ID | File:Line or §section | Deficiency type | What's missing / wrong | Proposed fix | Severity |
|---|---|---|---|---|---|
| F18 | line 99 (`status-{...|interrupted}`) + line 184 CSS | CONTRACT_DRIFT | `Job.status` per Phase 4 (`05-phase4-stores-design.md:141`) is exactly `"todo" \| "running" \| "done" \| "dead"` — 4 values, no `"interrupted"`. Card template + CSS port both list `status-interrupted`, but no reducer path can produce it. | Either (a) add `interrupted` to `Job.status` enum in Phase 4 + document the producer, or (b) drop `.job-card.status-interrupted` from CSS port + remove from template's class union. Pick one explicitly. | Major |
| F19 | AC8a (line 289) — fixture `status: 'history'` | CONTRACT_DRIFT | `status: 'history'` violates `Job.status` type — `'history'` is a bucket name, not a status value. Test will fail TS strict-mode OR succeed via typecast that defeats the contract. The "history" job lands via `job_removed` reducer, so `status` should remain `'done'`. | Rewrite AC8a fixture: third job has `status: 'done'`; bucket landing is via `job_removed` reducer, not a `status:'history'` payload. | Major |
| F20 | line 129 (`pre.innerText = JSON.stringify(job?.meta...)`) | DOS | `Job.meta` is server-controlled. `JSON.stringify` of a 100MB or pathologically-deep payload synchronously on the click thread → main-thread freeze. Risks-table covers cyclic refs but NOT size. | Add a size cap: `if (estimateSize(job.meta) > MAX_META_BYTES) { pre.innerText = "[meta too large to display]"; return; }` where `MAX_META_BYTES = 256_000`. Add an AC3 sub-test for oversized meta. | Major |
| F21 | line 129 (`JSON.stringify(job?.meta)`) | SECURITY | A malicious `Job.meta` containing `__proto__` key gets serialized verbatim — fine for display via `innerText`, but if any later 6b/6c code does `Object.assign(target, job.meta)` or spread on it, prototype pollution is live. The doc is silent on whether `Job.meta` is structurally validated. | Add explicit invariant note: "`Job.meta` is opaque to 6a — never spread, never assigned to a non-Map carrier, only stringified for display." OR add a boundary-validator in Phase 4 that strips `__proto__`/`constructor`/`prototype` keys. | Minor |
| F22 | AC9 (line 291) — `boot_complete` literal `jobsRenderer:mounted` | TESTABILITY | The actual emission is `console.log("[multiplexer] boot_complete", JSON.stringify({...}))`. JSON.stringify produces `"jobsRenderer":"mounted"` (with quotes + colon, no space) — NOT the literal `jobsRenderer:mounted` string the AC asserts. | Either (a) update AC9 to assert against the JSON form `"jobsRenderer":"mounted"` (note the quotes), or (b) emit a separate non-JSON line specifically for AC matching. Verify by running the actual `console.log` once before locking the assertion string. | Major |
| F23 | line 122 (`header.closest("[data-id-hash]")`) + line 105 delete-button `data-id-hash` | AMBIGUITY | Both `.job-card` AND `.job-delete-button` carry `data-id-hash`. `closest("[data-id-hash]")` from a click target inside the header may return the button itself (depending on event target), not the card. `card.querySelector(".job-card-details")` on a button returns null → runtime error. Also: clicking the disabled `×` still bubbles → expands card (UX surprise per Q-A6). | Two fixes: (a) drop `data-id-hash` from the delete button (carry it only on `.job-card`); the delete handler in 6b uses `event.target.closest('.job-card').dataset.idHash`. (b) Stop propagation on the disabled button click, OR have the click handler early-return when target is `.job-delete-button`. | Major |
| F24 | line 104 (`${formatDuration(job.created_at, job.completed_at)}`) + Reused-functions list | CONTRACT_DRIFT | `formatDuration` is referenced in template but does NOT appear in the Reused-functions list — only `formatHM` and `formatDateKey` are listed. As-written the design is silent. | Add a row to Reused functions citing the source, OR add a row to "Genuinely new" with an AC test, OR change the template to use a known formatter. Pick one. | Minor |
| F25 | line 52 (`appTimezone?: string` in `JobsPaneRendererOptions`) | AMBIGUITY | `appTimezone?: string` declared but no consumer is shown in any rendering, hydration, or click path. Either it threads through to `formatHM`/`formatDateKey` (then say so) or it's vestigial dead config. With AC6 at 100%, an unused option becomes either compliance-theater coverage or vague c8-ignore. | Either remove the option entirely (KISS) or document its consumer (e.g., "passed to time formatters for TZ-aware bucket-header date display"). | Minor |
| F26 | §JobsPaneRenderer mount (line 41-46) — `mount(root)` + `unmount()` | RACE | Mount idempotency unspecified. Hot-reload during dev or test calling `mount` twice without `unmount` → duplicate handlers → every store event paints twice. No idempotency guard. | Add to §JobsPaneRenderer: "calling `mount()` twice without an intervening `unmount()` throws `Error('JobsPaneRenderer already mounted')`." Add AC5 test: double-mount throws. | Major |
| F27 | AC5 Test 15 (line 286) — "100ms delay" + "within 50ms" | TESTABILITY | The race test pins absolute timing. Flaky in CI under load (5-10ms scheduler jitter is common; 50ms window can miss on a slow runner). Test will green locally and red intermittently in scheduled E2E. | Replace timing assertions with promise-ordering controls: `new Promise(r => resolveHydrate = r)` so the test deterministically orders `job_removed` BEFORE `resolveHydrate()`. No real-time waits. Same fix applies to Test 16. | Major |
| F28 | AC10 step 10.4 (line 292) — scope-leak grep checklist | OPERATIONAL | Grep targets (`* {`, `html {`, `body {`, `:root {`, `.card {`) are naive substring matches. False positives: `/* :root variables */` comment, `[attr*="*"]` selector, `.cardholder {` class. False negatives: `:where(:root) {`, `@layer base { :root {} }`, custom-property leaks. | Replace ad-hoc grep with: (a) stylelint rule `selector-disallowed-list: ['*', 'html', 'body', ':root']` scoped to `jobs-pane.css`, fails build on violation; (b) canary test asserting `getComputedStyle(document.body).backgroundColor` matches Phase 5 baseline post-load. Grep stays as coarse first pass. | Major |
| F29 | AC10 step 10.5 (line 292) — "decide re-capture vs rollback" | AMBIGUITY | No operational owner named for the re-capture-vs-rollback decision. Re-capture risks masking a 6a regression as "intentional drift"; rollback risks discarding legitimate Phase 5 work. | Default: rollback the 6a CSS port commit and re-investigate; only re-capture after 6a CSS scope leak is independently disproven by a separate diagnostic (temporarily delete `jobs-pane.css` `<link>` and re-run regression). Add this decision-tree to AC10 step 10.5. | Major |
| F30 | §Bucket template (lines 144-148) + Q-A9 | ACCESSIBILITY | `.jobs-bucket-header` gets `role="button"` + `tabindex="0"` but design specifies only click handling, not Enter/Space. Q-A9 covers Enter/Space for `.job-card-header` but is silent on bucket headers. Per WAI-ARIA 1.2, `role="button"` requires Enter+Space activation. | Add `keydown` handler: `if (e.key === "Enter" \|\| e.key === " ") { e.preventDefault(); toggleBucket(); }`. Add AC4 sub-test: keyboard-fired Enter on bucket header collapses; Space same; Tab moves focus; Escape no-op. Add `aria-expanded` on bucket header reflecting collapsed/expanded state. | Major |
| F31 | AC10 enumeration (line 292) — items 1-10 + sub-steps 10.1-10.5 | POLISH | "10.1 / 10.2" sub-step numbering is ambiguous against item numbering "10". | Renumber sub-steps as "10a / 10b / 10c / 10d / 10e". Cosmetic but reduces ratifier and implementer cognitive load. | Minor |
| F32 | line 358 (Reused functions: emoji TBD) | OPERATIONAL | Residual `TBD` line. REUSE pre-pass closed 2026-05-05 but this entry was not resolved. Pass 2 challenges the deferral: emoji selection is in the template TODAY (line 102: `⏳ \| ⚙ \| ✓ \| ✗`). | Edit line 358 either (a) cite the legacy source `notifications.js:5478` (already in REUSE table) and remove TBD, or (b) declare them as new design and add to "Genuinely new" rows. Stop deferring. | Minor |

### Layer 3 Design Concerns

| ID | Concern | What's at stake | Tradeoffs |
|---|---|---|---|
| C-6 | **Half-built delete button (Q-A6) UX risk** — 6a ships visible `×` with `aria-disabled` + `cursor: not-allowed`. If 6b slips or never ships, users see a button-shaped affordance that does nothing. No tooltip, no toast, no `title=""`. | UX trust degradation if shipped long-term in this state; visual regression vs legacy (which had a working delete) reads as a feature loss. | (1) Add `title="Delete coming in Phase 6b"` attribute now; (2) hide the button entirely until 6b (regress vs legacy parity); (3) ship 6a + 6b atomically (breaks slicing manifest). User must pick the long-term-stuck-at-6a posture. |

### Standout findings (highest implementer cost if missed)

- **F18 + F19 + F24**: contract drift between Phase 4 `Job` interface and 6a templates/ACs — surfaces as TS compile errors during implementation
- **F22**: AC9 string-match against the actual `console.log` output — verify the exact emission form before locking the assertion
- **F23**: `data-id-hash` collision on the delete button is the most likely runtime bug (TypeError on first click of disabled `×`)
- **F26**: mount idempotency is unguarded — double-mount silently duplicates listeners
- **F30**: only true accessibility hole — keyboard activation is contract-required for `role="button"`

### Awaiting

User ratification gate per PIP §6 + Q11 amendment. Cluster-walkthrough recommended (mechanical batch for Minors / meaningful walk for Majors), mirroring the Pass 1 pattern that worked.
