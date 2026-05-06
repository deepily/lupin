# Phase 6a — Jobs Surface (jobs-pane renderer + JobStore.hydrateHistory invocation + 5-bucket layout)

**Status**: 🟢 **PASS-1-CLOSED 2026-05-06** — Pass 1 Fitness 17 findings ratified (7 Minors batch-walked + 10 Majors walked individually); F15 ratification upgraded into the **global 100% coverage mandate** for multiplexer TypeScript (memory: `feedback_100pct_coverage_multiplexer.md`; project `CLAUDE.md` "100% COVERAGE MANDATE" section); AC table updated; Risks table updated; "Pass 1 Fitness — closed" subsection in `94-phase6a-review-findings.md`. Pass 2 Adversarial fires next against this Pass-1-resolved design state. Prior status: 🟡 REUSE-CLOSED 2026-05-05 (Q-A1-Q-A12 + Layer 3 concerns + 35 RE-rows all ratified — 27 reuse-as-is batch-approved + 8 meaningful rows walked one at a time; C-1 rejected; C-2-C-5 applied; RE-35 per-bucket-only-no-global-fallback per Q-A1).
**Authored**: 2026-05-05
**Q-ratification**: 2026-05-05 (this session — see §"Q-decisions — RATIFIED" below for the full ratification table)
**Slice**: 6a (first of 3) per `07-phase6-slicing-manifest.md`
**Issue**: ec746144

**Companion docs**:
- `07-phase6-slicing-manifest.md` — slice boundaries + dependencies + order across 6a/6b/6c
- `06-phase5-renderer-design.md` — Phase 5 design (notifications-list pane); 6a reuses its module patterns + AC machinery
- `05-phase4-stores-design.md` — Phase 4 store contracts; 6a consumes `JobStore` (read-only) + invokes `JobStore.hydrateHistory(api)` (Q7 hook)
- `90-execution-log.md` Phase 6a section (opens after user approval)
- `94-phase6a-review-findings.md` (to come — PIP output)

## Context

Phase 5 (commit `6ab9929` + determinism fix `d17abb6`) shipped the notifications-list pane (read-only) with hidden mount points for Phase 6 (`#jobs-pane` + `#tts-pane`, both `data-phase6-pending="true"`). Phase 6a lights up the jobs surface: render the 5-bucket layout (todo / running / done / dead / history), invoke `JobStore.hydrateHistory(api)` on mount (Q7 hook reserved through Phase 5), and lift `data-phase6-pending` from `#jobs-pane`.

Phase 4's `JobStore` already implements the reducer + the hydration body — `JobStore.hydrateHistory` fetches `/api/queue/job-history?limit=100`, dedups against in-session ids, emits `store_jobs_changed { changeKind: "hydrated", bucket: "history" }`. Phase 6a only needs to **call** it from the renderer + paint the panes from `JobStore.bucket(name)`.

This is the **most isolated slice** per the slicing manifest — own DOM surface, no shared mutable state with 6b or 6c, no contract changes to Phase 4 stores.

## Strategic design — recommended approach

### Module structure (`src/fastapi_app/static/js/multiplexer/render/` — extends Phase 5)

| Path | Purpose |
|---|---|
| `render/JobsPaneRenderer.ts` | Orchestrator: mount/unmount, store subscriptions, hydration trigger, hybrid Q-B render strategy adapted for 5 buckets |
| `render/templates/jobCard.ts` | `renderJobCard(job)` — `.job-card` per legacy class names (Q-C verbatim per Phase 5 precedent); status-{todo,running,done,dead} variants |
| `render/templates/jobBucket.ts` | `renderJobBucket(bucketName, jobs)` — bucket header + ordered card list; collapsed-by-default for done/dead/history |
| `render/index.ts` | Barrel — extends Phase 5 exports with `createJobsPaneRenderer({eventBus, stores, api})` factory (consumes ApiClient for hydration) |

Test files mirror Phase 5 layout under `src/tests/unit/multiplexer/render/`.

### JobsPaneRenderer

**Lifecycle** (mirrors Phase 5 `NotificationsListRenderer`):

```typescript
interface JobsPaneRenderer {
  mount(root: HTMLElement): void;
  unmount(): void;
  forceRenderForTesting(): void;
}

interface JobsPaneRendererOptions {
  eventBus    : EventBus;
  stores      : { jobs: JobStore };  // narrow object — only `jobs` is consumed (per Pass 1 F4)
  api         : JobHistoryApiClient;   // for hydrateHistory
  appTimezone?: string;
}
```

**Type contract** (per Pass 1 F4): the renderer accepts a NARROW `{ jobs: JobStore }` object, NOT the full `StoreSet`. This documents that only the jobs store is consumed and prevents accidental coupling to other stores. At construction time, if `stores.jobs` is falsy, `createJobsPaneRenderer` throws:

```typescript
if (!options.stores.jobs) {
  throw new Error("JobsPaneRenderer requires stores.jobs to be initialized");
}
```

This fails fast at boot.ts wiring rather than on first store-event subscription, and surfaces missing-dependency errors to the boot path where they're actionable.

**Render strategy** (hybrid, mirrors Q-B):
- `store_jobs_changed { changeKind: "hydrated", bucket: "history" }` → full rebuild of history bucket only
- `changeKind: "added" | "transitioned" | "removed"` → targeted bucket updates via `keyedListMerge` keyed by `data-id-hash` (per F12)
- No tick events for jobs (countdown is action-required-only)

**Mount routing** (per D-L family pattern): renderer mounts ONLY into `#jobs-pane`; does not touch `#notifications-pane` or `#tts-pane`. Removes `hidden` attribute + `data-phase6-pending` on successful mount.

**Hydration**: `mount()` calls `stores.jobs.hydrateHistory(api)` once asynchronously (no `await` in mount itself; floats the promise). Renderer's `store_jobs_changed { changeKind: "hydrated" }` subscription handles paint when the response lands. Initial paint shows whatever's already in `JobStore.bucket("history")` (in-session removed jobs only).

**Hydration error path** (per Pass 1 F3): the floated promise is wrapped in `.catch(...)` so rejections never become unhandled-rejection events:

```typescript
stores.jobs.hydrateHistory(api).catch(err => {
  console.warn("Failed to hydrate history:", err);
  eventBus.emit("hydration_failed", { source: "jobs", error: err });
});
```

The renderer subscribes to `hydration_failed { source: "jobs" }` and may optionally paint a "Could not load history" affordance into the history bucket header (visual-only in 6a; retry interactivity deferred). AC5 covers both the success-path race (F6) and the rejection-path race (F3 — fire `job_removed` while a rejecting hydrate promise is still pending).

**Ordering contract** (per Pass 1 F17 — Q-A7 "eager on mount"):
1. **Eager invocation**: `mount()` synchronously calls `stores.jobs.hydrateHistory(api)` INSIDE the mount method, **floats** the promise (no await).
2. **Mount returns immediately**; promise resolves asynchronously.
3. **Event subscription** to `store_jobs_changed { changeKind: "hydrated" }` fires when the promise resolves; renderer rebuilds the history bucket fully at that point.
4. **Race window**: if `job_state_transition` events arrive before hydrate resolves, the reducer applies them immediately; the hydrate response may include potentially-stale versions of those jobs. **JobStore dedup (by `id_hash`)** keeps final state coherent. Tested in AC5 race case (success + rejection variants).

