# Multiplexer Gap Analysis — what it has, partially has, or lacks

**Author:** Rachel 🕊️ (for Tiberius 👑) · **Date:** 2026-06-10
**Deliverable 2 of 3** — reads against [`00-functional-change-summary.md`](00-functional-change-summary.md); feeds [`02-bridging-work-plan.md`](02-bridging-work-plan.md).

## How to read this

The deprecation goal ("multiplexer absorbs everything the JS client gained in the interim") has
**two gap layers**, and conflating them is the main risk to the Saturday target:

- **Layer A — interim features (the assigned scope):** the 12 feature groups F1–F12 added to the
  JS client since anchor `26898e1`. These are what the engagement is nominally about.
- **Layer B — pre-existing parity gaps (the blocker nobody scoped):** capabilities that existed in
  `notifications.js` *before* the anchor and which the multiplexer **never absorbed** because it
  paused at Phase 6c. These block deprecation regardless of Layer A, because you cannot route
  users off the JS client until the multiplexer is a full functional replacement.

**Headline finding:** *every one of F1–F12 is ABSENT or non-functional-partial in the multiplexer.*
The multiplexer is a clean, 100%-covered, well-architected client — but it stopped at a notifications
+ jobs + action-required + persona + focus-tray core. It never had the Reading Pane, the CC-session
strip, the commons activity panel, Fleet-Status, the messaging plane, prediction votes, the missed
badge, manager badges, a working sender-send path, or a login bounce. So this is **not** a "port 12
small deltas" job — it is "finish the multiplexer to parity, of which the interim deltas are a
subset."

## Multiplexer architecture (context for the porter)

Strict **store → renderer → transport** TypeScript (~10,183 LOC), coupled only by a typed
`EventBus`. Five stores (`NotificationStore`, `SenderStore`, `ActionRequiredStore`, `AudioStore`,
`JobStore`) subscribe in pinned order; renderers subscribe to `store_*_changed` events and do
keyed DOM patching via `<template>` cloning. **No globals, no inline `onclick`** (the JS monolith's
two main idioms). Build: **esbuild** (`src/scripts/build-multiplexer.sh`, `npm run build`) →
`src/lupin_app/static/dist/multiplexer/boot.js` (+ hashed copy + `manifest.json` + sourcemap);
`tsconfig.json` is `noEmit:true` (typecheck/lint only). XState v5 backs `AuthManager`,
`ConnectionStateMachine`, `AudioStore`. Served at **`GET /app/multiplexer`** (`pages.py`); config at
`GET /api/multiplexer/config`. Last coded phase: **6c**; last *designed* phase: **7a telemetry**
(never coded). Most recent commit touching the tree is only the `fastapi_app→lupin_app` rename.

> **Porting-idiom consequence:** every JS feature that uses an inline `onclick=` or a
> `window.notificationsUI.*` global (F7 Reset, F8 vote, F12 fleet refresh/toggle) must be
> **re-expressed** as a store action + `addEventListener` delegation in the multiplexer. This is a
> design translation, not a copy — budget for it.

## Layer A — interim features F1–F12 vs multiplexer

| # | Feature | Multiplexer status | Evidence / why |
|---|---|---|---|
| F1 | Master-Detail Reading Pane (+iframe, bust-out, toggle, scroll-preserve) | **ABSENT** | No iframe / master-detail / doc-viewer code anywhere in the TS tree. This is a *new pane concept* the multiplexer never had. |
| F2 | Action-Required in Reading Pane | **ABSENT** (compound) | The AR *interactive widgets* are **FULLY** present (`ActionRequiredRenderer.ts`, `actionRequiredInteractive.ts`), but the "lift into Reading Pane" behavior depends on F1, which is absent. |
| F3 | Focus-mode card height boost (500px) | **PARTIAL** | Focus-tray FULLY present (`FocusTrayRenderer.ts`), but this is a CSS rule keyed on `#cc-strip-toggle[data-focus-active]` + `.date-accordion-messages` — the **CC-strip + date-accordion DOM it targets does not exist** in the multiplexer (see Layer B). Trivial CSS once the strip lands. |
| F4 | Broadcast "Show more" toggle fix | **ABSENT** | `shared/broadcast.ts` exists but is **inert** (never `start()`-ed — single-tab policy Q12). There is **no commons Recent Activity panel** in the multiplexer at all, so the toggle has nothing to fix. |
| F5 | STT insert-at-caret | **PARTIAL→ABSENT** | Recorder is **scaffolded but non-functional**: `boot.ts:307-320` wires `currentUserEmail:""` because `AuthManager.getCurrentUserEmail()` was never added, so the send POST fails validation. The insert-at-caret refinement itself is absent. |
| F6 | TTS preview-fraction slider (12.5%) | **ABSENT** | `TtsChromeRenderer.ts` is **playback transport only** (Pause/Resume/Stop/Skip + queue length). Header explicitly notes no preview slider / scrubber / track name. |
| F7 | Missed-while-away badge + Reset | **ABSENT** | No missed badge. Boot emits `page_hidden`/`page_visible` but no renderer consumes them for an away count. |
| F8 | Prediction-hint thumbs vote (+markdown/confidence fixes) | **ABSENT** | No prediction/hint/vote code. (Markdown fence rendering *is* present via `markdown.ts` marked+DOMPurify — the F8 fence fix is moot in the multiplexer; only the vote UI is the gap.) |
| F9 | Reap → focus-bar badge drop + broadcast refresh | **ABSENT** | No `session_reaped` handler; no CC-strip to drop a badge from; broadcast inert. |
| F10 | Spin-up persona symmetry + hover removal | **ABSENT** | No CC-strip; `voice_persona_assigned` handling in the strip sense does not exist. |
| F11 | Focus-bar manager-lineage badge | **ABSENT** | No lineage/manager-badge code; no CC-strip to host it. |
| F12 | Read-only Fleet-Status table (8 cols, live-only toggle, polling) | **ABSENT** | No fleet-status code in the multiplexer. Server endpoint `/api/arbiter/fleet-state` exists and is client-agnostic — pure new client surface. |

