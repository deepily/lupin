# Phase 5 — Renderer (tagged-template `html` helper + first pane: notifications list + CSS port)

**Status**: 🟢 **Phase 0 CLOSED 2026-05-05** — design ratified (Q-A through Q-L); plan-review pipeline executed in parallel; all 12 D-tier findings ratified; Resolution Loop round 1 fixes applied; convergence re-greps clean. Implementation cycle (separate plan-mode session) is the next step.
**Authored**: 2026-05-05 (parent plan: `~/.claude/plans/compressed-snacking-babbage.md`, approved via ExitPlanMode 2026-05-05)
**Q-ratification**: 2026-05-05 (this session — see "Decisions captured" section below)
**Issue**: ec746144

**Companion docs**:
- `2026.05.05-phase5-pre-design-exploration.md` — citation-depth Explore-agent findings (current pane DOM/CSS/handlers, Phase 4 store contracts verbatim, scaffolding integration map). Read this for background; it's the pre-design research that informs every section below.
- `90-execution-log.md` Phase 5 section — status tracking
- `92-phase5-review-findings.md` (to come) — REUSE + Pass 1 + Pass 2 findings post-ratification

## Context

The Lupin "multiplexer" UI rebuild — a TypeScript+esbuild greenfield rewrite of the vanilla-JS notifications page at `/app/notifications` — closed Phase 4 on 2026-05-04 (commit `8f1f11c`, AC1-AC10 green, 119 new unit + 3 smoke tests). Phase 5 is the **renderer phase**: first pane (notifications list) only, plus the tagged-template `html` helper that all subsequent panes will reuse.

User locked the design directive in voice on 2026-05-05:

- **Skip** pixel-perfect duplication and forensic snapshots — current `/app/notifications` is frozen
- **Imitate** layout / flow / order of the current pane
- **Lift** `notifications.css` as starting-point styling; diverge only where architecturally required
- **Fresh** HTML markup via the tagged-template `html` helper — verbatim DOM lift is architecturally blocked by the no-inline-handlers + render-boundaries + Trusted Types directives ratified in Phase 0
- **Goal**: feature parity, not pixel parity. Visual regression baselines established **fresh** at first Phase 5 E2E run on `:8000` (scheduled).

## Phase 0 status (this design doc)

This document IS Phase 0 of Phase 5 — the design landing at canonical R&D path. Subsequent steps gated on this:

1. ✅ Design doc landed at `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/06-phase5-renderer-design.md`
2. ✅ Phase 5 section seeded in `90-execution-log.md`
3. ✅ User ratified Q-A through Q-L (2026-05-05 — see "Decisions captured" section below)
4. ✅ Plan-review pipeline executed (REUSE → Pass 1 → Pass 2 in parallel) → `92-phase5-review-findings.md` (2026-05-05)
5. ✅ User ratified all 12 D-tier decisions (D-A through D-L); Resolution Loop round 1 fixes applied; convergence re-greps clean per PIP §10 termination rule (2026-05-05)
6. ⏸ Separate plan-mode cycle plans Phase 5 code execution (next session)

**Phase 0 status: 🟢 CLOSED 2026-05-05** — design ratified, PIP findings ratified, Resolution Loop converged, user go-ahead logged. Implementation planning is the next session's surface.

No code, no `boot.ts` edits, no `multiplexer.html` edits in Phase 0. Design doc + execution log + PIP findings are the artifacts; code is the next session.

## Strategic design — recommended approach

### Module structure (`src/fastapi_app/static/js/multiplexer/render/` — new)

| Path | Purpose |
|---|---|
| `render/html.ts` | Tagged-template `html` helper — ~120 LOC custom impl, returns `DocumentFragment` |
| `render/markdown.ts` | `renderMarkdown(text)` wrapper — uses page-loaded `marked` + `DOMPurify` globals (matches current page) |
| `render/time.ts` | `formatHM(ts)`, `formatDateKey(ts)`, `formatCountdown(ms)` — `formatCountdown` is a **pure formatter** (per D-H ratification): input is pre-corrected `ms` from store, output is zero-padded `MM:SS` string. No `Date.now()`, no offset math. `formatHM` and `formatDateKey` consume server-clock offset via `appTimezone` (legacy parity per D-J citation fix). |
| `render/dom.ts` | Tiny diff utility — `replaceChildren`, `keyedListMerge` (key by `data-id-hash`) |
| `render/NotificationsListRenderer.ts` | First-pane orchestrator — mount/unmount lifecycle, store subscriptions |
| `render/templates/senderCard.ts` | `renderSenderCard(sender, notifications)` |
| `render/templates/dateAccordion.ts` | `renderDateAccordion(dateKey, notifications)` |
| `render/templates/notificationItem.ts` | `renderNotificationItem(notification, actionRequiredItem?)` |
| `render/templates/actionRequiredReadOnly.ts` | Read-only widget (Phase 5) — prompt + countdown + options preview, **no submit handler** |
| `render/index.ts` | Barrel — `createNotificationsListRenderer({eventBus, stores})` factory |

Test files under `src/tests/unit/multiplexer/render/`.

### Tagged-template `html` helper

API:
```typescript
export function html( strings: TemplateStringsArray, ...values: Value[] ): DocumentFragment;
type Value = string | number | boolean | null | undefined | Node | DocumentFragment | readonly Value[] | { __raw: string };
export function raw( s: string ): { __raw: string };  // explicit opt-out for sanitized markdown
```

Returns `DocumentFragment` (not a string) — eliminates the string-concat seam where injection bugs hide. Auto-escapes string/number interpolations via `createTextNode`. Booleans/null/undefined render empty. Arrays flatten. `{__raw}` bypasses escape (markdown after DOMPurify).

Implementation: minimal custom (~120 LOC) — concatenate `strings` with comment-sentinels, parse via `<template>.innerHTML` once, walk fragment swapping sentinels for interpolated values. Attribute interpolation handled via regex pre-scan that rewrites to `setAttribute` calls post-parse. **No** `eval`/`new Function`. CSP-strict compatible.

**Trusted Types compatibility**: native `<template>.innerHTML` will trip a Trusted Types policy if one is enforced. Phase 5 ships a tiny default policy `lupin-html` registered ONLY when `window.trustedTypes` exists; the policy validates that the static parts came from a tagged template (TemplateStringsArray identity check) and refuses arbitrary strings. If TT is absent (current state), helper bypasses cleanly. Documented as a Phase 5 hook for future CSP hardening (Phase 7).

### NotificationsListRenderer

**Lifecycle** (per D-I ratification — plural store keys matching `StoreSet` at `stores/index.ts:36-42`):
```typescript
interface NotificationsListRenderer {
  mount( root: HTMLElement, deps: { eventBus, stores: { notifications, senders, actionRequired } } ): void;
  unmount(): void;  // unsubscribes ALL EventBus listeners + clears root
}
```