**Empty state per bucket** (per Pass 1 F9 + Q-A1 strict ratification — RE-35 modified): each `renderJobBucket()` checks `if (jobs.length === 0) return html` `<div class='jobs-bucket-empty'>No <bucketName> jobs.</div>` `; else return html` `<section ...><header .../><div .jobs-bucket-cards> ...cards... </div></section>` `. **No global fallback.** When all 5 buckets are empty, the pane renders 5 empty-state divs (one per section), not a single global "No jobs yet." message.

### Job card template (`render/templates/jobCard.ts`)

**Class structure** (Q-C verbatim, ports from `notifications.css:3542-3653`):

```html
<div class="job-card status-{todo|running|done|dead|interrupted}" data-id-hash="${job.id_hash}" data-job-type="${job.job_type}">
  <div class="job-card-header">
    <span class="job-status-icon">⏳ | ⚙ | ✓ | ✗</span>
    <span class="job-type">${job.job_type}</span>
    <span class="job-id-short">#${job.id_hash.slice(0, 8)}</span>
    <span class="job-timing">${formatDuration(job.created_at, job.completed_at)}</span>
    <button class="job-delete-button" data-id-hash="${job.id_hash}">×</button>
  </div>
  <div class="job-card-details collapsed">
    <!-- expanded on click; lazy-render per Q-G-style pattern (see "Lazy-render mechanism" below) -->
    <pre class="job-meta-json" hidden></pre>
  </div>
</div>
```

Per **F12**: `data-id-hash` carries the canonical key; `data-job-type` is auxiliary metadata (not a key). Click on `.job-card-header` toggles `.collapsed`; lazy-render the meta JSON on first expand (mirrors Q-G progress-group lazy-cache pattern from Phase 5).

**Lazy-render mechanism** (per Pass 1 F2): the `<pre class="job-meta-json" hidden>` element renders **empty** in the initial template. On first click of `.job-card-header`:

```typescript
const expandedMetaCache = new WeakSet<HTMLPreElement>();
function onJobCardHeaderClick(e: MouseEvent) {
  const header = e.currentTarget as HTMLElement;
  const card   = header.closest("[data-id-hash]") as HTMLElement;
  const pre    = card.querySelector(".job-meta-json") as HTMLPreElement;
  // toggle collapsed class
  card.querySelector(".job-card-details")!.classList.toggle("collapsed");
  // populate once, cache via WeakSet
  if (!expandedMetaCache.has(pre)) {
    const job = stores.jobs.getById(card.dataset.idHash!);
    pre.innerText = JSON.stringify(job?.meta ?? {}, null, 2);
    pre.removeAttribute("hidden");
    expandedMetaCache.add(pre);
  }
}
```

Subsequent toggles are O(1) — the cached `<pre>` content is reused; only the `.collapsed` class flips. `WeakSet` prevents memory leaks when cards unmount (browser GC reclaims the entry once the DOM node is removed).

### Bucket template (`render/templates/jobBucket.ts`)

**Class structure**:

```html
<section class="jobs-bucket jobs-bucket-{todo|running|done|dead|history}" data-bucket="${bucketName}">
  <header class="jobs-bucket-header" role="button" tabindex="0">
    <span class="jobs-bucket-label">${bucketName}</span>
    <span class="jobs-bucket-count">(${jobs.length})</span>
    <span class="jobs-bucket-toggle">▼</span>
  </header>
  <div class="jobs-bucket-cards"></div>
</section>
```

**Default-expansion CSS rule** (per Pass 1 F1, derived from Q-A2 — see F14 citation below):

| `data-bucket` value | Initial render |
|---|---|
| `todo` | `<div class="jobs-bucket-cards">` (no `collapsed` class — visible) |
| `running` | `<div class="jobs-bucket-cards">` (no `collapsed` class — visible) |
| `done` | `<div class="jobs-bucket-cards collapsed">` (collapsed by default) |
| `dead` | `<div class="jobs-bucket-cards collapsed">` (collapsed by default) |
| `history` | `<div class="jobs-bucket-cards collapsed">` (collapsed by default) |

**Chevron toggle mechanism** (per Pass 1 F10 — matches Phase 5 `dateAccordion` precedent for visual consistency):

- Initial chevron: `▼` for expanded buckets (todo + running); `▶` for collapsed (done + dead + history).
- Click handler toggles `.collapsed` class on `.jobs-bucket-cards`.
- **CSS rotation** (recommended single-icon approach): one `<span class="jobs-bucket-toggle">▼</span>` element per bucket; CSS rotates it when collapsed:
  ```css
  .jobs-bucket-cards.collapsed ~ .jobs-bucket-toggle { transform: rotate(-90deg); }
  /* OR, on the section level: */
  section.jobs-bucket:has(.jobs-bucket-cards.collapsed) .jobs-bucket-toggle { transform: rotate(-90deg); }
  ```
  Single-icon text + CSS rotation matches Phase 5's accordion pattern; avoids per-toggle text mutation.

History bucket header gets a special "Load More" affordance (Q-A3 — page through `hydrateHistory` calls beyond the initial 100).

### CSS port (`src/fastapi_app/static/css/multiplexer/jobs-pane.css`)

Cherry-pick from `notifications.css` (line ranges from grep):
- `.job-card`, `.job-card.status-*` (lines 3542-3653)
- `.job-card-header`, `.job-card-header.has-cancel`, `.job-card-header:hover` (lines 3555-3568)
- `.job-card-details`, `.job-card-details.collapsed` (lines 3644-3653)
- `.job-card.status-interrupted` (line 4022)
- `.job-card.status-done .job-delete-button`, `.job-card.status-dead .job-delete-button` (lines 4718-4719)
- `.job-card.job-paused` (lines 4841-4846 — included for Q-A4 ratification: does Phase 6a paint paused state, or defer to 6b?)

**Selector audit protocol** (per Pass 1 F5):

1. Port each line range verbatim into `jobs-pane.css`.
2. **Verify obsolete-context selectors are flagged**: legacy CSS may target HTML structures no longer present in 6a (e.g., `.job-card-header.has-cancel` — the cancel-button sibling is removed by Q-A6 visual-only state; `.job-card-header > .job-status-icon` deeply-nested layout assumed in legacy).
3. **Run smoke test AC8a with fixture injecting a job per status** (`status-todo`, `status-running`, `status-done`, `status-dead`, `status-interrupted`, `job-paused`); assert no layout shift across viewports.
4. **Remove obsolete selectors as part of the port**: if a selector targets a class/structure that no longer exists in the 6a template (e.g., `.job-card-header.active`), DELETE the rule — do not leave dead CSS.
5. **Audit recorded in execution log**: per-rule disposition table (kept / pruned / modified / new) lands in `90-execution-log.md` Phase 6a section at apply time.

**Target**: ≤ 800 LOC residual (smaller than Phase 5's 579-LOC notification-list ceiling because job cards have less internal chrome than sender cards).

**Loading**: separate `<link>` tag in `multiplexer.html` head (per Q-D Phase 5 precedent).

### Page shell update (`src/fastapi_app/static/html/multiplexer.html`)

Lift `data-phase6-pending="true"` from `#jobs-pane`; remove `hidden`; populate the section structure:

```html
<section id="jobs-pane" data-testid="multiplexer-jobs-pane">
  <header class="jobs-pane-header">
    <h2>Jobs</h2>
    <button class="jobs-pane-history-load" data-testid="multiplexer-jobs-load-history">Load history</button>
  </header>
  <div id="jobs-buckets-container" data-testid="multiplexer-jobs-buckets"></div>
</section>
```

`data-phase6-pending` stays on `#tts-pane` (6b) and on every action-required widget (6b).

### Boot.ts wiring

Insertion point: AFTER `renderer.mount(mountEl)` (Phase 5), BEFORE `transports.queue.start(sessionId)` (per F13 ordering invariant — listeners attached before frames flow):