**Layer A scorecard:** ABSENT ×9 (F1, F2, F4, F6, F7, F8, F9, F10, F11, F12 — F2 compound) · PARTIAL ×2 (F3, F5). **Zero fully-present.**

## Layer B — pre-existing parity gaps that block deprecation

These are *not* in the assigned "interim" scope but **must** be closed before users can be routed
off `notifications.js`. Discovered by reading the multiplexer source directly.

| Capability | Multiplexer status | Deprecation impact |
|---|---|---|
| **CC-session strip / focus-bar icons** | **ABSENT** | Hard blocker. F3/F9/F10/F11 *all* depend on it; it is also a primary always-on UI affordance in the JS client. The multiplexer has a `FocusTrayRenderer` but **no per-session strip** concept. |
| **Commons "Recent Activity" panel** | **ABSENT** | Blocker for F4 and for general parity (broadcasts, peer activity are visible in the JS client). |
| **Login bounce + token-key alignment** | **PARTIAL (real gap)** | Login is a *separate page* (`/app/auth/login`) — good. But `notifications.js` reads `lupin_access_token`/`lupin_refresh_token` and **redirects to `/app/auth/login?redirect=…` on missing token**, while the multiplexer `AuthManager` reads storage key **`auth_token`** and has **no missing-token redirect**. A user landing on `/app/multiplexer` with no token (or a token under the JS keys) will not authenticate. Small but mandatory. |
| **Sender-card send path (`getCurrentUserEmail`)** | **PARTIAL (non-functional)** | `boot.ts:307-320` TODO — outbound `user_initiated_message` POST fails until this lands. Blocks F5 and any user-typed/dictated reply. |
| **TTS preview slider** (same as F6) | **ABSENT** | Listed in Layer A too; called out here because it predates the anchor in the JS client. |
| **Action-Required read-only open-ended stubs** | **PARTIAL** | `actionRequiredReadOnly.ts:101,109` render `[ text input — Phase 6 ]` placeholders. Largely shadowed by the interactive renderer at boot, but a correctness gap. |
| **Scroll-position persistence** | **PARTIAL** | `StorageService` persists session-id + unread count only; no scroll persistence (F1's scroll-preserve has nowhere to anchor). |
| **Phase 7 (telemetry / CSP / Trusted Types / a11y)** | **DESIGNED, not coded** | Not a parity blocker for deprecation, but the multiplexer was *intended* to ship these. Out of scope for the Saturday bridge; note as deferred. |

## Net assessment for the Saturday target

- **Work is dominated by Layer B's CC-session strip + commons activity panel + auth/send fixes**,
  because most of Layer A (F3, F9, F10, F11) cannot land until the strip exists, and F1/F2 require a
  brand-new Reading Pane subsystem.
- **Realistic read:** full functional parity → deprecation by **Sat 2026-06-14** is **not credible**
  as a single push. The honest framing is a **tiered plan** (see Deliverable 3): a defensible
  minimum-viable-deprecation set vs. the full parity set, with explicit cut lines so Tiberius/Rick
  can choose the deprecation bar rather than discover the slip late.
- **Lowest-risk early wins** (no strip/pane dependency): F6 TTS slider, F8 vote UI, F7 missed badge,
  F12 Fleet-Status table (self-contained, server endpoint ready), auth-key alignment, `getCurrentUserEmail`.
- **Highest-cost items:** F1 Reading Pane (new subsystem) and the CC-session-strip family (F3/F9/F10/F11 + Layer B strip).

## Confidence notes

- Multiplexer statuses were read from the TS source (boot.ts, stores/, render/, transport/, audio/,
  auth/) — source over docs where they disagreed.
- The "FULLY present" claims for AR-interactive, jobs pane, persona modal, WS transport, conversation-mode
  pin were confirmed in the renderers and `boot.ts` wiring.
- Where a feature is "shadowed but stubbed" (AR read-only open-ended), it is flagged PARTIAL rather
  than ABSENT to avoid overstating the gap.