**Render strategy — hybrid (full-on-hydrate + diff-on-tick)**:
- `store_notifications_changed { changeKind: "hydrated" }` → full rebuild from `notificationStore.list()`
- `changeKind: "added" | "updated" | "expired"` → targeted update of single `[data-id-hash]` element (via `keyedListMerge`)
- `store_action_required_changed { changeKind: "tick" }` → **countdown text node only**, never the tree (1Hz × N pending prompts must not re-render the world; explicit unit-test invariant)
- `store_senders_changed` → targeted update of sender-card chrome (display name + `--persona-color` CSS var)

**DOM grouping**: keep current page's hierarchy (sender → date → message), newest-first ordering, soft-delete hides DOM until refresh. Element keys: `data-sender-id`, `data-date-key`, `data-id-hash`. Persona color via `element.style.setProperty("--persona-color", ...)` (avoids inline `style=` interpolation in helper).

**Action-required widgets in Phase 5 — read-only**: render prompt + `response_type` label badge + countdown + options preview + default. **No submit button, no input control, no click handlers** (Phase 6). Mark with `data-phase6-pending="true"` so Phase 6 selector finds it. Container shows `cursor: not-allowed` + `aria-disabled="true"` to communicate inertness.

**Markdown rendering** (per D-J ratification — citation correction + dual block/inline variants): reuse page-loaded globals `window.marked` + `window.DOMPurify`. The legacy notifications page ships **two** markdown renderers, both of which Phase 5 ports verbatim:

- **Block variant** — `renderMarkdown(text)` at `notifications.js:12203-12247` — wraps output in `<p>` paragraph (suitable for full-paragraph notification bodies).
- **Inline variant** — `renderMarkdownInline(text)` at `notifications.js:12279-12305` — strips the wrapping `<p>` (suitable for chat-bubble `.message-text` inside `.sender-message` where `<p>`-wrapping is wrong).

Phase 5's `render/markdown.ts` exports both:

```typescript
export function renderMarkdown( text: string ): { __raw: string };       // block
export function renderMarkdownInline( text: string ): { __raw: string };  // inline
```

DOMPurify config + post-process target/rel rewriting ports verbatim from `notifications.js:12203-12247` (the canonical block-variant config; inline shares it). Snapshot test in `markdown.test.ts` asserts the imported config object equals the canonical legacy config; a second test asserts block vs inline produce different DOM (paragraph wrapping vs no wrapping) for the same input. Saves ~50KB on `boot.js` vs bundling.

### CSS port mechanism

- **Location**: `src/fastapi_app/static/css/multiplexer/notifications-list.css` (new directory)
- **Port**: copy `src/fastapi_app/static/css/notifications.css` (5,010 LOC) → strip non-pane rules (jobs queue, TTS chrome, audio recorder, focus tray, voice-persona modal, conversation-mode pin, abstract popover) → audit for selector-specificity regressions → target ~800-1,200 residual LOC
- **Loading**: `<link rel="stylesheet" href="/static/css/multiplexer/notifications-list.css">` in `multiplexer.html` head (separate tag — keeps `boot.js` budget realistic, parallel fetch, esbuild stays JS-only)
- **Class names**: keep existing (`.sender-card`, `.sender-message`, `.date-accordion`, etc.) — old + new pages on different URLs never share a DOM, namespace risk is zero, rename buys nothing functional
- **Drop**: `.cc-voice-input`, `.notification-corner-pause-btn`, `.notification-corner-stop-btn`, `.tts-playing`, `.is-paused-current` (all Phase 6)

### Page shell update (`src/fastapi_app/static/html/multiplexer.html`)

Per Q-D ratification (separate `<link>` tag, esbuild stays JS-only), Q-E ratification (reuse page-loaded `marked` + `DOMPurify`), Q-F ratification (`multiplexer-<thing>` flat data-testid), Q-L ratification (pre-add hidden Phase 6 mount points), and **D-L ratification** (two-child structure inside `#notifications-pane` — action-required widgets above sender cards):

```html
<head>
  ...existing lupin-base/nav links...
  <link rel="stylesheet" href="/static/css/multiplexer/notifications-list.css">
  <script src="/static/js/vendor/marked.min.js"></script>
  <script src="/static/js/vendor/purify.min.js"></script>
</head>
<body>
  <main class="container">
    <h1>Multiplexer</h1>
    <section id="notifications-pane" class="notifications-pane"
             data-testid="multiplexer-notifications-pane">
      <!-- D-L: action-required widgets render here, ABOVE sender cards -->
      <div id="action-required-section"
           data-testid="multiplexer-action-required-section"></div>
      <!-- D-L: sender cards render here, BELOW action-required widgets -->
      <div id="sender-cards-container"
           data-testid="multiplexer-sender-cards"></div>
    </section>

    <!-- Phase 6 mount points -->
    <section id="jobs-pane" hidden
             data-testid="multiplexer-jobs-pane"
             data-phase6-pending="true"></section>
    <section id="tts-pane" hidden
             data-testid="multiplexer-tts-pane"
             data-phase6-pending="true"></section>
  </main>
  <script type="module" src="/static/dist/multiplexer/boot.js"></script>
</body>
```

Remove `<p data-testid="multiplexer-phase1-placeholder">`. **Per D-G ratification**, this removal is paired with a coordinated update to `src/tests/smoke/test_multiplexer_phase1_smoke.py` to assert `multiplexer-notifications-pane` instead — landing in the same Phase 5 implementation cycle, so AC10 (Phase 1 smoke green) stays executable.

The Phase 6 mount points (`#jobs-pane`, `#tts-pane`) are pre-added as `hidden` per Q-L; renderer ignores them in Phase 5; Phase 6 mounts its renderers into them and removes the `hidden` attribute as it lights up. The `<!-- Phase 6 mount points -->` comment + `data-phase6-pending="true"` markers document intent so the markup doesn't read as orphaned.

**Mount routing (D-L)**: the action-required renderer mounts widgets into `#action-required-section`; the notifications-list renderer mounts sender cards into `#sender-cards-container`. Both renderers stay independent and separately observable — AC8a asserts both child elements exist post-mount.

### Empty-state UI (Q-K ratification)

When `notificationStore.list()` returns empty (fresh user, post-clear-all, pre-first-notification), the renderer paints a single empty-state `<div>` rather than leaving `#notifications-pane` blank:

```html
<div data-testid="multiplexer-empty-state" class="notifications-empty-state">
  No notifications yet.
</div>
```

The renderer subscribes to `store_notifications_changed { changeKind }`; on hydrate or post-removal, if the resulting `notificationStore.list()` is empty, the empty-state replaces the sender-card grouping. CSS centers the text vertically + horizontally with muted color (e.g. `color: #6c757d`); no illustration, no animation (per Q-K — pixel-parity creep was locked out 2026-05-05).

The `data-testid="multiplexer-empty-state"` is the Phase 5 smoke-test selector for asserting the empty path renders without DOM errors.

### Progress-group history rendering (Q-G ratification)

Per Q-G, progress-group history is **collapsed by default** + **lazy-rendered on first toggle-expand click**:

- `.progress-group-head` (current/most-recent message in the group) renders eagerly at hydrate/add time
- `.progress-group-toggle` chevron renders eagerly with the head; `aria-expanded="false"` initial state; chevron icon `▶`
- `.progress-group-history` container renders eagerly but EMPTY (`<div class="progress-group-history" hidden></div>`) — no history entries materialized yet
- On first toggle click: handler fetches `notification.progress_group_entries` (or equivalent shape from `NotificationStore`), renders entries into the empty container via `keyedListMerge`, removes `hidden`, flips `aria-expanded="true"` + chevron to `▼`, **caches** the rendered fragment
- Subsequent toggles re-show / re-hide cached fragment without re-rendering — toggle is O(1) after first expand
- Memory note: history is a per-notification slice already held by `NotificationStore`; renderer merely reflects it. No additional memory overhead.

This bounds initial render time (AC8 < 100ms target with 50-notification fixture) by keeping potentially large histories (50+ entries on long-running deep-research jobs) out of the initial paint cost. Tested in `render/notifications_list_renderer.test.ts` via assertion: "first hydrate produces N head elements but zero history entries; expanding one history materializes its entries and caches them; expanding again does not re-render."

### Action-required read-only template (Q-H ratification + D-A rename + D-L mount)

Per Q-H, Phase 5 ships **Option A — full fields, visually inert**. Two-phase rollout (Phase 5 = markup + visual + countdown; Phase 6 = handlers + submit).

**Naming policy (per D-A ratification 2026-05-05)**: all classes use the `.action-required-*` prefix matching legacy convention. Q-C compliance restored — no Phase-5-only `.ar-*` namespace. Where legacy provides the same semantic class, it's reused verbatim (e.g. `.action-required-timer` for the countdown, matching `notifications.css:609-770+`); where Phase 5 needs a class with no legacy equivalent (e.g. `.action-required-pending-notice` for the read-only microcopy), the new class adopts the same prefix family.

**Mount location (per D-L ratification 2026-05-05)**: action-required widgets render into `#action-required-section`, a direct child of `#notifications-pane` rendered ABOVE all sender cards. See §Page shell + §DOM grouping for the parent layout.

Concrete DOM template per `response_type`:

**`yes_no`**:
```html
<div class="action-required-widget" data-phase6-pending="true"
     data-testid="multiplexer-action-required" data-id-hash="${idHash}"
     aria-disabled="true" style="cursor: not-allowed">
  <div class="action-required-prompt">${prompt}</div>
  <span class="action-required-response-type-badge">yes/no</span>
  <span class="action-required-countdown" data-countdown="${expires_at}">⏱ ${formatCountdown(countdownMs)}</span>
  <div class="action-required-options-preview">
    <span class="action-required-option-readonly">Yes</span>
    <span class="action-required-option-readonly">No</span>
  </div>
  <div class="action-required-default">Default: ${default ?? "no"}</div>
  <div class="action-required-pending-notice">Input arrives in next phase</div>
</div>
```

**`multiple_choice`**: identical structure; `.action-required-options-preview` enumerates each entry from `options` array.
**`open_ended`**: `.action-required-options-preview` replaced by `<div class="action-required-input-placeholder">[ text input — Phase 6 ]</div>`; default value still shown.
**`open_ended_batch`**: per-question repeats of the `open_ended` shape; one shared countdown.

Inertness markers (all required):
- `data-phase6-pending="true"` — Phase 6's selector for handler-attach pass
- `aria-disabled="true"` — accessibility signal
- `style="cursor: not-allowed"` — visual signal on hover
- `.action-required-pending-notice` microcopy — explicit user-facing signal

**Countdown invariant** (per Q-B + D-H): store emits `store_action_required_changed { changeKind: "tick", id_hash, countdownMs }` with `countdownMs` already-corrected for server-clock offset (math owned by `ActionRequiredStore.ts:157, :302`). Renderer's tick handler is a single text-node mutation:

```typescript
element.querySelector(`[data-id-hash="${id_hash}"] .action-required-countdown`)
       .textContent = formatCountdown(countdownMs);
```

`formatCountdown(ms)` is a **pure formatter** per **D-H** — no `Date.now()` access, no offset math, no global state. Input `5023` → output `"00:05"`. **No parent-tree mutation on tick.** Unit test (`AC4`) asserts: set sentinel `data-test-canary="<uuid>"` on the `.action-required-widget` parent; emit a 10-tick burst at 100ms intervals; assert canary unchanged AND only `.action-required-countdown` `textContent` differs.

**CSS port reuse opportunities** (per Q-C / D-A): `notifications.css:609-770+` provides `.action-required-notification`, `.action-required-header`, `.action-required-title`, `.action-required-timer`, `.response-buttons`. Phase 5 read-only widget can selectively reuse layout/spacing/typography rules from these for the renamed siblings (`.action-required-prompt` borrows from `.action-required-title`; `.action-required-countdown` borrows from `.action-required-timer`; `.action-required-options-preview` borrows layout from `.response-buttons` minus interactive button states).

Phase 6 lights up by:
1. Adding click handler bound to `.ar-options-preview > .ar-option-readonly` (or input control for open_ended) — calls `actionRequiredStore.respond(idHash, response)`
2. Removing `aria-disabled`, `cursor: not-allowed`, `.ar-pending-notice` element
3. Removing `data-phase6-pending` marker

No markup rework; Phase 5 + Phase 6 share the same DOM scaffold.

### Tagged-template `html` helper — Trusted Types policy (Q-J ratification)

Per Q-J, the helper registers a `lupin-html` Trusted Types policy unconditionally when `window.trustedTypes` exists (zero-cost when absent — the current state in production). Implementation sketch:

```typescript
// render/html.ts
const TT_POLICY = ( typeof window !== "undefined" && window.trustedTypes )
  ? window.trustedTypes.createPolicy( "lupin-html", {
      createHTML: ( input: string, knownTemplate: TemplateStringsArray ): string => {
        // identity check: input must originate from a known TemplateStringsArray
        if ( !KNOWN_TEMPLATES.has( knownTemplate ) ) {
          throw new TypeError( "lupin-html: refused to mint TrustedHTML from unknown source" );
        }
        return input;
      }
    } )
  : null;

const KNOWN_TEMPLATES = new WeakSet<TemplateStringsArray>();

export function html( strings: TemplateStringsArray, ...values: Value[] ): DocumentFragment {
  KNOWN_TEMPLATES.add( strings );  // identity-track at first call
  const combined = assembleWithSentinels( strings, values );
  const template = document.createElement( "template" );
  if ( TT_POLICY ) {
    template.innerHTML = TT_POLICY.createHTML( combined, strings );
  } else {
    template.innerHTML = combined;
  }
  return swapSentinels( template.content, values );
}
```

Phase 7 (or any later phase) flips TT enforcement on by adding `Content-Security-Policy: trusted-types lupin-html` to FastAPI response middleware — a single-line server change. Every `html\`…\`` call site shipped from Phase 5 onward is automatically TT-compliant. Unit test (`AC3` slot) covers: (a) policy registration when `window.trustedTypes` mocked present; (b) helper bypasses cleanly when mocked absent; (c) attempts to mint TrustedHTML from non-tagged-template input throw.