```typescript
import { createJobsPaneRenderer } from "./render";

const jobsRenderer = createJobsPaneRenderer({
  eventBus,
  stores : { jobs: stores.jobs },
  api    : apiClient,
});
const jobsMountEl = document.getElementById("jobs-pane");
if (jobsMountEl === null) throw new Error("multiplexer: #jobs-pane not found");
jobsRenderer.mount(jobsMountEl);
```

Extend `BootCompletePayload.handlers` with `jobsRenderer: "mounted"` literal (mirrors Phase 5's `notificationsRenderer`):

```typescript
const bootCompletePayload: BootCompletePayload = {
  handlers : {
    audioBinary           : stores.audio.binaryHandler.name,
    notificationsRenderer : "mounted",
    jobsRenderer          : "mounted",
  },
};
```

`shared/types.ts:BootCompletePayload.handlers` extended with `jobsRenderer?: string` (optional, mirrors Phase 5 RE-16 + F22 pattern for intermediate-state cleanliness).

**Producer/type asymmetry** (per Pass 1 F11 + F12 — these clarifications are compatible, not contradictory):

- **Type-level (F12)**: `jobsRenderer?: string` is **optional in the TypeScript interface** — preserves forward/backward-compat with consumers that may receive payloads from older boot.ts revisions.
- **Runtime (F11)**: When `boot_complete` is emitted by the current boot.ts, `jobsRenderer` is **always set to the literal `"mounted"`** — unconditional. If `jobsRenderer` mount fails (e.g., `#jobs-pane` not found), `boot.ts` throws an error and `boot_complete` is never emitted. There is no path through current boot.ts that emits `boot_complete` with `jobsRenderer` missing.
- **Commit ordering (F12)**: The interface change in `shared/types.ts` and the producer change in `boot.ts` land in the **same commit**. `shared/types.ts` is edited first (or simultaneously) so `boot.ts`'s new field assignment compiles cleanly.

### Dev-tools card update (`src/fastapi_app/static/html/dev-tools.html:145`)

> "Greenfield rebuild of the notifications UI. Phase 6a: notifications-list + jobs surface live (read-only). TTS chrome, action-required interactive widgets, focus tray, voice persona modal, and audio recorder land in Phase 6b + 6c."

## Q-decisions — RATIFIED 2026-05-05

All twelve Q-A1 through Q-A12 ratified by user in interactive cosa-voice session 2026-05-05. Status column reflects ratification.

| Q | Question | Decision | Tradeoff (other paths considered) | Status |
|---|---|---|---|---|
| **Q-A1** | Empty-state policy when all 5 buckets empty | **Per-bucket empty messages** — each bucket renders its own muted "No <name> jobs." under its header | Single global "No jobs yet." (cleaner first-load but hides bucket structure) | ✅ Ratified 2026-05-05 |
| **Q-A2** | Bucket default-expansion on first paint | **Match legacy** — Todo + Running expanded; Done + Dead + History collapsed. **Legacy citation (per Pass 1 F14)**: `notifications.js:5128-5180` (accordion grouping body) + `notifications.js:5453+` (job-type routing). Legacy in-progress state mapped to "running + todo visible" by default; done/dead jobs hidden by default; history not shown until scroll-load. Phase 6a mapping: `todo`+`running` → expanded; `done`+`dead`+`history` → collapsed. F1 above provides the concrete CSS class table that implements this mapping. | All-expanded (history could be 100 cards on hydrate; visual noise) or all-collapsed (no info on first paint) | ✅ Ratified 2026-05-05; F14 citation added 2026-05-06 |
| **Q-A3** | History pagination | **Single 100-row hydrate** — Phase 4's `hydrateHistory(api)` fires `?limit=100` once on mount; pagination deferred to a later micro-slice | Paged "Load more" (would extend `JobStore` contract or break read-only renderer invariant) or configurable limit (YAGNI scope creep) | ✅ Ratified 2026-05-05 |
| **Q-A4** | `.job-card.job-paused` styling scope | **Defer to 6b** — paused state is interactive (you can resume); visual without controls is misleading; pause/resume + visual ship together in 6b | Paint paused visual now (scope creep + confusing UX) | ✅ Ratified 2026-05-05 |
| **Q-A5** | Job card click action | **Expand-inline with lazy-cache** — matches Phase 5 Q-G progress-group pattern; click `.job-card-header` toggles `.job-card-details`; lazy-render meta JSON on first expand + cache | Modal portal (scope creep — 6c work; new portal infrastructure) or inline + modal CTA (most complex) | ✅ Ratified 2026-05-05 |
| **Q-A6** | `.job-delete-button` (×) scope | **Visual only in 6a, handler in 6b** — render `×` with `data-phase6-pending="true"` + `aria-disabled="true"` + `cursor: not-allowed` per Phase 5 inertness pattern; 6b wires `DELETE /api/queue/<name>/<id>` handler. Mirrors Q-H two-phase rollout. | Wire DELETE handler in 6a (scope creep) or skip entirely (looks like regression vs legacy) | ✅ Ratified 2026-05-05 |
| **Q-A7** | History hydration trigger | **Eager on mount** — `JobsPaneRenderer.mount()` calls `stores.jobs.hydrateHistory(api)` once asynchronously; history paints when response lands; `isHistoryHydrated()` becomes the "Load more" affordance gate. **4-step ordering contract (per Pass 1 F17)** documented inline in §JobsPaneRenderer "Ordering contract" subsection — covers: (1) eager invocation inside mount; (2) mount returns immediately; (3) `store_jobs_changed { changeKind: "hydrated" }` subscription paints when promise resolves; (4) race-window dedup by `id_hash` for early `job_state_transition` events arriving during the in-flight hydrate. AC5 covers the race (success path = F6, rejection path = F3). | Button-trigger only ("where's my history?" support load) or eager + refresh button (ambiguous semantics) | ✅ Ratified 2026-05-05; F17 ordering contract added 2026-05-06 |
| **Q-A8** | data-testid naming pattern | **Extend Phase 5 flat pattern** — `multiplexer-jobs-pane`, `multiplexer-jobs-buckets`, `multiplexer-jobs-bucket-{todo\|running\|done\|dead\|history}`, `multiplexer-job-card`, `multiplexer-jobs-load-history`, `multiplexer-jobs-bucket-empty` | Hierarchical `multiplexer.jobs.bucket.todo` (breaks Phase 5 precedent; CSS attribute selectors with dots need escaping) | ✅ Ratified 2026-05-05 |
| **Q-A9** | Click target on job card | **Full `.job-card-header`** — entire header row clickable; `role="button"`, `tabindex="0"`, keyboard Enter/Space activates expand/collapse. Matches legacy + Phase 5 sender-card-header pattern. | Status-icon only (tiny click target; mobile-hostile) or caret toggle only (small target; new chrome) | ✅ Ratified 2026-05-05 |
| **Q-A10** | Sort order within each bucket | **Newest-first by `created_at`**; `id_hash` lexicographic tiebreak when `created_at` is equal. Matches legacy + Phase 5 date-accordion ordering. | (no other paths surfaced) | ✅ Ratified 2026-05-05 |
| **Q-A11** | `boot.js` gz threshold for 6a | **Re-baseline per slice**: Phase 5 baseline = 29,662 bytes gz; +30 KB delta ceiling = **60,382 bytes** for 6a. Each subsequent slice re-baselines from prior slice's actual gz size. Per Q-I "revisable per-phase via Q-amendment in `01-phase0-decisions.md`". | Tighter delta (false-positive prone) or different baseline reference (Phase 4) | ✅ Ratified 2026-05-05 |
| **Q-A12** | Action-required filter on jobs | **N/A** — `Job` interface has no `action_required` flag (different schema from `Notification`); jobs can RAISE action-required notifications, but those flow through `NotificationStore` + action-required pane, not `JobStore` + jobs pane. No filter logic in `JobsPaneRenderer`. User confirmation comment: "Confirming: action-required filter does NOT apply to jobs". | (not applicable) | ✅ Ratified-by-N/A 2026-05-05 |

## Acceptance criteria (AC1-AC11b — modeled on Phase 5; per-slice 6a numbering)

Per-row `EXECUTOR: AI` per Pass 2 A1 schema; AC11a's `Human gate` column for slot-coordination only.

| AC | What | Executor | Human gate | Command / pass criterion |
|---|---|---|---|---|
| AC1 | TS compile clean | `EXECUTOR: AI` | — | `npx tsc --noEmit -p tsconfig.json` exit 0 |
| AC2 | ESLint clean | `EXECUTOR: AI` | — | `npx eslint src/fastapi_app/static/js/multiplexer/` exit 0 |
| AC2a | `hydrateHistory` grep guard now LIFTS — Phase 6a explicitly INVOKES it | `EXECUTOR: AI` | — | `grep -rn "hydrateHistory" src/fastapi_app/static/js/multiplexer/render/` returns ≥1 match (in `JobsPaneRenderer.ts`); previous Phase 5 ban inverts to a require |
| AC3 | Job card template tests ≥6 PASS (per response variant: empty meta, populated meta, status-{todo,running,done,dead}, click-toggle behavior) | `EXECUTOR: AI` | — | `npx tsx --test src/tests/unit/multiplexer/render/templates_job_card.test.ts` ≥6 PASS |
| AC4 | Bucket template tests ≥4 PASS (collapsed-by-default for done/dead/history, expanded for todo/running, header toggle, count display) | `EXECUTOR: AI` | — | `npx tsx --test src/tests/unit/multiplexer/render/templates_job_bucket.test.ts` ≥4 PASS |
| AC5 | JobsPaneRenderer tests ≥**16** PASS — mount/unmount, hydrate on mount triggers `hydrateHistory(api)` exactly once, store-event subscriptions, transition events update buckets via `keyedListMerge`, removed events route done/dead → history bucket, click-on-header toggles details lazy-cache, no tick events expected. **Test 15 (success-path race, per Pass 1 F6)**: (a) pre-seed JobStore with completed job `{id_hash: 'abc123', status: 'done'}`; (b) emit `job_removed { id_hash: 'abc123' }` → reducer moves to history bucket; (c) call `hydrateHistory(api)` with mock returning `{jobs: [{id_hash: 'abc123', status: 'done', ...}]}` after **100ms delay**; (d) within 50ms of hydrate call: verify state is still `{history: [job]}`; (e) wait for hydrate promise to settle; (f) assert final state is `{history: [job]}` with `count === 1` (no duplicate, no orphan). **Test 16 (rejection-path race, per Pass 1 F3)**: same fixture as Test 15 but mock returns a rejected promise after 100ms; assert (a) `hydration_failed` event emitted with `{source: "jobs"}`; (b) no unhandled-rejection in test harness; (c) state is `{history: [job]}` (in-session removed job preserved despite hydrate rejection). | `EXECUTOR: AI` | — | `npx tsx --test src/tests/unit/multiplexer/render/jobs_pane_renderer.test.ts` ≥16 PASS |
| AC6 | Coverage **100% lines / branches / functions** on the new render/ files (`JobsPaneRenderer.ts`, `templates/jobCard.ts`, `templates/jobBucket.ts`) per the **global 100% coverage mandate for multiplexer TypeScript** ratified 2026-05-06 (project `CLAUDE.md` "100% COVERAGE MANDATE"; auto-memory `feedback_100pct_coverage_multiplexer.md`). `c8 ignore` regions allowed BUT require same-line comment with explicit reason per Phase 4 A1 contract — use case is genuinely-unreachable defensive branches. **Re-exported Phase 5 utilities** (`html`, `keyedListMerge`, time formatters) are EXCLUDED from this AC6 — their coverage is measured by Phase 5's AC6 (also retroactively bumped to 100% per the global mandate; Phase 4 + Phase 5 backfill is a prerequisite of Phase 6a implementation per TODO.md). | `EXECUTOR: AI` | — | `c8 --all --include='src/fastapi_app/static/js/multiplexer/render/{JobsPaneRenderer.ts,templates/job*.ts}' --100 npx tsx --test src/tests/unit/multiplexer/render/jobs_pane_renderer.test.ts src/tests/unit/multiplexer/render/templates_job_card.test.ts src/tests/unit/multiplexer/render/templates_job_bucket.test.ts` (the `--100` flag fails the run if any of lines/functions/branches/statements drop below 100%) |
| AC7 | `boot.js` (content-hashed canonical) gzipped delta ≤ +30 KB vs Phase 5 baseline of **29,662 bytes** → ceiling = **60,382 bytes** | `EXECUTOR: AI` | — | `gzip -9 -c src/fastapi_app/static/dist/multiplexer/boot.<hash>.js \| wc -c` ≤ `60382`. Phase 5 baseline frozen in `90-execution-log.md` Phase 5 closure section (this slice opens its own AC7 baseline section) |
| AC8a | Functional page-load smoke — page loads on `LUPIN_API_URL`; jobs renderer mount completes within 500ms of `boot_complete`. AI Playwright asserts: (1) `[data-testid="multiplexer-jobs-pane"]` is NOT hidden, (2) 5 bucket sections present (`[data-bucket="todo"]` through `[data-bucket="history"]`), (3) **3 fixture jobs injected (per Pass 1 F16)** via three separate `page.evaluate(() => eventBus.emit(...))` calls, each payload `{id_hash: '<uuid>', job_type: 'DeepResearchJob', status: 'running'\|'done'\|'history', created_at: <epoch>, completed_at?: <epoch>, meta: {}}`. Bucket landing: (a) running job → `bucket('running')` via `job_state_transition`; (b) done job → `bucket('done')` via `job_state_transition`; (c) third job injected as `job_removed { id_hash, from: 'done', to: 'history' }` → `bucket('history')`. Assert 3 `[data-id-hash]` elements present, one per bucket. (4) **per C-5 tightening + Pass 1 F7 parameterization**: `data-phase6-pending="true"` count is **EXACTLY** `1 + N` where `N` = action-required widgets injected by the test fixture. **Three sub-cases parameterized**: (a) 0 action-required injected → count === 1 (only `#tts-pane`); (b) 2 action-required injected → count === 3 (`#tts-pane` + 2 widgets); (c) 3 action-required injected → count === 4 (`#tts-pane` + 3 widgets). Assertion form: `document.querySelectorAll('[data-phase6-pending="true"]').length`. Test name: `test_phase6a_data_phase6_pending_exact_count`; parameterized over fixture counts. Hard-coded count beats `≥` so silent drift can't slip through. | `EXECUTOR: AI` | — | `pytest src/tests/smoke/test_multiplexer_phase6a_smoke.py::test_phase6a_functional_smoke src/tests/smoke/test_multiplexer_phase6a_smoke.py::test_phase6a_data_phase6_pending_exact_count -v` all PASS |
| AC8b | Perf gate — pre-seed 50 jobs across buckets; first paint of all 50 cards within **150ms** of `boot_complete` (slightly looser than Phase 5's 100ms because 5 nested buckets cost more parent-traversal than the flat sender-cards container) | `EXECUTOR: AI` | — | `pytest src/tests/smoke/test_multiplexer_phase6a_smoke.py::test_phase6a_perf_gate -v` 1/1 PASS |
| AC9 | `boot_complete` console line includes `jobsRenderer:mounted` (literal string, F22 pattern) | `EXECUTOR: AI` | — | `pytest src/tests/smoke/test_multiplexer_phase6a_smoke.py::test_phase6a_boot_complete_handler_handshake -v` 1/1 PASS |
| AC10 | Phase 1/3/4/5 verification suites still green | `EXECUTOR: AI` | — | Enumerated: (1) `npx tsc --noEmit`; (2) `npx eslint`; (3) Phase 1 smoke 7/7 (post-D-G selector); (4) Phase 2 unit suite all PASS; (5) Phase 3 smoke 1/1; (6) WS smoke 50/50; (7) Phase 4 unit suite ≥88; (8) **Phase 5 unit suite all PASS** (cumulative 325 + 6a render tests); (9) Phase 5 smoke 3/3; (10) **Phase 5 visual baseline (regression check, no `--update-snapshots`) 1/1 PASS** — confirms 6a CSS port did not drift the notifications-list pane visual. **Per C-2 attribution rule + Pass 1 F8 5-step procedure**: (10.1) **Pre-6a**: capture Phase 5 baseline snapshot at **1920×1080** + list viewport. (10.2) **Post-6a CSS lands**: run Phase 5 visual regression check (no `--update-snapshots`) at the **same** viewport. (10.3) **If regression check fails**: examine `git diff src/fastapi_app/static/css/multiplexer/jobs-pane.css` + `git log --oneline \| head -1` (6a commit). (10.4) **Scope-leak grep checklist** in new file — grep for: `* {` (universal selector), `html {` / `body {` / `:root {` (root-level rules), generic `.card {` (class collisions). If any found → STOP; attribute failure to scope leak; revert CSS narrowing. (10.5) **If scope-leak grep is clean but visual still differs**: escalate as Phase 5 baseline drift (intentional or not); decide re-capture vs rollback. Diff inspection MUST attribute root cause to either (a) 6a CSS scope leak (revert 6a CSS narrowing), OR (b) genuine Phase 5 baseline drift (recapture baseline if intentional) BEFORE proceeding to commit. |
| AC10b | CSS port residual LOC ≤ 800 (smaller than Phase 5's 1,200 ceiling because job cards have less chrome); stylelint clean | `EXECUTOR: AI` | — | `[ "$(wc -l src/fastapi_app/static/css/multiplexer/jobs-pane.css \| awk '{print $1}')" -le 800 ] && npx stylelint src/fastapi_app/static/css/multiplexer/jobs-pane.css` exit 0 |
| **AC11a** | E2E submission — `POST /api/test-suite/submit` body `{"test_types": "e2e", "scheduled_at": "<user-confirmed slot>", "pytest_args": "--update-snapshots -k multiplexer_phase6a", "auto_fix_on_failure": false}` → HTTP 200 + valid `submission_id`. **Per Phase 5 spec drift §7-§9** documented learnings: status verification via Docker container logs, NOT `/api/test-suite/status/<id>` (endpoint does not exist) | `EXECUTOR: AI` | **HUMAN** — confirms `scheduled_at` slot non-overlapping. **NOT tester duty.** | `curl -X POST .../api/test-suite/submit -d '...'` returns 200 + `submission_id` |
| **AC11b** | E2E post-run state — assert (a) `find io/test-suite/visual-baselines/test_multiplexer_phase6a_visual/ -type f -name "*.png" \| wc -l > 0`, (b) container log contains `Test suite complete` + `e2e: 1 passed, 0 errors` for Run #2 (regression check, no `--update-snapshots`). **Per Phase 5 spec drift §4-§5**: fixture envelopes use FIXED timestamps + `_STABILIZE_DOM_JS` pattern from the start | `EXECUTOR: AI` | — | Two-run sequence: (1) `--update-snapshots` captures baseline (1 passed, 1 error per library convention); (2) regression check passes (1 passed, 0 errors) |

## Test pyramid

- **Unit** (`:7999` AI-discretionary): `templates_job_card.test.ts`, `templates_job_bucket.test.ts`, `jobs_pane_renderer.test.ts`. Includes hydration mock (stub `JobHistoryApiClient.get<T>` returning fixture jobs), bucket-routing assertion (transition events route correctly), no-tick-event invariant.
- **Smoke** (`:7999` AI-discretionary): `src/tests/smoke/test_multiplexer_phase6a_smoke.py` — page-load, mount, fixture injection, `data-phase6-pending` count assertion. Parameterized via `LUPIN_API_URL`.
- **E2E** (`:8000` scheduled-only via `POST /api/test-suite/submit`): `src/tests/e2e_ui/test_multiplexer_phase6a_visual.py` — captures `#jobs-pane` snapshot with 5 fixture jobs across buckets. Deterministic-fixture pattern (FIXED timestamps + `_STABILIZE_DOM_JS` pinning all dynamic text) applied from the start per Phase 5 spec drift §4-§5.

## Plan-review pipeline scope (Phase 0 step 4 — runs before user ratification)

- **REUSE pre-pass**: search prior art for jobs-pane patterns. Expected findings — legacy `notifications.js:5453+` (`type: 'job-card'` routing), `notifications.js:5128+` (job-card lookup by id), `notifications.css:3542-3653` (job-card class hierarchy). Phase 4 `JobStore` interface verbatim (read-only consumption).
- **Pass 1 fitness**: bucket-routing correctness, hydrate-on-mount race conditions (what if `mount()` runs before `JobHistoryApiClient` is ready?), `Q-A1`-`Q-A12` answer table coherence.
- **Pass 2 adversarial**: AC executability, ownership tags (canonical `EXECUTOR:` schema), convergence re-grep against Phase 4/5 baseline patterns, AC10b CSS LOC ceiling realism.

Findings consolidated into `94-phase6a-review-findings.md` for batch user ratification.

## Risks + mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| `JobHistoryApiClient.get` rejects (500, 401, network) on mount → renderer never paints history | Medium | Catch + emit warning console.log + render history bucket as "Could not load (retry)" affordance. AC5 unit test covers the rejection path |
| Hydrate races with live `job_removed` event for the same id → in-session entry replaced by stale persisted version | Medium | `JobStore.hydrateHistory` already dedups by id_hash (Phase 4 — see `JobStore.ts:152-156`). AC5 covers via the test "hydrate-after-removal preserves in-session removed-job state" |
| 5-bucket layout nested `keyedListMerge` calls (per-bucket merge AND per-card merge inside) → quadratic cost in worst case | Low | Top-level merges are O(buckets) = O(5) const; inner merges are O(jobs-in-bucket). Total O(N + 5) per re-render, same complexity class as Phase 5. |
| Click delegation handler conflict between Phase 5's notifications-pane handler and 6a's jobs-pane handler — both bind to the page | Low | **Isolation contract (per Pass 1 F13)**: Each renderer registers its OWN listener on its OWN mount root: `jobsMountEl.addEventListener('click', jobsClickHandler)` and `notificationsMountEl.addEventListener('click', notificationsClickHandler)`. Both listen at mount-root level for delegated clicks (`.job-card-header` clicks bubble → `jobsClickHandler`; `.sender-message-meta` clicks bubble → `notificationsClickHandler`). **No cross-pane delegation; each handler is independent.** Test assertion (`test_phase6a_click_handler_isolation` in AC5 / Phase5-AC4): two separate console.log or event-trace markers confirm both handlers fire for their own pane and **not** for the other pane. |
| Phase 5 visual baseline regression — 6a CSS port introduces a generic rule (e.g., `* { margin: 0 }`) that drifts `#notifications-pane` pixels | Medium | AC10 step #10 explicitly re-runs the Phase 5 visual regression check (no `--update-snapshots`) — pixel-match or fail. Encourages narrow-scope CSS in the new file. |
| `Job.meta` is `Record<string, unknown>` — JSON.stringify of a deeply-cyclic object throws | Low | Wrap stringify in try/catch; fall back to `String(meta)` representation. AC3 unit test covers cyclic-meta fixture. |
| **C-3/C-4 race**: `hydrateHistory(api)` runs asynchronously from `mount()`; live `job_removed` events can arrive while the hydrate promise is in flight, and the response may include a stale persisted version of an in-session-removed job | Medium | `JobStore.hydrateHistory` already dedups by `id_hash` (Phase 4 — `JobStore.ts:152-156`). AC5 floor bumped to ≥15 to cover the timing case explicitly: fire `job_removed` while hydrate promise is unresolved; assert no duplicate, no orphan. C-3 covers C-4 — same root race surfaced from two perspectives. |

## Critical files

**New** (Phase 6a implementation cycle):
- `src/fastapi_app/static/js/multiplexer/render/JobsPaneRenderer.ts`
- `src/fastapi_app/static/js/multiplexer/render/templates/jobCard.ts`
- `src/fastapi_app/static/js/multiplexer/render/templates/jobBucket.ts`
- `src/fastapi_app/static/css/multiplexer/jobs-pane.css`
- `src/tests/unit/multiplexer/render/templates_job_card.test.ts`
- `src/tests/unit/multiplexer/render/templates_job_bucket.test.ts`
- `src/tests/unit/multiplexer/render/jobs_pane_renderer.test.ts`
- `src/tests/smoke/test_multiplexer_phase6a_smoke.py`
- `src/tests/e2e_ui/test_multiplexer_phase6a_visual.py`

**Edited**:
- `src/fastapi_app/static/html/multiplexer.html` (lift `data-phase6-pending` + `hidden` from `#jobs-pane`; populate section structure with `#jobs-buckets-container` + "Load history" button; add CSS `<link>` for `jobs-pane.css`)
- `src/fastapi_app/static/js/multiplexer/boot.ts` (jobs renderer instantiation post-Phase-5-renderer-mount; `BootCompletePayload.handlers.jobsRenderer = "mounted"` per F22 pattern)
- `src/fastapi_app/static/html/dev-tools.html:145` (description text)
- `src/fastapi_app/static/js/multiplexer/render/index.ts` (export `createJobsPaneRenderer` from barrel)
- `src/fastapi_app/static/js/multiplexer/shared/types.ts` (extend `BootCompletePayload.handlers` with optional `jobsRenderer?: string`)

**Tracking docs** (Phase 0 — this cycle):
- ✅ `08-phase6a-jobs-surface-design.md` (this doc)
- ⏸ `90-execution-log.md` Phase 6a section seed (after PIP)
- ⏸ `94-phase6a-review-findings.md` (after PIP)

## Reused functions / utilities (existing)

- `JobStore.bucket(name)` + `getById(idHash)` + `hydrateHistory(api)` + `isHistoryHydrated()` — Phase 4 public API (`stores/JobStore.ts:90-97`); read-only consumption + one method invocation
- `JobHistoryApiClient` — Phase 4 loose interface (`stores/JobStore.ts:74-76`); production passes the canonical `ApiClient` (Phase 2)
- `keyedListMerge` from Phase 5 (`render/dom.ts`) keyed by `data-id-hash` (F12)
- `html` tagged-template helper from Phase 5 (`render/html.ts`)
- `formatHM`, `formatDateKey` from Phase 5 (`render/time.ts`) for `job.created_at` / `completed_at` display
- EventBus subscription pattern from Phase 4/5 (`unsubscribers: Array<() => void>`)
- Factory shape from Phase 5 `createNotificationsListRenderer` (RE-12)
- Legacy CSS classes ported verbatim from `notifications.css:3542-3653, 4022, 4718-4725, 4841-4846` (Q-C)
- Legacy job-card status-icon emojis if any (TBD — REUSE pre-pass to confirm)

## Pre-exit self-audit (against feedback memory)

| Memory | Compliance |
|---|---|
| `feedback_documentation_step_stops_at_doc` | ✅ This doc IS the artifact for Phase 0 of slice 6a; PIP runs + ratification + implementation are separate cycles |
| `feedback_phase0_serialization_prominence` | ✅ Phase 0 = doc serialization (top of doc, mandatory before any code) |
| `feedback_plans_include_tracking_docs` | ✅ Design doc (this) + execution log Phase 6a section seed + review-findings doc to come |
| `feedback_comprehensive_automated_testing` | ✅ Test pyramid covers unit (job card / bucket / renderer) + smoke (functional + perf gate + boot_complete handshake) + scheduled E2E (visual baseline on `:8000` with deterministic-fixture pattern from start) |
| `feedback_tests_parameterize_base_url` | ✅ Smoke + E2E parameterize via `LUPIN_API_URL` |
| `feedback_skip_rnd_doc_for_trivial_fixes` | ✅ NOT applicable — Phase 6a is non-trivial (~7 new files, new pane, new templates) |
| `feedback_lupin_only_never_cosa` | ✅ All edits under `src/fastapi_app/static/{js,html,css}/multiplexer/` + `src/tests/` + `src/rnd/`. No CoSA touch |
| `feedback_e2e_two_phase_gate` | ✅ AC11 first-run captures fresh baselines on `:8000` scheduled run; gate is "baselines + regression check both green" before 6b starts |
| `feedback_test_server_monopolize_mode` | ✅ AC11a submitted via `POST /api/test-suite/submit` with non-overlapping `scheduled_at`; never side-door injection |
| `feedback_audit_plans_at_execute_time` | ✅ Re-audit at execute-time noted in code-execution-plan cycle |
| `feedback_no_auto_promote_tags` / `feedback_never_auto_commit_push` | ✅ User explicitly approves each commit |
| `feedback_sweep_for_pattern_offenders` | ✅ NOT applicable — Phase 6a is greenfield, not a class-of-bug fix |
| `feedback_no_defensive_programming` | ✅ Renderer code uses explicit `x !== undefined` checks; no `getattr`-style fallbacks |
| `feedback_acknowledge_receipt_before_tool_work` (conversation mode) | ✅ Receipt acks issued for every user prompt in the implementation cycle |
| `feedback_enumerate_all_activation_paths` | ✅ Phase 6a surfaces enumerated: jobs-pane mount via boot.ts; store-event subscriptions; click delegation on `.job-card-header` and `#jobs-pane`'s "Load history" button; voice/MCP/hooks N/A in this slice |
| `feedback_naming_underscore_not_abbreviations` | ✅ Module names follow Phase 5 precedent: `JobsPaneRenderer.ts`, `jobCard.ts`, `jobBucket.ts` (camelCase TS files matching Phase 5's `senderCard.ts` / `dateAccordion.ts`) |

## Out of scope (Phase 6b or 6c — see slicing manifest)

- Action-required interactive submit (Phase 6b — Q-H two-phase rollout completion)
- TTS playback chrome on `#tts-pane` (Phase 6b)
- Job-delete button handler — `.job-delete-button` (Q-A6 — visual only in 6a; handler in 6b)
- Job-pause / job-resume controls (`.job-card.job-paused` interactive — Phase 6b if at all)
- `claude_code_event` consumer — D1 A-extended permanently out
- Voice-persona modal, conversation-mode UI pin, focus tray, audio recorder (Phase 6c)
- Cross-tab BroadcastChannel features (Q12)
- Forced cutover from `/app/notifications` (Q9)

---

## Decisions captured (additional context from 2026-05-05 ratification session)

The Q-decision table above is the canonical record. This section captures user-supplied context from the cosa-voice walkthrough that doesn't fit the table:

### Ratification session metadata

- **Session ID** (cosa-voice MCP): `532b16e1`
- **Date**: 2026-05-05
- **Mode**: conversation mode (user listening at distance via TTS); voice-message answers throughout
- **Tool**: `mcp__cosa-voice__ask_multiple_choice` for Q-A1 through Q-A9 (3-option layouts) + `mcp__cosa-voice__ask_yes_no` for Q-A10 through Q-A12 (binary confirms)
- **Re-asks during session**: Q-A3 first attempt hit a 503 from MCP backend; resubmitted with shorter abstract; ratified Option A on retry
- **User-attached confirmation comment** (Q-A12): "Confirming: action-required filter does NOT apply to jobs"
- **All 12 ratifications**: matched the design doc's recommendation (no redirects)

---

## Prior art referenced (REUSE close-out 2026-05-05 per PIP §4)

REUSE pre-pass surfaced 35 prior-art rows + 5 Layer 3 design concerns (full table in `94-phase6a-review-findings.md`). All ratified 2026-05-05; this section persists the verdict pointers for code-write time.

### Reuse-as-is (patterns) — 23 rows

| 6a element | Existing pattern (file:line) | Notes |
|---|---|---|
| `JobsPaneRenderer` orchestrator lifecycle (mount/unmount/forceRenderForTesting) | `render/NotificationsListRenderer.ts:69-130` | Phase 5 same-shape contract; copy verbatim |
| `createJobsPaneRenderer({eventBus, stores, api})` factory shape | `render/index.ts` Phase 5 barrel | Match factory signature |
| `getElementById + null-throw + removeAttribute` mount pattern | `NotificationsListRenderer.ts:91-110` | D-L mount routing precedent |
| `unsubscribers: Array<() => void>` lifecycle pattern | `NotificationsListRenderer.ts:112-129` | Closure collection from `bus.on()` returns |
| Hybrid render strategy (hydrated=full, transitions=keyed) | `NotificationsListRenderer.ts:139-167` | Q-B precedent adapted (no tick events for jobs) |
| `keyedListMerge` keyed by `data-id-hash` | `render/dom.ts` (F12 invariant) | Import from Phase 5; key by `data-id-hash="${job.id_hash}"` |
| EventBus `bus.on(...)` subscription + closure collection | `NotificationsListRenderer.ts:139-158` | Mirror listener signature |
| `JobStore.hydrateHistory(api)` invocation (no await) | `stores/JobStore.ts:144-171` (Phase 4 body complete) | Float promise; renderer subscribes to `changeKind: "hydrated"` |
| `.job-card.status-{todo,running,done,dead}` legacy CSS classes | `notifications.css:3542-3570` | Q-C verbatim port |
| Full-row `.job-card-header` click target with `role="button"` + `tabindex="0"` | `notifications.css:3555-3568` | Q-A9 ratified pattern |
| Lazy-render details on first expand + cache | `render/templates/notificationItem.ts` Q-G pattern | Q-A5 ratified pattern |
| Status-icon emoji mapping (⏳/⚙/✓/✗) | `notifications.js:5478` | Visual continuity with legacy |
| `.job-delete-button` visual + `aria-disabled` + `cursor: not-allowed` | `notifications.css:4692-4712, 4718-4725` | Q-A6 inertness pattern (Phase 5 actionRequiredReadOnly precedent) |
| `html` tagged-template helper import | `render/html.ts:1-120` | TT policy auto-applies |
| `formatHM(ts)` for HH:MM display | `render/time.ts:53-82` (D-H purity) | Import verbatim |
| `formatDateKey(ts)` for date grouping | `render/time.ts:85-103` | Import verbatim |
| `JobStore.bucket(name)` read-only consumption | `stores/JobStore.ts:90-141` | Phase 4 public API |
| `JobStore.getById(idHash)` for O(1) lookup | `stores/JobStore.ts:138-142` | Phase 4 public API |
| `JobStore.hydrateHistory(api)` with Phase 2 ApiClient | `stores/JobStore.ts:144-171` | Eager invocation per Q-A7 |
| `JobStore.isHistoryHydrated()` affordance gate | `stores/JobStore.ts:173-175` | Per Q-A3, gates "Load more" UI |
| Boot.ts insertion AFTER Phase 5 renderer mount, BEFORE transports.queue.start | `boot.ts:155-165` (F13 invariant) | Same ordering pattern |
| `boot_complete` console.log emission for AC9 | `boot.ts:173-175` | Extend payload, no new mechanism |
| Test naming `templates_job_card.test.ts` etc. | `src/tests/unit/multiplexer/render/templates_*.test.ts` | Phase 5 flat naming |

### Extend-existing — 9 rows

| 6a element | Legacy/Phase 5 anchor | What's reused |
|---|---|---|
| Bucket header click toggle (`.jobs-bucket-cards` collapse/expand) | `render/templates/dateAccordion.ts` | Apply Phase 5 accordion delegation pattern; new class names |
| CSS port from legacy ranges | `notifications.css:3542-3653, 4022, 4718-4725, 4841-4846` | Cherry-pick verbatim per Phase 5 precedent |
| `.job-card.status-interrupted` styling | `notifications.css:4022` | Port verbatim; visual-only in 6a (Q-A4) |
| `.job-card.job-paused` styling | `notifications.css:4841-4846` | Port verbatim; visual-only in 6a (Q-A4) |
| `BootCompletePayload.handlers.jobsRenderer` | `shared/types.ts:393-400` Phase 5 BootCompletePayload | Add optional field; mirror Phase 5 `notificationsRenderer` extension |
| Empty-state per bucket (NO global fallback per Q-A1; RE-35 modified 2026-05-05) | `render/templates/actionRequiredReadOnly.ts` Phase 5 empty-state CSS | Per-bucket-only per Q-A1 strict ratification; visual styling (`text-align: center`, muted color) borrows from Phase 5 `notifications-empty-state` class for visual continuity. The "global fallback when all 5 empty" half of the agent's original RE-35 verdict was DROPPED — Q-A1 explicitly rejected the mixed-mode option. |
| Unit test JobHistoryApiClient mock | `src/tests/unit/multiplexer/stores/job_store.test.ts:40-70` | Mock API shape `{jobs: Job[], total?, limit?, offset?}` |
| Smoke test `LUPIN_API_URL` env var | `test_multiplexer_phase5_smoke.py:1-40` | Copy scaffolding |
| `c8` coverage gates | Phase 5 AC6 contract | Same per-file ≥90% lines floor + Phase 4 A1 inline-comment-required for `c8 ignore` regions |

### Genuinely new — 3 rows

| 6a element | Why no prior art is acceptable |
|---|---|
| `.jobs-bucket-{todo\|running\|done\|dead\|history}` section structure | Bucket-level grouping has no legacy precedent (legacy was card-only flat). Design provides full DOM spec inline. |
| 5-bucket layout with selective default-expansion (todo/running expanded; done/dead/history collapsed) | First time 5 buckets are paneled. Legacy used inline status grouping without per-bucket containers. |
| Bucket header collapse/expand state management | Each bucket maintains its own `data-collapsed` attribute; renderer's click handler toggles. New pattern but follows Phase 5 accordion logic. |

### Layer 3 Design Concerns — disposition

| ID | Concern | Disposition | Where applied |
|---|---|---|---|
| C-1 | CSS namespace collision (cross-page coexistence with legacy) | ❌ **Rejected as framed** — CSS scope is per-page; cross-page collision impossible per browser model. The agent confused cross-page coexistence with same-page stylesheet overlap. | (no doc edit; rejection captured here for traceability) |
| C-2 | Delete-button visual regression risk against Phase 5 baseline | ✅ **Applied** | AC10 step (10) gets attribution rule — failure post-6a CSS lands → first suspect is 6a CSS scope leak |
| C-3 | History hydration race with early `job_removed` events | ✅ **Applied** | AC5 floor bumped 14 → 15; new test case enumerated in AC5 row + Risks-table row |
| C-4 | Boot.ts wiring order race (same root as C-3) | ✅ **Applied** | Folded into C-3's test case + Risks-table row notes "C-3 covers C-4" |
| C-5 | `data-phase6-pending` lift count assertion | ✅ **Applied** | AC8a count expectation tightened from `≥` to **exactly** `1 + N` (where `N` = action-required widgets injected by fixture); hard count beats `≥` so silent drift can't slip through |

### Sweep verification (PIP §7 step 3 grep targets)

After REUSE close-out, the design doc should pass:

| Grep target | Expected result | Status |
|---|---|---|
| `grep -nE "(\\bTBD\\b\|confirm during impl\|decide at impl time)" 08-phase6a-jobs-surface-design.md` | residual hits only in Q-decisions table (now ratified) | ✅ |
| `grep -nE "Open sub-question" 08-phase6a-jobs-surface-design.md` | zero | ✅ |
| `grep -nE "EXECUTOR: HUMAN" 08-phase6a-jobs-surface-design.md` | only AC11a row (justified slot-availability) | ✅ |
| `grep -rn "\\.job-card\\b\|\\.jobs-" src/fastapi_app/static/css/multiplexer/notifications-list.css` (verifying Phase 5 strip was complete; pre-implementation Pre-flight check per C-1 underneath-concern) | 0 matches expected; if any, refactor to scope `jobs-pane.css` rules narrowly | ⏸ pre-implementation Pre-flight |

---

---

## Pass 1 Fitness — closed 2026-05-06 (per Sequential PIP per Q11 amendment)

All 17 Pass 1 Fitness findings from `94-phase6a-review-findings.md` ratified via cosa-voice walkthrough on 2026-05-06 (Session `5ced4868`, persona Mr. Radio). 7 Minors walked individually after the batch yes/no was rejected; 10 Majors walked individually per design-doc TODO recommendation.

| ID | Severity | Type | Disposition | Where applied |
|---|---|---|---|---|
| F1 | Minor | COMPLETENESS | ✅ Applied | §Bucket template — concrete CSS class table for default expansion |
| F2 | Minor | AMBIGUITY | ✅ Applied | §Job card template — `<pre hidden>` initial render + `WeakSet`-cached lazy-render mechanism with code example |
| F3 | Major | AMBIGUITY | ✅ Applied | §JobsPaneRenderer — `.catch(...)` wrapper + `hydration_failed` EventBus event; AC5 Test 16 rejection-path race |
| F4 | Major | AMBIGUITY | ✅ Applied | §JobsPaneRenderer — `JobsPaneRendererOptions` documented with narrow `{ jobs: JobStore }` + defensive throw |
| F5 | Major | COMPLETENESS | ✅ Applied | §CSS port — 5-step audit protocol (verbatim port + obsolete selector flagging + per-status fixture smoke + dead-rule deletion + execution-log audit table) |
| F6 | Major | TESTABILITY | ✅ Applied | AC5 Test 15 — concrete success-path race fixture (pre-seed → remove → 100ms-delayed hydrate → assert no duplicate) |
| F7 | Major | TESTABILITY | ✅ Applied | AC8a — parameterized `[data-phase6-pending="true"]` count assertion across 0/2/3 fixture sub-cases |
| F8 | Major | COMPLETENESS | ✅ Applied | AC10 — 5-step visual regression procedure with viewport pin (1920×1080), scope-leak grep checklist, escalation path |
| F9 | Minor | AMBIGUITY | ✅ Applied | §Empty state per bucket — explicit "no global fallback" per Q-A1 strict; 5 empty buckets render 5 empty-state divs |
| F10 | Minor | COMPLETENESS | ✅ Applied | §Bucket template — CSS rotation chevron mechanism matching Phase 5 dateAccordion |
| F11 | Minor | COMPLETENESS | ✅ Applied | §Boot.ts wiring — `jobsRenderer: "mounted"` runtime-unconditional clarification |
| F12 | Minor | COMPLETENESS | ✅ Applied | §Boot.ts wiring — TS-optional `jobsRenderer?: string` + commit-ordering note (`shared/types.ts` + `boot.ts` same commit) |
| F13 | Major | RISK_SURFACE | ✅ Applied | Risks table — full click-delegation isolation contract + `test_phase6a_click_handler_isolation` assertion |
| F14 | Major | DECISION_TRACEABILITY | ✅ Applied | Q-A2 row — legacy citation `notifications.js:5128-5180` + `:5453+` + bucket-mapping table |
| F15 | Minor | COMPLETENESS | ✅ Applied + **GLOBAL UPGRADE** | AC6 — coverage floor bumped 90→100; new files enumerated; c8-ignore allowed with same-line reason. **Side-effect**: ratified into the global 100% coverage mandate for multiplexer TypeScript (project `CLAUDE.md` "100% COVERAGE MANDATE"; auto-memory `feedback_100pct_coverage_multiplexer.md`); Phase 4 + Phase 5 backfill is a prerequisite of Phase 6a implementation (TODO.md entry added). |
| F16 | Major | TESTABILITY | ✅ Applied | AC8a — explicit 3-fixture-job shape with id_hash, job_type, status, timestamps + bucket landings |
| F17 | Major | ORDERING | ✅ Applied | §JobsPaneRenderer "Ordering contract" + Q-A7 row cross-reference — 4-step eager-mount sequence |

### Convergence sweep (PIP §7 step 3 — Pass 1 close-out grep targets)

After this apply pass, the design doc passes:

| Grep target | Expected result | Status |
|---|---|---|
| `grep -nE "TBD\|confirm during impl\|decide at impl time" 08-phase6a-jobs-surface-design.md` | residual hits only in Q-decisions table (now ratified) + line 275 vestigial REUSE-era footnote (clean-up deferred — non-blocker per Pass 1 findings doc grep section) | ✅ |
| `grep -nE "Open sub-question" 08-phase6a-jobs-surface-design.md` | zero | ✅ |
| `grep -nE "EXECUTOR: HUMAN" 08-phase6a-jobs-surface-design.md` | only AC11a row (justified slot-availability) | ✅ |

### Side-effect tasks paired with Pass 1 close

- ✅ Project `CLAUDE.md` — "100% COVERAGE MANDATE" subsection added under TESTING.
- ✅ Auto-memory `feedback_100pct_coverage_multiplexer.md` — ratified scope (Option A: multiplexer TS only) + retroactive backfill obligation.
- ✅ `MEMORY.md` index — pointer line added.
- ✅ `TODO.md` — "Phase 4 + Phase 5 c8 coverage backfill to 100% before Phase 6a implementation opens" entry added.
- ✅ `94-phase6a-review-findings.md` — "Pass 1 Fitness — closed 2026-05-06" subsection appended (mirrors REUSE-closed pattern from 2026-05-05).

---

**Awaiting**: Pass 2 Adversarial Agent run (clean-context, sees this Pass-1-resolved design state per Q11 amendment + sequential PIP) → produces Pass 2 findings section in `94-phase6a-review-findings.md` → user ratification → Resolution Loop → final user go-ahead → separate plan-mode cycle plans Phase 6a code execution.