### `boot.js` size threshold (Q-I ratification — revisable; baseline captured per D-C+D-D)

AC7 enforces gzipped delta ≤ +30 KB vs Phase 4 baseline.

**Phase 4 baseline (captured 2026-05-05 per D-C+D-D ratification)**:
- Artifact: `src/fastapi_app/static/dist/multiplexer/boot.<hash>.js` (content-hashed canonical per `manifest.json`)
- Command: `gzip -9 -c src/fastapi_app/static/dist/multiplexer/boot.<hash>.js | wc -c`
- Result: **24,325 bytes** (frozen literal; recorded in `90-execution-log.md` Phase 4 closure section)

**Phase 5 ceiling (AC7)**: 24,325 + 30,720 = **55,045 bytes** at `gzip -9`. Same command, both ends.

Realistic Phase 5 budget breakdown (gzipped):

| Item | Δ gz |
|---|---|
| Tagged-template `html` helper (~120 LOC) | +1.5 KB |
| `render/markdown.ts` wrapper (uses globals — Q-E; block + inline variants per D-J) | +0.5 KB |
| `render/time.ts` formatters (`formatHM`, `formatDateKey`, `formatCountdown` — pure formatter per D-H) | +0.5 KB |
| `render/dom.ts` keyed-merge utility | +1.0 KB |
| `render/NotificationsListRenderer.ts` (lifecycle, subscriptions) | +3.0 KB |
| 4 template modules (senderCard, dateAccordion, notificationItem, actionRequiredReadOnly) | +4.0 KB |
| TT policy module (Q-J) | +0.5 KB |
| TS strict-mode declaration overhead | +1.0 KB |
| **Realistic total** | **~+11.8 KB gzipped** |

+30 KB gives ~2.5× headroom over the realistic estimate. Per the Q-I ratification, **the threshold is revisable per-phase via Q-amendment in `01-phase0-decisions.md`**. Phase 6 in particular will require a bump (jobs queue, TTS chrome, audio recorder land); Phase 7 too (User Timing + Long Tasks + OTel SDK). Pattern: amendment must update the baseline figure (whatever boot.js gzipped size at the start of that phase) AND the ceiling delta together; same Q-amendment machinery used by Q9 / Q10 / Q11.

### Boot.ts wiring (`src/fastapi_app/static/js/multiplexer/boot.ts`)

Insert after line 162 (`transports.audio.start(...)`), before `boot_complete` emit:

```typescript
import { createNotificationsListRenderer } from "./render";
const renderer = createNotificationsListRenderer( { eventBus, stores } );
const mountEl  = document.getElementById( "notifications-pane" );
if ( !mountEl ) throw new Error( "multiplexer: #notifications-pane not found" );
renderer.mount( mountEl );
```

Extend `boot_complete` payload to `{handlers: {audioBinary: "audioStoreBinaryHandler", notificationsRenderer: "mounted"}}` — gives Phase 5 a console-mirrored verification line for AC9.

### Dev-tools card (`src/fastapi_app/static/html/dev-tools.html:145`)

New description: *"Greenfield rebuild of the notifications UI. Phase 5: notifications-list pane live (read-only). Jobs queue, TTS, and action-required interactive widgets land in Phase 6."*

## Acceptance criteria (AC1-AC11b — refined per D-tier ratification 2026-05-05)

Per **D-F** ratification, AC11 splits into AC11a (submission) + AC11b (post-run state) + explicit `Human gate` column. Per **D-K** ratification, AC8 splits into AC8a (functional smoke) + AC8b (perf gate). Per **D-D** ratification, AC7 references the frozen Phase 4 baseline captured in `90-execution-log.md` (24,325 bytes at `gzip -9`) with explicit ceiling formula. The `Executor` column adopts the canonical PIP `EXECUTOR:` tag schema (AI-side rows tagged accordingly; AC11a's human-gate role lives in its own column with explicit slot-availability justification per **A1**).

| AC | What | Executor | Human gate | Command / pass criterion |
|---|---|---|---|---|
| AC1 | TS compile clean | `EXECUTOR: AI` | — | `npx tsc --noEmit -p tsconfig.json` exit 0 |
| AC2 | ESLint clean (incl. `hydrateHistory` ban — see AC2a) | `EXECUTOR: AI` | — | `npx eslint src/fastapi_app/static/js/multiplexer/` exit 0 |
| AC2a | `hydrateHistory` ban grep (per Q7 — Phase 5 must NOT call it) | `EXECUTOR: AI` | — | `! grep -rn "hydrateHistory" src/fastapi_app/static/js/multiplexer/render/` (exit 0 required; non-empty match → fail) |
| AC3 | `html` helper unit tests ≥ 18 PASS (escape, attr, fragment, raw, array, conditional, TT-policy-mocked-present, TT-policy-mocked-absent, identity-check failure) | `EXECUTOR: AI` | — | `npx tsx --test src/tests/unit/multiplexer/render/html.test.ts`. TT mocks: hand-rolled `globalThis.trustedTypes = { createPolicy: (name, hooks) => ({ createHTML: (s, t) => hooks.createHTML(s, t) }) }` shim in `beforeEach`; absence test uses `delete globalThis.trustedTypes` |
| AC4 | Renderer unit tests ≥ 16 PASS (hydrate, add, expire, **tick-only-touches-countdown via `data-test-canary` sentinel + 10-event burst**, mount/unmount, no leaked listeners, **4 empty-state transitions**) | `EXECUTOR: AI` | — | `npx tsx --test src/tests/unit/multiplexer/render/notifications_list_renderer.test.ts`. Tick invariant: `widget.setAttribute("data-test-canary","<uuid>")` before burst; assert canary unchanged after 10 `eventBus.emit("store_action_required_changed", { changeKind: "tick", id_hash, countdownMs })` calls; only `.action-required-countdown` `textContent` differs |
| AC5 | Template + dom + time + markdown unit tests ≥ 24 PASS combined; **per-file floors**: senderCard ≥3, dateAccordion ≥3, notificationItem ≥4, actionRequiredReadOnly ≥4 (one per response_type), dom ≥3, time ≥4, markdown ≥3 (incl. block vs inline DOM-shape contrast test) | `EXECUTOR: AI` | — | `npx tsx --test src/tests/unit/multiplexer/render/templates_*.test.ts src/tests/unit/multiplexer/render/{dom,time,markdown}.test.ts` |
| AC6 | Coverage ≥ 90% lines on `render/`; any inline `c8 ignore` region MUST include same-line comment naming unreachable branch + reason (Phase 4 A1 contract) | `EXECUTOR: AI` | — | `c8 --all --include 'src/fastapi_app/static/js/multiplexer/render/**' --exclude '**/*.test.ts' --reporter=text-summary --check-coverage --lines 90 npx tsx --test src/tests/unit/multiplexer/render/...` |
| AC7 | **`boot.js` (content-hashed canonical) gzipped delta ≤ +30 KB vs Phase 4 baseline of 24,325 bytes** → ceiling = **55,045 bytes** | `EXECUTOR: AI` | — | `gzip -9 -c src/fastapi_app/static/dist/multiplexer/boot.<hash>.js \| wc -c` ≤ `55045`. Phase 4 baseline frozen in `90-execution-log.md` Phase 4 closure section (D-C+D-D ratification 2026-05-05) |
| **AC8a** | **Functional page-load smoke** — page loads on `LUPIN_API_URL` (default `http://localhost:7999`), renderer.mount completes within 500ms of `boot_complete` per `performance.now()`. AI Playwright asserts: (1) `[data-testid="multiplexer-notification"]` count === 3, (2) plain notification `.message-text` equals fixture text, (3) markdown notification `.message-text` contains rendered HTML, (4) `.action-required-countdown` text changes between two samples 1100ms apart, (5) `[data-phase6-pending="true"]` count ≥ 3 (2 hidden panes + ≥1 action-required widget per **D-K(3)**). Fixtures injected via `page.evaluate(() => eventBus.emit("notification_queue_update", {...}))` direct, bypassing transport (per **D-E**) | `EXECUTOR: AI` | — | `pytest src/tests/smoke/test_multiplexer_phase5_smoke.py::test_phase5_functional_smoke -v` 1/1 PASS |
| **AC8b** | **Perf gate** — with 50-notification fixture pre-seeded via `page.evaluate(() => fixtures.forEach(f => eventBus.emit("notification_queue_update", f)))`, first-paint of `[data-testid="multiplexer-notification"]` count===50 within **100ms** of `boot_complete` per `performance.now()` | `EXECUTOR: AI` | — | `pytest src/tests/smoke/test_multiplexer_phase5_smoke.py::test_phase5_perf_gate -v` 1/1 PASS |
| AC9 | `boot_complete` console line includes `handlers.notificationsRenderer === "mounted"` (literal string, not function-name introspection); independent pass/fail surface | `EXECUTOR: AI` | — | `pytest src/tests/smoke/test_multiplexer_phase5_smoke.py::test_phase5_boot_complete_handler_handshake -v` 1/1 PASS. Captures `console.log` buffer via `page.on("console", ...)`; asserts string `notificationsRenderer:mounted` exactly once. Runs on independent Playwright context (try/finally around fixture seed); not coupled to AC8a/AC8b runtime |
| AC10 | Phase 1/3/4 verification suites still green; **per-D-G**, Phase 1 smoke also updates to assert `multiplexer-notifications-pane` instead of `multiplexer-phase1-placeholder` | `EXECUTOR: AI` | — | Enumerated: (1) `npx tsc --noEmit -p tsconfig.json` exit 0; (2) `npx eslint src/fastapi_app/static/js/multiplexer/` exit 0; (3) `pytest src/tests/smoke/test_multiplexer_phase1_smoke.py -v` 7/7 PASS (post-D-G selector update); (4) `npx tsx --test src/tests/unit/multiplexer/auth/auth_manager.test.ts ...` (Phase 2 suite, all PASS); (5) `pytest src/tests/smoke/test_multiplexer_phase3_smoke.py -v` 1/1 PASS; (6) `bash src/scripts/run-websocket-smoke-tests.sh` 4/4 PASS; (7) `npx tsx --test src/tests/unit/multiplexer/stores/...` ≥ 88/88 PASS |
| AC10b | CSS port residual LOC ≤ 1,200; stylelint clean | `EXECUTOR: AI` | — | `[ "$(wc -l src/fastapi_app/static/css/multiplexer/notifications-list.css \| awk '{print $1}')" -le 1200 ] && npx stylelint src/fastapi_app/static/css/multiplexer/notifications-list.css` exit 0 |
| **AC11a** | **E2E submission** — submit run via `POST /api/test-suite/submit` body `{"test_types": "e2e_ui", "scheduled_at": "<user-confirmed slot>", "args": "--update-snapshots -k multiplexer_phase5"}`; assert HTTP 200 + valid `submission_id` returned | `EXECUTOR: AI` | **HUMAN** — confirms `scheduled_at` slot non-overlapping with other in-flight `:8000` runs. **Justification**: external slot-availability calendar — user has visibility into the `:8000` schedule that AI does not. **NOT tester duty.** AI executes the submission. | `curl -X POST .../api/test-suite/submit -d '...'` returns 200 + JSON with `submission_id` |
| **AC11b** | **E2E post-run state** — poll `/api/test-suite/status/<submission_id>` to terminal state; assert (a) `find src/tests/e2e_ui/__snapshots__/multiplexer-phase5/ -type f -name "*.png" \| wc -l > 0`, (b) `final_state === "passed"`. E2E test code parameterizes target via `LUPIN_API_URL` env var (no hardcoded `:8000` literal in `src/tests/e2e_ui/multiplexer_phase5_*.py`). Per locked 2026-05-05 directive: feature parity not pixel parity; baselines fresh; no forensic capture from old page | `EXECUTOR: AI` | — | `pytest src/tests/integration/test_e2e_post_run_state.py::test_phase5_baseline_capture` 1/1 PASS |

## Test pyramid

- **Unit** (`:7999` AI-discretionary): `render/html.test.ts`, `render/markdown.test.ts`, `render/time.test.ts`, `render/dom.test.ts`, `render/templates/*.test.ts`, `render/notifications_list_renderer.test.ts`. Includes Trusted-Types-policy mocking, server-clock-offset edge cases, keyed-merge reorder correctness, `tick` invariant assertion.
- **Smoke** (`:7999` AI-discretionary): `src/tests/smoke/test_multiplexer_phase5_smoke.py` — page-load, mount, three-fixture render, countdown-tick visible. Parameterized via `LUPIN_API_URL` env var (default `http://localhost:7999`) per `feedback_tests_parameterize_base_url`.
- **E2E** (`:8000` scheduled-only via `POST /api/test-suite/submit` with non-overlapping `scheduled_at`): first run captures fresh visual baselines under `src/tests/e2e_ui/__snapshots__/multiplexer-phase5/`. **No forensic snapshot capture from `/app/notifications`** (per locked directive 2026-05-05).
- **Performance**: `boot.js` size delta tracked in execution log on every commit; first-render time measured via Playwright `performance.now()` from `boot_complete` to first paint of `[data-testid="multiplexer-notification"]` (target: < 100 ms with 50-notification fixture).

## Plan-review pipeline scope (Phase 0 step 4)

- **REUSE pass** (executed 2026-05-05 — see `92-phase5-review-findings.md` REUSE table RE-1 through RE-23): search prior art for tagged-template helpers, markdown rendering, time formatting, DOM diff utilities. Findings:
  - `notifications.js:12203-12247` (block markdown) + `12279-12305` (inline markdown variant) — reuse contract verbatim, both ports needed (per D-J)
  - `notifications.js:10068-10098` (date-key formatter — `getDateString` + `extractDateFromTimestamp`) — port logic
  - `notifications.js:10398-10412` (progress-group toggle handler) — port delegated-click pattern
  - Phase 2 EventBus subscription pattern — reuse-as-is
  - Phase 4 store contracts — must be consumed read-only; no mutation (D-B extends `Notification` interface to surface 5 renderer-required fields)
  - Third-party libs (lit-html / uhtml / htm) — assessed against custom impl; rejected per Q-A

- **Pass 1 fitness** (executed 2026-05-05): TT policy registration timing; markdown DOMPurify config drift audit; renderer-vs-store construction-order vs Phase 4 F12 precedent. 22 findings consolidated into `92-phase5-review-findings.md` Pass 1 table (F1-F22); 0 Layer 3 design concerns surfaced.

- **Pass 2 adversarial** (executed 2026-05-05): AC executability (AC7 gzip mode `-9` pinned per D-D; AC8 fixture mechanism = `page.evaluate` direct per D-E; AC11 baseline-capture mechanism = AC11a+AC11b split per D-F); ownership tags on each AC (canonical `EXECUTOR: AI` schema adopted per A1); convergence re-grep against Phase 4 baseline patterns. 14 findings consolidated into `92-phase5-review-findings.md` Pass 2 table (A1-A14); 3 Layer 3 design concerns folded into D-F + D-K.

Findings consolidated into `92-phase5-review-findings.md` for batch user ratification (mirrors Phase 4's `91-phase4-review-findings.md`). All 12 D-tier decisions ratified 2026-05-05 — fixes applied to this design doc + `90-execution-log.md`.

## Q-decisions — RATIFIED 2026-05-05

All twelve Q-A through Q-L ratified by user in interactive session 2026-05-05. Status column reflects ratification; "Decisions captured" section below records additional context provided during ratification (operator notes, follow-up commitments, two-phase rollout language for Q-H, revisable threshold language for Q-I).

| Q | Question | Decision | Tradeoff (other paths considered) | Status |
|---|---|---|---|---|
| **Q-A** | Tagged-template impl | Custom ~120 LOC returning `DocumentFragment`; conditional `lupin-html` TT policy | `htm` (~1KB) + render adapter, or `lit-html` (~6KB gz) — adds dep + supply chain | ✅ Ratified 2026-05-05 |
| **Q-B** | Render strategy | Hybrid: full-on-hydrate + keyed-on-{add,update,expire} + countdown-text-node-only-on-tick | Full re-render every change (1Hz × N action-required = thrash) or full RDOM diff (reintroduces framework declined in Q-A) | ✅ Ratified 2026-05-05 |
| **Q-C** | CSS class naming | Keep existing names verbatim (`.sender-card`, `.sender-message`, `.date-accordion`, etc.) | `mxr-` prefix or CSS Modules — no functional gain since old + new pages never share DOM | ✅ Ratified 2026-05-05 |
| **Q-D** | CSS bundling | Separate `<link rel="stylesheet">` tag; esbuild stays JS-only | Inline `<style>` (bloats HTML) or esbuild CSS plugin (rebuilds pipeline, breaks Phase 1 JS-only build decision) | ✅ Ratified 2026-05-05 |
| **Q-E** | Markdown library | Reuse page-loaded `window.marked` + `window.DOMPurify` globals; DOMPurify config verbatim port from `notifications.js:12203-12247` (block) + `12279-12305` (inline) per D-J citation correction | Bundle into `boot.js` (+~50KB) or switch to `micromark` (output drift vs old page → breaks parity) | ✅ Ratified 2026-05-05 |
| **Q-F** | data-testid naming | `multiplexer-<thing>` flat (matches `multiplexer-phase1-placeholder` + `devtools-link-multiplexer` precedent) | `mxr-<pane>-<thing>` hierarchical (`mxr` opaque outside codebase) or triple-prefixed (verbose) | ✅ Ratified 2026-05-05 |
| **Q-G** | Progress-group history rendering | Collapsed by default; head/toggle render eagerly; history materializes lazily on first toggle-expand click | Full hydration (slower initial render — 50+ entry deep-research jobs) or defer to Phase 6 (visible feature gap, breaks parity directive) | ✅ Ratified 2026-05-05 |
| **Q-H** | Action-required read-only display | **Option A** — full fields (prompt + `response_type` badge + countdown + options preview + default + "Input arrives in next phase" microcopy), inert (no submit, no input, no click handlers); two-phase rollout: Phase 5 ships markup + visual treatment + countdown ticker; Phase 6 attaches handlers via `[data-phase6-pending="true"]` selector | Option B (minimal "pending" indicator — loses RE-12 contract-validation) or Option C (hide entirely — breaks parity directive) | ✅ Ratified 2026-05-05 |
| **Q-I** | `boot.js` size threshold | ≤ +30 KB gzipped delta vs Phase 4 baseline = AC7 ceiling. **Per-phase commitment, revisable via Q-amendment in `01-phase0-decisions.md`** as bundle grows in Phase 6+ | +15 KB (false-positive prone) / +50 KB / +75 KB (would miss bundling `marked` ≈ 50 KB — defeats early-warning purpose) | ✅ Ratified 2026-05-05 |
| **Q-J** | Trusted Types policy | Register `lupin-html` unconditionally if `window.trustedTypes` exists (zero-cost when absent — current state); ~50 LOC including unit tests; Phase 7 lights up enforcement with single CSP header change | Opt-in via meta tag (extra config point) or defer to Phase 7 (every shipped `html\`…\`` call site becomes audit liability) | ✅ Ratified 2026-05-05 |
| **Q-K** | Empty-state UI | Plain text "No notifications yet." inside `<div data-testid="multiplexer-empty-state">` | Animated/illustrated empty state (pixel-parity creep, locked out 2026-05-05) or blank (no signal, no E2E hook) | ✅ Ratified 2026-05-05 |
| **Q-L** | Phase 6 placeholder mounts | Pre-add `<section id="jobs-pane" hidden data-testid="multiplexer-jobs-pane" data-phase6-pending="true">` + `<section id="tts-pane" hidden data-testid="multiplexer-tts-pane" data-phase6-pending="true">` in Phase 5 HTML edit, with `<!-- Phase 6 mount points -->` comment | Defer to Phase 6 (one extra HTML edit + commit just to add 2 hidden tags) | ✅ Ratified 2026-05-05 |

## Decisions captured (additional context from ratification session)

The Q-decision table above is the canonical record. This section captures user-supplied context provided during the 2026-05-05 ratification session that doesn't fit cleanly in the table:

### Q-H — two-phase rollout language

User asked for explicit clarification of the Phase-5/Phase-6 split for the action-required widget. Confirmed and recorded here:

| Phase | What lands | New/edited files |
|---|---|---|
| **Phase 5** (renderer-only) | Static markup (prompt + `response_type` badge + options preview + default), CSS for the visually-inert state, live countdown ticker via `tick → text node only` invariant from Q-B | `render/templates/actionRequiredReadOnly.ts` (new); `notifications-list.css` (inert styles) |
| **Phase 6** (interactive) | Click handlers attached via `[data-phase6-pending="true"]` selector; input controls wired up; `respond(idHash, ...)` calls into `ActionRequiredStore`; markup is unchanged; strip `aria-disabled`, `cursor: not-allowed`, microcopy | `render/templates/actionRequiredInteractive.ts` or extension of Phase-5 template |

The DOM scaffold + visual treatment land once in Phase 5; Phase 6 adds behavior to the same skeleton. The `data-phase6-pending="true"` marker is the agreed contract surface — Phase 6's selector finds the elements Phase 5 dropped, attaches handlers, and removes the marker.

### Q-I — threshold is a per-phase commitment, revisable

User confirmed that the +30 KB ceiling is a **starting commitment for Phase 5 specifically**, not a permanent constraint. Future phases can revisit:
- Phase 6 (jobs queue + TTS chrome + audio recorder land — bundle legitimately grows; expect a ceiling bump request)
- Phase 7 (observability libs — User Timing, Long Tasks, OTel browser SDK — explicit budget request)

Convention for changing the threshold is a **Q-amendment in `01-phase0-decisions.md`** (the durable record), same machinery already used for Q9 / Q10 / Q11 amendments. Amendment must update the baseline figure and the ceiling together.

### Q-J — Phase 5 ships TT-ready, enforcement comes later

User ratified the policy registration without redirect. Operational consequence recorded: when Phase 7 (or any later phase) decides to enforce CSP `trusted-types lupin-html` via the response header, it is a **single-line server config change** with no client-side rework needed. Every `html\`…\`` call site shipped from Phase 5 onward is automatically TT-compliant.

### Ratification session metadata

- **Session ID** (cosa-voice MCP): `532b16e1`
- **Date**: 2026-05-05
- **Mode**: started in notification mode (conversation_mode_active=false); user enabled conversation mode partway through the D-tier ratification round (after the 12-Q-decision walk)
- **Tool**: `mcp__cosa-voice__ask_yes_no` for each of Q-A through Q-L AND each of D-A through D-L
- **Re-asks during session**: Q-H (user asked for richer examples — re-asked with Options A/B/C breakdown + DOM samples; ratified Option A); Q-I (user asked for full context on what `boot.js` size threshold means and why it matters — re-asked with byte-budget breakdown + alternatives table; ratified +30 KB)

### D-tier ratifications applied 2026-05-05 (Resolution Loop round 1)

After plan-review pipeline ran (REUSE + Pass 1 Fitness + Pass 2 Adversarial — 59 findings consolidated into 12 D-tier decisions in `92-phase5-review-findings.md`), the user walked through D-A through D-L interactively and ratified all twelve. Fixes applied to this design doc + `90-execution-log.md` per PIP §7 Resolution Loop:

| D | Ratification | Where applied |
|---|---|---|
| D-A | Rename `.ar-*` → `.action-required-*` matching legacy; reuse legacy CSS for layout/typography | §Action-required read-only template (DOM block + naming-policy paragraph + CSS port reuse note) |
| D-B | Extend Phase 4 `Notification` interface + `NotificationStore.normalize()` with 5 new optional fields; ~5 unit tests; Phase 4 design doc minor amendment | §Critical files (Edited list adds `shared/types.ts`, `NotificationStore.ts`, and `05-phase4-stores-design.md`) |
| D-C+D-D | Capture Phase 4 `boot.js` baseline at `gzip -9` (24,325 bytes); pin both ends to identical command | §`boot.js` size threshold (frozen baseline + ceiling); `90-execution-log.md` Phase 4 closure section (baseline row + discrepancy flag) |
| D-E | AC8 fixtures injected via `page.evaluate(eventBus.emit("notification_queue_update", ...))` direct, bypassing transport | §Acceptance criteria AC8a (fixture mechanism + assertions) |
| D-F | Split AC11 → AC11a (submission) + AC11b (post-run state) + new `Human gate` column with explicit slot-availability justification | §Acceptance criteria (table restructured); `92-phase5-review-findings.md` D-F resolved |
| D-G | Phase 1 smoke selector update bundled into Phase 5 implementation cycle | §Critical files (Edited list adds `test_multiplexer_phase1_smoke.py`); §Page shell (D-G note) |
| D-H | `formatCountdown(ms)` is a pure formatter — no `Date.now()` access, no offset math; offset stays in `ActionRequiredStore` | §Module structure `render/time.ts` row; §Action-required read-only template (countdown invariant paragraph) |
| D-I | Mount signature uses plural `stores: { notifications, senders, actionRequired }` matching `StoreSet` | §NotificationsListRenderer Lifecycle |
| D-J | Three line-citation fixes (DOMPurify config, date-key formatter, progress-group toggle); add `renderMarkdownInline` to spec | §Markdown rendering (block + inline variants); §Reused functions (corrected citations); §Q-decisions table Q-E row (citation correction); §Plan-review pipeline scope (REUSE bullet citations) |
| D-K | Split AC8 → AC8a (functional smoke at 500ms with 3 fixtures) + AC8b (perf gate at 100ms with 50-fixture); add `data-phase6-pending` count assertion to AC8a | §Acceptance criteria AC8a + AC8b |
| D-L | Action-required widgets mount into `#action-required-section`; sender cards mount into `#sender-cards-container` (both children of `#notifications-pane`) | §Page shell update (two-child structure); §Action-required read-only template (mount-location paragraph) |

**Convergence re-greps** (PIP §7 step 3) run after this Resolution Loop closes to verify the standard Pass 1 + Pass 2 patterns return zero offenders (per the canonical PIP grep set).

## Risks + mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| CSS port leaves dropped-DOM selectors → bloated, confusing residual | High | Audit pass after first port + stylelint smoke check; aim ≤ 1,200 residual LOC |
| Tick events at 1Hz × N pending prompts cause render thrash | Medium | Hybrid strategy (Q-B) makes tick-only touch countdown text node; explicit unit test asserts no parent DOM touches on tick |
| Read-only action-required widget mistaken for interactive | Medium | `cursor: not-allowed`, `aria-disabled="true"`, microcopy "input arrives in next phase" |
| Markdown XSS regression vs old page | Low | Port DOMPurify config + XSS test fixtures verbatim from `notifications.js` |
| `boot.js` size threshold breach | Low | Track on every Phase 5 commit; AC7 fails fast |
| `marked`/`DOMPurify` globals not loaded when first notification renders | Low | Renderer constructor checks; queues renders until `DOMContentLoaded` if absent |
| TT policy bug breaks page when CSP later enforced | Low | Phase 5 ships policy WITHOUT enforcing TT; Phase 7 flips enforcement after burn-in |
| Phase 5 accidentally calls `JobStore.hydrateHistory()` (Q7 hook reserved for Phase 6) | Low | Grep guard in CI: `grep -r "hydrateHistory" .../render/` returns empty |
| Date-key boundary on locale flip puts "today" under wrong heading | Medium | Use server-clock offset (Phase 4 ActionRequiredStore pattern); document in `render/time.ts` |

## Critical files

**New** (Phase 5 implementation cycle, NOT Phase 0):
- `src/fastapi_app/static/js/multiplexer/render/{html,markdown,time,dom,index}.ts`
- `src/fastapi_app/static/js/multiplexer/render/NotificationsListRenderer.ts`
- `src/fastapi_app/static/js/multiplexer/render/templates/{senderCard,dateAccordion,notificationItem,actionRequiredReadOnly}.ts`
- `src/fastapi_app/static/css/multiplexer/notifications-list.css`
- `src/tests/unit/multiplexer/render/*.test.ts`
- `src/tests/smoke/test_multiplexer_phase5_smoke.py`

**Edited** (Phase 5 implementation cycle):
- `src/fastapi_app/static/html/multiplexer.html` (mount points + CSS link + marked/DOMPurify scripts; per D-L: two-child structure inside `#notifications-pane`)
- `src/fastapi_app/static/js/multiplexer/boot.ts` (renderer instantiation post-line-162; per F13: construction order `createStores → createRenderer → renderer.mount → transports.audio.start`)
- `src/fastapi_app/static/html/dev-tools.html:145` (description text)
- `src/tests/smoke/test_multiplexer_phase1_smoke.py` (per **D-G** ratification: update selector from `multiplexer-phase1-placeholder` → `multiplexer-notifications-pane`; bundles into Phase 5 cycle so AC10 stays green)
- `src/fastapi_app/static/js/multiplexer/shared/types.ts` (per **D-B** ratification: extend `Notification` interface with 5 new optional fields — `voice_persona?`, `abstract?`, `progress_group_id?`, `was_expired?`, `time_display?`)
- `src/fastapi_app/static/js/multiplexer/stores/NotificationStore.ts` (per **D-B** ratification: extend `normalize()` to copy through 5 new fields; ~5 unit tests in `notification_store.test.ts` for the new fields)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/05-phase4-stores-design.md` (per **D-B** ratification: add minor amendment block documenting Phase 5-initiated interface bump on `Notification`)

**R&D docs** (Phase 0 — this cycle):
- ✅ `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/06-phase5-renderer-design.md` (this doc)
- ⏸ `90-execution-log.md` Phase 5 section seed
- ⏸ `92-phase5-review-findings.md` (after PIP runs)

## Reused functions / utilities (existing)

- **EventBus subscription pattern** — Phase 2 `shared/EventBus.ts` (`.on()`, `.off()`)
- **NotificationStore public API** — `stores/NotificationStore.ts:55-70` (read-only consumption)
- **ActionRequiredStore public API** — `stores/ActionRequiredStore.ts:112-118` (read-only consumption + countdown subscription)
- **`Notification` interface** — `shared/types.ts:237-250`
- **`ActionRequiredItem` interface** — `shared/types.ts:320-329`
- **DOMPurify config** — `notifications.js:12203-12247` (block variant — verbatim port to `render/markdown.ts`); inline variant at `12279-12305` (per D-J citation fix 2026-05-05)
- **Date-key formatter** — `notifications.js:10068-10074` (`getDateString`) + `notifications.js:10084-10098` (`extractDateFromTimestamp` — `appTimezone`-aware) — logic port to `render/time.ts` (per D-J citation fix 2026-05-05; previous citation `10365-10395` was `createDateAccordion`, an unrelated function)
- **Time formatter (HH:MM 24-hour)** — `notifications.js:10107-10121` (`getLocalTimeDisplay`) — logic port to `render/time.ts` (per D-J citation fix 2026-05-05)
- **Progress-group toggle handler** — `notifications.js:10398-10412` (delegated handler in date accordion — per D-J citation fix 2026-05-05; previous citation in pre-design exploration §1.3 said `10678` which is unrelated)
- **esbuild build chain** — `src/scripts/build-multiplexer.sh` (no edit needed; CSS stays separate)
- **page-loaded globals** — `marked.min.js` + `purify.min.js` from `static/js/vendor/`

## Pre-exit self-audit (against feedback memory)

| Memory | Compliance |
|---|---|
| `feedback_documentation_step_stops_at_doc` | ✅ This doc IS the artifact for Phase 0; code is the next session, not auto-progressed |
| `feedback_phase0_serialization_prominence` | ✅ Phase 0 = doc serialization (top of doc, mandatory before any code) |
| `feedback_plans_include_tracking_docs` | ✅ Design doc (this) + execution log Phase 5 section + review-findings doc to come |
| `feedback_comprehensive_automated_testing` | ✅ Test pyramid covers unit (html/dom/time/markdown/templates/renderer) + smoke (page-load + 3 fixtures) + scheduled E2E (visual baseline on :8000) |
| `feedback_tests_parameterize_base_url` | ✅ Smoke + E2E parameterize via `LUPIN_API_URL` (default `:7999` smoke, `:8000` scheduled E2E) |
| `feedback_skip_rnd_doc_for_trivial_fixes` | ✅ NOT applicable — Phase 5 is non-trivial (~10-15 new files, new pane, new helpers) |
| `feedback_lupin_only_never_cosa` | ✅ All edits under `src/fastapi_app/static/{js,html,css}/multiplexer/` + `src/tests/` + `src/rnd/`. No CoSA touch |
| `feedback_e2e_two_phase_gate` | ✅ Phase 5 first-run E2E captures fresh baselines on `:8000` scheduled run; gate is "baselines committed + reviewed" before Phase 6 starts |
| `feedback_test_server_monopolize_mode` | ✅ AC11 first-run baseline submitted via `POST /api/test-suite/submit` with non-overlapping `scheduled_at`; never side-door injection |
| `feedback_audit_plans_at_execute_time` | ✅ Re-audit at execute-time noted: at PIP-run authoring, re-grep for new feedback memories that may have landed since this doc was written |
| `feedback_no_auto_promote_tags` / `feedback_never_auto_commit_push` | ✅ No commits or pushes triggered by this doc; user explicitly approves each commit |
| `feedback_sweep_for_pattern_offenders` | ✅ NOT applicable — Phase 5 is greenfield, no class-of-bug fix that needs codebase sweep |
| `feedback_acknowledge_receipt_before_tool_work` (conversation mode) | ✅ Receipt acks issued for every user prompt in this conversation |
| `feedback_enumerate_all_activation_paths` | ✅ Phase 5 surfaces enumerated: WebSocket events (notification_queue_update, etc.), store-event subscriptions, page-load, dev-tools card; voice/MCP/hooks N/A in this phase |

## Out of scope (Phase 6 or later)

- Jobs queue rendering (todo/running/done/dead/history buckets)
- TTS playback chrome + queue
- Action-required interactive submit (Phase 5 is read-only display only)
- Focus tray + focus-mode toggle
- Voice persona display modal
- Conversation-mode UI pin
- Sender-card audio recorder
- `claude_code_event` consumer (intentional per D1; F16-flagged)
- `JobStore.hydrateHistory()` invocation (Q7 hook reserved for Phase 6)
- Cross-tab BroadcastChannel features (Q12 single-tab policy)
- Forced cutover from `/app/notifications` (Q9 — old page stays indefinitely)
- Forensic snapshot capture from `/app/notifications` (locked out 2026-05-05 by user voice directive)

---

**Awaiting**: User ratification of Q-A through Q-L (or redirects). After ratification, plan-review pipeline (REUSE → Pass 1 → Pass 2) runs and produces `92-phase5-review-findings.md`. After PIP findings clean, separate plan-mode cycle plans Phase 5 code execution.
