# Phase 6b — Plan-Review Findings

**Date**: 2026-05-07
**Owner**: Mr. Radio session (`e8228026`)
**Cycle status**: REUSE pre-pass ✅ CLOSED 2026-05-07. Pass 1 Fitness dispatched 2026-05-07 → **14 findings** (0 Block / 9 Major / 5 Minor / 0 Layer 3); awaiting per-row ratification. Pass 2 Adversarial pending.

---

## REUSE Pre-Pass — Findings

Clean-context Explore agent walked the proposed module structure in `09-phase6b-interactive-widgets-design.md` against the existing multiplexer codebase. **28 RE rows** produced (vs Phase 6a's 35 — tighter surface as expected). Disposition breakdown: 16 reuse-as-is / 9 extend-existing / 3 genuinely-new.

### RE-row table

| ID | Component | Disposition | Evidence |
|---|---|---|---|
| **Render layer** | | | |
| RE-1 | `ActionRequiredRenderer.ts` | reuse-as-is | `NotificationsListRenderer.ts:69-130` Phase 5 lifecycle pattern |
| RE-2 | `TtsChromeRenderer.ts` | reuse-as-is | `JobsPaneRenderer.ts:81-100` Phase 6a precedent + Phase 5 pattern |
| RE-3 | ActionRequired factory signature | reuse-as-is | `boot.ts:197-201` Phase 6a JobsPaneRenderer factory shape |
| RE-4 | TtsChrome factory signature | reuse-as-is | Same; no `apiClient`, narrow `{stores}` per Pass 2 F4 |
| RE-5 | `#action-required-pane` mount | extend-existing | `NotificationsListRenderer.ts:100` (Phase 5 D-L routing — see C-1) |
| RE-6 | `#tts-pane` mount | extend-existing | `multiplexer.html:42-44` Phase 5 scaffold |
| RE-7 | `BootCompletePayload.handlers` two-key extension | extend-existing | `shared/types.ts:399-415` Phase 6a pattern |
| RE-8 | Boot wiring sequence | extend-existing | `boot.ts:177-204` (insert after jobsRenderer, before transports.queue.start) |
| **Templates** | | | |
| RE-9 | `actionRequiredInteractive.ts` | **genuinely-new** | No interactive template precedent (Phase 5 ships read-only only) |
| RE-10 | `ttsChrome.ts` | **genuinely-new** | TTS chrome is greenfield surface |
| RE-11 | Inertness-lift contract (Q-B2 atomic 4-marker strip) | extend-existing | `actionRequiredReadOnly.ts:49-53` applies markers; renderers strip atomically |
| RE-12 | Wait-for-response state machine (Q-B3) | **genuinely-new** | No prior submission state-machine in Phase 5/6a |
| RE-13 | Inline error stripe (Q-B4) | **genuinely-new** | No inline error UX in Phase 5/6a multiplexer |
| RE-14 | Delete-button click handler on JobsPaneRenderer | extend-existing | `JobsPaneRenderer.ts:81-220` Phase 6a deferred handler (Q-A6) |
| **CSS** | | | |
| RE-15 | `action-required.css` ≤500 LOC | **genuinely-new** | No interactive CSS precedent — Phase 5 deferred |
| RE-16 | `tts-chrome.css` ≤700 LOC | extend-existing | `jobs-pane.css:1-50` per-pane pattern + legacy port |
| RE-17 | `<link>` tags in `multiplexer.html` | extend-existing | `multiplexer.html:9-10` Phase 6a wire-up |
| RE-18 | Stylelint layer-2 scope-leak guard | reuse-as-is | `jobs-pane.css:24-28` Phase 6a layer-1+2 protection |
| **Boot & types** | | | |
| RE-19 | `ActionRequiredStore.respond()` consumption | reuse-as-is | `ActionRequiredStore.ts:116` Phase 4 API |
| RE-20 | `AudioStore` event subscriptions (Q-B9) | reuse-as-is | `AudioStore.ts:109-119` + `types.ts:74-77` |
| RE-21 | `AudioStore` control methods | reuse-as-is | `AudioStore.ts:109-119` (pause/resume/skip) |
| RE-22 | `DELETE /api/queue/<bucket>/<id>` endpoint | reuse-as-is | `src/cosa/rest/routers/queues.py:1193` `delete_queue_job` exists |
| **Tests** | | | |
| RE-23 | 4 unit test files | reuse-as-is | Phase 6a vitest pattern + 100% c8 mandate |
| RE-24 | Smoke test | reuse-as-is | `test_multiplexer_phase5_smoke.py:1-40` pattern |
| RE-25 | E2E visual test | reuse-as-is | Phase 5/6a AC11 pattern |
| **Patterns / cross-cutting** | | | |
| RE-26 | Renderer factory signature | reuse-as-is | `boot.ts:33-36` + `render/index.ts:13-24` |
| RE-27 | EventBus subscription + unsubscriber array | reuse-as-is | `NotificationsListRenderer.ts:74-75, 112-129` |
| RE-28 | Q-B1 response-type dispatch | extend-existing | `actionRequiredReadOnly.ts:71-109` Phase 5 dispatch logic |

**Totals**: 16 reuse-as-is / 9 extend-existing / 3 genuinely-new.

---

### Layer-3 design concerns surfaced during REUSE

**C-1 — Phase 5 action-required widget mount-point ambiguity**

The design doc's boot-wiring section assumed `#action-required-pane`, but Phase 5's `NotificationsListRenderer.ts:100-105` mounts widgets inline within `#notifications-pane` as `#action-required-section` per the D-L two-child routing pattern. If Phase 6b assumes a separate pane, `boot.ts` will fail with "querySelector #action-required-pane not found".

**Resolution**: Phase 0 prerequisite item #4 (already on the list per Q-B12 walkthrough surfacing). Verify before implementation; if Phase 5 uses inline routing, either rewire the mount or extend `NotificationsListRenderer` instead of creating a new pane-level renderer. Maps to Q-L + Phase 0 #4.

**C-2 — `multiSelect` flag missing from `ActionRequiredStore` payload schema**

Q-B1 routing depends on a `multiSelect: bool` field in the action-required notification payload. Phase 4 `ActionRequiredStore.ts:88-102` `ServerNotificationFields` interface does NOT include it. If the server doesn't send it, Q-B1 routing fails.

**Resolution**: Phase 0 prerequisite item #2 (already on list). CoSA-side server payload extension if absent. Maps to Q-B1 + Phase 0 #2.

**C-3 — `AudioStore` notification linkage missing**

Q-B8 textual current-track indicator requires the renderer to know which notification's audio is currently playing. `AudioStore.ts:109-119` does NOT expose `currentNotificationIdHash` or equivalent.

**Resolution**: Phase 0 prerequisite item #3 (already on list). CoSA-side `audio_chunk_decoded` event extension OR internal `AudioStore` linkage + getter. Maps to Q-B8 + Phase 0 #3.

**C-4 — `JobStore.delete(idHash)` API may be missing** ⚠️ NEW concern

Q-B10 optimistic delete requires `JobStore.delete(idHash)` to exist. Phase 4 `JobStore.ts:90-142` does NOT include a public `delete(idHash)` method. Without it, the Phase 6b delete-button handler cannot invoke the optimistic deletion. Since Phase 6a is already deployed (commit `243267b`), this may be either spec drift during Phase 6a execution OR an item that was never authored.

**Resolution**: Phase 0 prerequisite NEW item #6 — verify `JobStore` public API includes `delete(idHash: string)` method. If absent, file a Phase 4 amendment in the same R&D folder; add the method before Phase 6b implementation Phase 4 (delete-button wiring). Maps to Q-B10. **Promote to AC: AC2d grep guard verifies `JobStore.prototype.delete` exists.**

**C-5 — `data-phase6-pending` count assertion drift across phases** ⚠️ NEW concern

Phase 5 AC8a originally asserts `data-phase6-pending` count `≥ 3` (jobs-pane + tts-pane + action-required widgets). Phase 6a lifted the jobs-pane marker, dropping count to `≥ 2`. Phase 6b will lift the tts-pane marker, dropping count to `≥ 1` (action-required widgets only — interactive variants still ship with the marker until they're attached). If Phase 5's AC8a assertion was NOT updated to track Phase 6a's lift, the cascade drifts silently.

**Resolution**: Phase 6a REUSE findings (`94-phase6a-review-findings.md:106`) already appended AC8a update — verify it was applied. Phase 6b AC10 regression gate MUST re-run Phase 5 AC8a with the updated floor to ensure the cascade is correct. **Promote to AC: AC10e — re-run Phase 5 AC8a with assertion floor `= 0` (post-6b lift) AND re-run Phase 6a AC8a with floor `= 0` (post-6b lift).**

---

## REUSE — closed 2026-05-07

### Ratification record

| Turn | Scope | Result |
|---|---|---|
| Batch 1 | All 28 RE-rows | ✅ ratified (single yes/no) |
| Batch 2 | C-1 / C-2 / C-3 confirmations | ✅ ratified (single yes/no — no new work, just confirms existing Phase 0 prerequisites) |
| Individual | C-4 (`JobStore.delete` missing) | ✅ ratified — adds Phase 0 #6 + AC2d |
| Individual | C-5 (count-cascade drift) | ✅ ratified — adds AC10e |

### Empirical verification of C-4 (post-ratification)

Ran `grep -nE '^\s*(public\s+)?(async\s+)?delete\s*\(' src/fastapi_app/static/js/multiplexer/stores/JobStore.ts` — **0 matches** for a public method. Followup grep on `delete` returned only `JobStore.ts:292: this.indexById.delete(id)` — internal Map mutation inside another method.

**Confirmed**: `JobStore` does NOT expose a public `delete(idHash)` method. Phase 6b's Phase 4 implementation MUST add it as sub-step 4A before sub-step 4B (delete-button click handler) wires up.

### Applied to design doc

- § "Prior art referenced" subsection appended (closed REUSE table summary)
- AC2d added (JobStore.delete grep + tsc guard)
- AC5c added (delete-button extension test ≥6 cases — was implicit in Q-B11; made explicit here)
- AC10e added (cross-phase count-cascade regression)
- Phase 0 prerequisite #6 added (`JobStore.delete(idHash)` verification)

### Convergence re-grep

All 28 RE-rows have ratified dispositions; no proposed component lacks a Prior-art entry. No design conflicts detected.

---

---

## Pass 1 Fitness — Findings

**Total**: 14 findings (0 Block / 9 Major / 5 Minor / 0 Layer 3)

Phase 6a Pass 1 produced 17 (10 Major / 7 Minor); 6b is tighter — likely because Q-B6's mid-walkthrough correction caught a major that would've surfaced here.

### Findings table

| ID | Severity | Cluster | Summary |
|---|---|---|---|
| F-1 | Major | COMPLETENESS | AC10b TTS chrome budget says ≤500 but Q-B12 ratified ≤700 |
| F-2 | Major | TESTABILITY | AC5 ≥18 cases unenumerated — no breakdown per response_type |
| F-3 | Major | AMBIGUITY | Response-type dispatch implementation unspecified — where does Q-B1 routing live? |
| F-4 | Major | DECISION TRACEABILITY | Q-B5 countdown-expiry implementation lacks store-event + state details |
| F-5 | Major | TESTABILITY | AC2d grep regex won't match TS method definitions (`public delete(idHash: string)`) |
| F-6 | Major | COMPLETENESS | Phase 0 #6 prerequisite verification DOD + sub-step 4A/4B split unclear |
| F-7 | Major | AMBIGUITY | Inertness-lift child-element removal mechanism unspecified |
| F-8 | Minor | COMPLETENESS | AC7 boot.js baseline missing post-Phase-6a — delta budget unverifiable |
| F-9 | Minor | TESTABILITY | AC5b ≥12 cases unenumerated — state transitions + control combinations |
| F-10 | Minor | AMBIGUITY | Q-B9 throttling — store-side or renderer-side? |
| F-11 | Minor | COMPLETENESS | Phase 0 #3 verification target API shape unspecified |
| F-12 | Minor | ORDERING | Boot wiring insertion-point timing (sync vs floating promise) |
| F-13 | Major | RISK SURFACE | R2 throttling covers chunk_decoded only; rapid state-toggle could still thrash DOM |
| F-14 | Minor | COMPLETENESS | AC10e pytest command mixes explicit path + `-k` filter, fragile across phase test names |

### Standout Majors to walk first

- **F-2** — concrete AC5 enumeration; mirrors Phase 6a's "fixture shapes" rigor
- **F-3** — Q-B1 routing dispatch implementation details (template signature + sub-template structure)
- **F-6** — Phase 0 #6 verification DOD + Phase 4 sub-step split for `JobStore.delete` co-delivery

### Detailed findings

(See agent output for F-1 through F-14 detailed Description + Suggested resolution. Will be applied to design doc + this section closed once user ratification gate completes.)

---

## Pass 1 Fitness — closed 2026-05-11

**Date**: 2026-05-11 (resumed from 2026-05-07 break point)
**Owner**: Mr. Radio session (`017dc1cc`)
**Ratification mode**: Per-decision-point cosa-voice `ask_yes_no` notifications routed to action-required UI (per user directive — "push every decision point into the action-required UI"). 1 Minors batch + 8 individual Major walks = 9 firings; all returned `yes`.

### Ratification record

| Turn | Scope | IDs | Result | Resolution applied to 09-design.md |
|---|---|---|---|---|
| 1 | Minors batch | F-8, F-9, F-10, F-11, F-12, F-14 | ✅ yes | F-8: AC7 post-6a baseline capture step; F-9: AC5b ≥12 enumerated sub-table; F-10: Q-B9 renderer-side throttling specified; F-11: Phase 0 #3 target API shape specified; F-12: "mount() is synchronous" addendum in Boot wiring; F-14: AC10e command rewritten to unified `-k "pending_count"` |
| 2 | Individual | F-1 | ✅ yes | AC10b `tts-chrome.css` ceiling corrected from ≤500 → ≤700 per Q-B12 |
| 3 | Individual | F-2 | ✅ yes | AC5 enumerated sub-table added (≥18 cases across 7 clusters; subtotal 21) |
| 4 | Individual | F-3 | ✅ yes | New § "Q-B1 dispatch contract" subsection in Strategic design with template-internal switch contract snippet |
| 5 | Individual | F-4 | ✅ yes | Q-B3 state machine extended with `expired_visual` + `responded_default` vertices; Q-B5 ratified text rewritten with local RAF timer + clock-skew handling; new Phase 0 prerequisite #7 (`countdown_expires_at` payload field) |
| 6 | Individual | F-5 | ✅ yes | AC2d rewritten — grep regex replaced with unit-test contract (`jobstore_delete_api.test.ts`) + tsc check |
| 7 | Individual | F-6 | ✅ yes | Phase 0 prerequisite #6 reworded with sub-step 4A/4B split + DOD tables; new § "Phase 4 sub-step DOD" subsection with explicit `delete()` signature returning `restoreState` closure |
| 8 | Individual | F-7 | ✅ yes | § Inertness-lift contract rewritten — single-write template swap (`replaceChildren`), atomicity contract spec; AC2c rewritten as MutationObserver assertion (count = 1 per widget) |
| 9 | Individual | F-13 | ✅ yes | Q-B9 ratified text amended — state-change events also RAF-coalesced (NOT 100ms throttle); R7 risk row added; AC5b storm-safety case (b) added |

**Convergence re-grep** (run 2026-05-11):
- All 14 findings have applied resolutions traceable in `09-phase6b-interactive-widgets-design.md` via the `Pass 1 F-NN` annotation markers
- No proposed resolution conflicts with another (cross-referenced manually during apply)
- AC5 + AC5b sub-tables provide concrete test contracts; floors hold

### Doc-state delta

| File | Net LOC change | Sections touched |
|---|---|---|
| `09-phase6b-interactive-widgets-design.md` | +~220 LOC | Status header; Strategic design (Boot wiring, Inertness-lift, NEW Q-B1 dispatch contract); Q-B3/B5/B9 ratified texts; AC2c/2d/5/5b/7/10b/10e rows; NEW AC5/AC5b enumeration sub-tables; Risks (NEW R7); Phase 0 prereq list (#3 reword, #6 reword, NEW #7); NEW § Phase 4 sub-step DOD |
| `95-phase6b-review-findings.md` | +~70 LOC (this section) | NEW "Pass 1 Fitness — closed 2026-05-11" subsection |

### Phase 6b cycle state

```
Q-decisions      ✅ CLOSED  (12/12 ratified)        2026-05-07
REUSE pre-pass   ✅ CLOSED  (28 RE + 5 L3 ratified) 2026-05-07
Pass 1 Fitness   ✅ CLOSED  (14/14 ratified, applied) 2026-05-11
Pass 2 Adversarial   ⏳ pending — gated on user go-ahead
Code-execution plan  ⏳ pending
Implementation       ⏳ pending
```

### Resume pointer status

`93-resume-here-phase6b-pass1-ratification.md` is now historical. Pass 2 dispatch will produce its own findings doc section in this file (`95-phase6b-review-findings.md` § "Pass 2 Adversarial — Findings") when the user gives the go-ahead.

---

## Pass 2 Adversarial — Findings (opened 2026-05-11)

**Reviewer**: clean-context Pass 2 Adversarial agent
**Scope**: `09-phase6b-interactive-widgets-design.md` in Pass-1-resolved state
**Cluster focus**: security, DOS, race conditions, contract drift
**Pass 1 findings** (F-1..F-14): considered closed — not re-raised here
**Method**: full doc read + grep verification against shipped code (`stores/ActionRequiredStore.ts`, `stores/JobStore.ts`, `stores/AudioStore.ts`, `render/NotificationsListRenderer.ts`, `render/templates/actionRequiredReadOnly.ts`, `boot.ts`, `shared/types.ts`).

### Findings

| ID | Severity | Cluster | Finding | Recommended resolution |
|----|----------|---------|---------|------------------------|
| A1 | Major | contract-drift | `ActionRequiredStore.respond(idHash, response: string)` is **already optimistic** — flips local state to `responded` BEFORE the API POST, silently swallows network failures. Q-B3 `pending→submitting→responded\|failed` wait-for-response state machine cannot observe a real `failed` transition from the existing store API. | Either (a) extend `ActionRequiredStore` with a non-optimistic `respondAndAwait(idHash, response): Promise<void>` that throws on POST rejection, OR (b) re-ratify Q-B3 to match reality (optimistic with offline-resync). Pick one explicitly. |
| A2 | Major | contract-drift | `ActionRequiredStore.respond()` parameter type is `response: string`. Design AC5 cases (c)/(d)/(e)/(f) pass `[labels]` (array, multiSelect), `{header: value, ...}` (object, open_ended_batch). These will be stringified-by-coercion or fail TS strict-mode. | Tighten `ActionRequiredStore.respond()` signature to `respond(idHash: string, response: string \| ReadonlyArray<string> \| Record<string, string>): Promise<void>` AS PART OF Phase 0 prerequisite check (new prereq #8); update store + tests accordingly. |
| A3 | Major | race | `NotificationsListRenderer.renderActionRequiredSection()` (Phase 5, `NotificationsListRenderer.ts:228-243`) overwrites every action-required widget with `renderActionRequiredReadOnly` via `existing.replaceWith(fresh)` on every non-tick store event (`added`, `responded`, `expired`, `cancelled`, `offline-frozen`, `offline-resumed`). After Phase 6b's interactive mount, ANY of these events nukes the interactive widget back to the read-only template — restoring all 4 inertness markers, destroying user-typed text in `<input>`, dropping listeners. The design's "post-mount targeted-mutation only" contract (L101) is fundamentally incompatible with the existing Phase 5 renderer. | Pick one path: (a) move action-required rendering ENTIRELY to `ActionRequiredRenderer` and have Phase 5's `NotificationsListRenderer.renderActionRequiredSection()` short-circuit when Phase 6b is mounted (introduce a "owner" flag in the section element); (b) replace `renderActionRequiredReadOnly` with the interactive template inside `NotificationsListRenderer` and delete the separate `ActionRequiredRenderer` (KISS); (c) reuse-on-match in `keyedListMerge` (do not call `replaceWith` for already-mounted widgets — patch in place). Each has tradeoffs; design doc MUST pick one before code is written. |
| A4 | Major | contract-drift | Design L80-92 `mount()` snippet uses (a) `widget.querySelectorAll("[data-action-required-id]")` — the actual attribute is `data-id-hash` (`actionRequiredReadOnly.ts:49`); (b) `this.stores.actionRequired.getByDomElement(widget)` — no such method exists (`ActionRequiredStore` has `getById(idHash)` only). An implementer following the doc cold writes code that compiles against fictional API. | Rewrite the snippet to use the real attribute: `widget.querySelectorAll('[data-id-hash]')` + `this.stores.actionRequired.getById(widget.dataset.idHash)`. Tighten AC2c to grep for `data-id-hash` (NOT `data-action-required-id`). |
| A5 | Major | contract-drift | Q-B5 ratified text (L149) says `notification.countdown_expires_at (ISO8601)` and `new Date(...) - Date.now()`. The actual field on `ActionRequiredItem` is `expires_at: number` (ms epoch, `shared/types.ts:344`). `new Date(<number>) - Date.now()` works numerically but the design's claimed ISO8601 type is wrong, AND Phase 0 prerequisite #7 (L342) demands the server add a NEW field `countdown_expires_at` that is **redundant with the existing `expires_at`**. Implementer either (a) writes a noop server change, (b) waits forever for an unneeded field, or (c) types it wrong and crashes on `Date.parse(undefined)`. | Drop Phase 0 prerequisite #7. Rewrite Q-B5 to consume `item.expires_at: number` directly (already present in `ActionRequiredItem`). No server change needed; no `countdown_expires_at` field. |
| A6 | Major | contract-drift | `AudioStore` public interface (`AudioStore.ts:109-119`) exposes `pause()`, `resume()`, `skip()`, `state()`, `queueLength()` — NO `stop()` method. AC5b control-wiring case "stop dispatches stop intent" and Q-B7 "4 controls (Pause/Resume single toggle, Stop, Skip)" + Q-B7 per-notification "2 controls (Pause, Stop)" have no store API to dispatch against. | Either (a) extend `AudioStore` with `stop(): void` (semantic = skip + clear remaining queue + transition to idle) — add as Phase 0 prerequisite #8; (b) re-ratify Q-B7 to drop Stop (keep Pause/Resume/Skip only). The doc does neither; pick one. |
| A7 | Major | contract-drift | Design `boot.ts` snippet at L57-65 calls `actionRequiredRenderer.mount()` and `ttsChromeRenderer.mount()` with no args. Phase 6a's shipped `JobsPaneRenderer.mount(root: HTMLElement): void` REQUIRES a root argument (`JobsPaneRenderer.ts:48, 108`). The inertness-lift snippet at L80-92 also declares `mount(): void` with no params, accessing `this.container`. The factory snippet at L53-65 passes `container` as a factory option. Three different mount-signature contracts in one design doc. | Pick the Phase 6a precedent: factory options carry `container?: HTMLElement` (optional, but resolved), and `mount(root: HTMLElement)` is the canonical surface. OR pick the new "factory-resolves-container" pattern and explicitly document that 6b diverges from 6a's mount signature. AC9 grep guard for the four `:mounted` console lines must align with whichever pattern is picked. |
| A8 | Major | race | Boot ordering (`boot.ts:208-209`) starts `transports.audio` AFTER renderer mounts but BEFORE Phase 6b's `ttsChromeRenderer` exists in the doc's specified sequence. If the new mount calls land at L60-66 of the snippet (after `jobsRenderer.mount()`, before `transports.audio.start`), the chunk-decoded subscription is wired in time. But the design at L62-66 is silent on **insertion point relative to `transports.audio.start`**. If a future refactor reorders, the audio binary handler can fire (and emit `store_audio_chunk_decoded`) before `ttsChromeRenderer` subscribes — chunks arriving during the mount → start window get lost AND a chunk-decoded storm on first connection (legacy notification re-fanout) thrashes the renderer-side RAF coalescer before AC9 grep completes. | Make the ordering invariant explicit in the design: "Both new mounts MUST land AFTER `jobsRenderer.mount()` and BEFORE `transports.audio.start(sessionId, ...)`. AC9 verifies all four `:mounted` lines appear BEFORE any `store_audio_chunk_decoded` console emission." Add a smoke test that asserts ordering. |
| a1 | Minor | security | The interactive template (Q-B1) will inject `notification.options` strings as button/radio/checkbox labels and `notification.prompt` as text. The legacy `html` tagged-template helper (`render/html.ts`) escapes interpolated values — verify this is contractually documented in the design. If a future renderer dev writes `${rawHTML(opt.label)}`, an attacker-controlled `response_options` from a compromised CC session produces XSS. AC tests don't currently grep for unsafe sinks (`.innerHTML =`, `dangerouslySetInnerHTML`, `rawHTML(`). | Add AC2e: grep ban inside `actionRequiredInteractive.ts` and `ttsChrome.ts` for the patterns `.innerHTML =`, `rawHTML(`, `outerHTML =`. The `html` tagged template + DOM `.textContent`/`.value` writes are the only allowed write paths. Document the invariant in the template files' header comments. |
| a2 | Minor | DOS | Q-B5 specifies a local RAF-driven countdown per widget; ratified text says "RAF-driven visible digit with text-node updates throttled to 1/sec". Phase 5's existing `ActionRequiredStore` ALREADY emits `tick` events at 1Hz (`ActionRequiredStore.ts:291` `setInterval(..., 1000)`) AND Phase 5's `NotificationsListRenderer` already mutates `.action-required-countdown` text on each tick (`NotificationsListRenderer.ts:258-259`). Adding a SECOND RAF-driven timer per widget in the new renderer means: 60Hz wakeups × N widgets just to render at 1Hz, doubling the timer cost vs the existing setInterval path. Phone-on-battery + 20 pending prompts = ~1200 idle wakeups/sec for cosmetic UI work. | Reuse the store's existing 1Hz `tick` event for countdown render. Drop the renderer-side RAF loop. If sub-second visual smoothing is desired, use CSS animations (`transition`) instead of JS timers. AC5 countdown-expiry case (line 226) becomes "renderer observes store-emitted tick AND transitions widget to `expired_visual` when store emits `expired` changeKind" — eliminates the dual-timer architecture. |
| a3 | Minor | testability | AC9 grep guard "four stable `:mounted` lines emit in observed order" (L71) doesn't specify the order itself. If the smoke test asserts an order that conflicts with the actual emit sequence (Phase 5: notifications → 6a: jobs → 6b new mounts), CI fails. The design also doesn't say whether `actionRequiredRenderer:mounted` comes before or after `ttsChromeRenderer:mounted`. | Pin the exact order in the AC9 row: `notificationsRenderer:mounted` → `jobsRenderer:mounted` → `actionRequiredRenderer:mounted` → `ttsChromeRenderer:mounted` (alphabetic within new mounts is the simplest stable ordering). Update the smoke test to assert this literal order via grep with `-A` line offsets. |

### Per-finding detail

#### A1 — `ActionRequiredStore.respond()` is already optimistic — Q-B3 wait-for-response unbuildable

**Where**: `09-phase6b-interactive-widgets-design.md:147` (Q-B3 ratified text) + `09-phase6b-interactive-widgets-design.md:280-281` (R1 risk row)
**Cluster**: contract-drift
**Severity**: Major
**Problem**: The shipped `ActionRequiredStore.respond()` (`stores/ActionRequiredStore.ts:182-206`) flips local state to `responded` and emits `store_action_required_changed{changeKind: "responded"}` **before** the `await this.api.post(...)`. The `try/catch` on the POST silently swallows network failures — Phase 4 explicitly punts retry to Phase 6+ (line 204 comment). Q-B3's `pending → submitting → responded | failed` state machine cannot observe a `failed` transition because the store doesn't surface one. The renderer's `respond()` call resolves cleanly even when the network failed; the inline error stripe (Q-B4) will never appear in the wild.
**Falsifiability check**: Network-disconnect the test environment, click Submit on an action-required widget, observe DOM: the design says inline error stripe should appear. Actual behavior: widget transitions to `responded` (server's eventual fanout when reconnected confirms it). AC5 error-rollback cluster (5 cases) fundamentally cannot pass without store changes.
**Recommended resolution**: Extend `ActionRequiredStore` with a non-optimistic `respondAndAwait(idHash, response): Promise<void>` that does NOT flip local state until the POST resolves; reject on POST failure. Phase 6b uses this method exclusively. Add as Phase 0 prerequisite #8. Alternatively, re-ratify Q-B3 to drop the `failed` state and the inline error stripe — accept the optimistic-with-eventual-resync model.

#### A2 — `respond()` accepts only `string` — multi-select and batch shapes are unrepresentable

**Where**: `09-phase6b-interactive-widgets-design.md:223` (AC5 case (d): `respond([labels])`) + L223 case (f): `respond({header: value, ...})`
**Cluster**: contract-drift
**Severity**: Major
**Problem**: `ActionRequiredStore.respond(idHash: string, response: string): Promise<void>` (`stores/ActionRequiredStore.ts:116, 182`). The design's AC5 cases require passing an array (multiSelect checkboxes) or an object (open_ended_batch responses). TypeScript strict mode rejects this at compile time; implementer either widens the signature (which requires changing Phase 4 store + tests) or stringifies (which loses information for the server). The POST body shape on the wire is also unspecified: server receives `{notification_id, response_value: {response: <coerced>}}` regardless. If the server expects a structured `response_value`, multi-select round-trips as a comma-joined string and the server-side handler parses it wrong.
**Falsifiability check**: tsc compile fails when AC5 cases (c-f) are translated to test code. Or: tsc passes via implicit any/cast and the unit test green-lights a wrong serialization.
**Recommended resolution**: Phase 0 prerequisite #8 — extend signature to `respond(idHash: string, response: string | ReadonlyArray<string> | Record<string, string>): Promise<void>`; verify server-side `/api/notify/response` handler accepts the structured shape; update existing Phase 4 unit tests to cover the new branches; update the design's POST body shape table (which currently does not exist — add one).

#### A3 — Phase 5 renderer overwrites Phase 6b interactive widget on every store event

**Where**: `render/NotificationsListRenderer.ts:228-243` (renderActionRequiredSection) + `render/NotificationsListRenderer.ts:262-266` (onActionRequiredChange) versus `09-phase6b-interactive-widgets-design.md:101` (post-mount targeted-mutation contract)
**Cluster**: race
**Severity**: Major
**Problem**: Phase 5's `NotificationsListRenderer` subscribes to `store_action_required_changed` and routes any non-tick changeKind to `renderActionRequiredSection`, which uses `keyedListMerge` with `update: existing.replaceWith(fresh)` where `fresh` is `renderActionRequiredReadOnly(...)` — a **read-only** widget with all 4 inertness markers restored. After Phase 6b's `ActionRequiredRenderer.mount()` swaps to interactive: any incoming `added`/`responded`/`expired`/`cancelled`/`offline-frozen`/`offline-resumed` event from the store nukes the interactive widget back to read-only. User-typed `<input>` text vanishes. Listeners attached by 6b are lost (they were on the old DOM node, now garbage-collected). The 6b state machine breaks because the DOM no longer matches the state. This is THE most likely runtime bug — the design assumes 6b owns the widget DOM, but Phase 5 still actively rewrites it.
**Falsifiability check**: Open dev, mount Phase 6b interactively, click a partial answer (e.g., type half a response in `open_ended`), then simulate an `offline-frozen` event from another widget. The typed text disappears as Phase 5 re-renders the whole section. Or: in a smoke test, after `mount()`, fire `store_action_required_changed{changeKind: "added"}` for a sibling widget and assert that the target widget retains its interactive DOM. Will fail.
**Recommended resolution**: One of three paths (pick explicitly, add to design):
- **Path A**: Add ownership flag — `NotificationsListRenderer.renderActionRequiredSection()` early-returns when `this.actionRequiredMount.dataset.phase6bOwner === "true"`; Phase 6b's renderer sets this flag at mount, owns the section thereafter, and replicates Phase 5's added/expired/cancelled rendering itself.
- **Path B**: Replace `renderActionRequiredReadOnly` call inside `NotificationsListRenderer` with a conditional that picks `renderActionRequiredInteractive` after 6b mount. Drop the separate `ActionRequiredRenderer` factory. Simpler but tighter coupling.
- **Path C**: Switch `keyedListMerge` to reuse-on-match (don't `replaceWith`, patch in place). Requires the read-only template to expose a "patch" function. More refactoring of Phase 5 code but preserves separation.

This MUST be picked before any 6b implementation code is written.

#### A4 — Mount snippet uses fictional attribute and method names

**Where**: `09-phase6b-interactive-widgets-design.md:80-92` (Mechanism (concrete) snippet)
**Cluster**: contract-drift
**Severity**: Major
**Problem**: The snippet at L81 uses `widget.querySelectorAll<HTMLElement>("[data-action-required-id]")`. The shipped template (`render/templates/actionRequiredReadOnly.ts:49`) sets `data-id-hash`, NOT `data-action-required-id`. The snippet at L82 calls `this.stores.actionRequired.getByDomElement(widget)` — no such method exists on `ActionRequiredStore` (`stores/ActionRequiredStore.ts:113-119` lists `list()`, `getById()`, `respond()`, `disposeForTesting()` only). An implementer copying the snippet writes TypeScript that fails compile; OR worse, declares the missing API on a local interface, casts it through, and gets a runtime TypeError when `getByDomElement(...)` is `undefined`.
**Falsifiability check**: `grep -rn "data-action-required-id" src/fastapi_app/static/js/multiplexer/` returns zero matches. `grep -n "getByDomElement" src/fastapi_app/static/js/multiplexer/stores/ActionRequiredStore.ts` returns zero matches.
**Recommended resolution**: Rewrite the snippet:
```ts
const widgets = this.container.querySelectorAll<HTMLElement>('[data-id-hash]');
for (const widget of widgets) {
    const idHash = widget.dataset.idHash;
    if (!idHash) continue;
    const item = this.stores.actionRequired.getById(idHash);
    if (!item) continue;
    // ... existing template-swap logic
}
```
Tighten AC2c MutationObserver assertion to also grep for `data-id-hash` (the real attribute). Strike all references to `data-action-required-id` and `getByDomElement` from the design.

#### A5 — Phase 0 prerequisite #7 demands a redundant server field

**Where**: `09-phase6b-interactive-widgets-design.md:342` (Phase 0 #7) + L149 (Q-B5 ratified text)
**Cluster**: contract-drift
**Severity**: Major
**Problem**: Q-B5 says `notification.countdown_expires_at (ISO8601)` and the renderer computes `new Date(...) - Date.now()`. The actual `ActionRequiredItem.expires_at: number` (`shared/types.ts:344`, ms epoch) is already exposed via the store. The template at `actionRequiredReadOnly.ts:61` already sets `data-countdown="${item.expires_at}"` — so the data is on the DOM today. Phase 0 prerequisite #7 demands CoSA add a brand-new `countdown_expires_at: ISO8601 string` field that is semantically identical to the existing `expires_at: number`. Implementer either (a) blocks 6b on a CoSA change that adds redundant data; (b) writes `Date.parse(item.countdown_expires_at)` which is `NaN` when the field is undefined (TS strict permits because the design typed it as `string | null`); (c) fixes the design but the design says ISO8601 and prereq #7 still claims server-side work is pending.
**Falsifiability check**: `grep -n "countdown_expires_at\|expires_at" src/fastapi_app/static/js/multiplexer/shared/types.ts` returns `expires_at: number` for both `ActionRequiredItem` and the notification interface; zero hits for `countdown_expires_at`. Confirmed redundant.
**Recommended resolution**: Strike Phase 0 prerequisite #7. Rewrite Q-B5 ratified text to consume `item.expires_at` directly (already typed as `number`, ms epoch). The local timer computes `Math.max(0, item.expires_at - Date.now())`. No server change needed; this finding closes Phase 0 prereq #7 without action.

#### A6 — `AudioStore.stop()` does not exist; AC5b control-wiring case is unbuildable

**Where**: `09-phase6b-interactive-widgets-design.md:156` (Q-B7) + L240 (AC5b control-wiring case "stop dispatches stop intent")
**Cluster**: contract-drift
**Severity**: Major
**Problem**: `AudioStore` public interface (`stores/AudioStore.ts:109-119`) exposes `pause()`, `resume()`, `skip()`, `state()`, `queueLength()`, `binaryHandler`, `disposeForTesting()`. There is no `stop()` method. Q-B7 ratification specifies "Pane chrome: 4 controls (Pause/Resume single toggle, Stop, Skip)" and per-notification "2 controls (Pause, Stop)". AC5b control-wiring requires "stop dispatches stop intent". There is nothing to dispatch against. Implementer either (a) extends `AudioStore` with a method that wasn't in the design; (b) maps `Stop` → `skip()` (which only advances ONE chunk and does not clear the queue, so the UX is wrong); (c) ships a non-functional Stop button.
**Falsifiability check**: `grep -n "stop\s*(" src/fastapi_app/static/js/multiplexer/stores/AudioStore.ts` returns zero method definitions; only test-helper `disposeForTesting()`. Confirmed missing.
**Recommended resolution**: Either (a) extend `AudioStore` with `stop(): void` whose semantics are: transition to idle, clear remaining queued chunks, do not auto-resume on next chunk. Add as Phase 0 prerequisite #8; (b) re-ratify Q-B7 to drop Stop (Pane chrome = Pause/Resume + Skip; per-notification = Pause only). Either choice is fine; the doc currently does neither, leaving an unbuildable AC.

#### A7 — Three conflicting `mount()` signatures in one design doc

**Where**: `09-phase6b-interactive-widgets-design.md:52-66` (Boot wiring snippet, no-arg) + L80-92 (Mechanism snippet, no-arg accessing `this.container`) versus shipped `render/JobsPaneRenderer.ts:48, 108` (`mount(root: HTMLElement): void`)
**Cluster**: contract-drift
**Severity**: Major
**Problem**: The boot snippet calls `actionRequiredRenderer.mount()` and `ttsChromeRenderer.mount()` with zero args. The inertness-lift snippet declares `mount(): void` accessing `this.container`. The Phase 6a precedent ships `mount(root: HTMLElement): void` taking the root explicitly. The factory snippet at L53-55 passes `container: document.querySelector('#action-required-pane')` as a factory option. The design implies the factory pre-resolves the root and stores it on the instance, diverging from the Phase 6a pattern WITHOUT calling out the divergence. Implementer either follows 6a (and the boot snippet fails to compile) or follows the new shape (and AC9 + Phase 5 wiring + the mount-idempotency Pass 1 F-26 contract from Phase 6a all need adjustment).
**Falsifiability check**: Try implementing the design literally — `mount()` no-arg conflicts with the existing `RendererBase` shape used in `boot.ts:192, 204`.
**Recommended resolution**: Pick the Phase 6a precedent: factory takes neither `container` nor `apiClient` for `ttsChromeRenderer`, and `mount(root: HTMLElement)` is the canonical surface. Boot wiring resolves the root explicitly: `const root = document.getElementById('tts-pane'); if (root === null) throw ...; ttsChromeRenderer.mount(root);`. Update all three snippets in the design to match. AC9 grep guard verifies the four `:mounted` lines in their canonical order (see a3).

#### A8 — Boot ordering invariant silent on new-mount placement vs `transports.audio.start`

**Where**: `09-phase6b-interactive-widgets-design.md:50-67` (Boot wiring section)
**Cluster**: race
**Severity**: Major
**Problem**: The design says "Add two factory calls to `boot.ts` after the existing `notificationsRenderer` + `jobsRenderer` mount lines" but is silent on placement relative to `transports.audio.start(sessionId, stores.audio.binaryHandler)` at `boot.ts:209`. The audio transport, once started, can immediately emit `store_audio_chunk_decoded` events (on cached audio replay during reconnect, or on the legacy WebSocket re-fanout of in-flight chunks). If `ttsChromeRenderer.mount()` lands AFTER `transports.audio.start`, the first wave of chunk-decoded events fires before the renderer subscribes — chunks are dropped from the chrome display. Even worse, AC9's smoke test could grep four `:mounted` lines BEFORE the `boot_complete` JSON emission while `transports.audio.start` is firing chunk events concurrently — racing the test assertion. The "audio chunk-storm on first connect" pattern is exactly the DOS surface that R2/R7 + AC5b storm-safety care about; mounting late means the renderer never sees the storm and AC5b passes hollowly.
**Falsifiability check**: Reorder `transports.audio.start` to land BEFORE the mount calls in a local branch, observe that chunk events fire pre-mount → renderer never logs them → AC5b storm test green-lights despite the drop.
**Recommended resolution**: Pin the order in the design:
```ts
// Order: renderers FIRST, transports LAST
notificationsRenderer.mount(...);
jobsRenderer.mount(...);
actionRequiredRenderer.mount(...);   // NEW — must precede transports.audio.start
ttsChromeRenderer.mount(...);         // NEW — must precede transports.audio.start
attachLifecycleListeners();
transports.queue.start(sessionId);
transports.audio.start(sessionId, stores.audio.binaryHandler);
```
Add AC9b: smoke test asserts the four `:mounted` console lines appear BEFORE the first `store_audio_chunk_decoded` event in the captured console log. Add a comment in `boot.ts` documenting the ordering invariant so a future reorder is caught at code review.

#### a1 — Tagged-template escape contract not asserted by AC

**Where**: `09-phase6b-interactive-widgets-design.md:111-125` (Q-B1 dispatch contract template signature) + § "Test pyramid" / AC2/AC3
**Cluster**: security
**Severity**: Minor
**Problem**: The interactive template interpolates server-controlled `notification.prompt`, `notification.response_options` array elements, and (for `open_ended_batch`) per-question headers as text. The `html` tagged-template helper (`render/html.ts`) escapes interpolated values via `.textContent` for string slots. But the design does not assert this escape contract anywhere in AC2/AC3/AC5. A future PR that ports a legacy template using `.innerHTML = ...` or introduces a `rawHTML(...)` companion to the `html` helper opens an XSS hole: a compromised CC session emitting `response_options: ["<img src=x onerror=...>"]` becomes script execution. The risk is real because `action_required` payloads originate from agents (server-side LLM output is one path; another is the proxy auto-answer infrastructure that already routes through user-supplied content).
**Falsifiability check**: After implementation, manually feed an `action_required` notification with `response_options: ['<img src=x onerror=alert(1)>']` via the integration harness; assert the rendered DOM has zero `<img>` elements created from the option strings, AND that the literal `<img ...>` text shows up as a textContent string in the button label. Or: grep ban `.innerHTML\s*=`, `outerHTML\s*=`, `rawHTML\b` in the new template files at AC time.
**Recommended resolution**: Add AC2e: `npx eslint --rule 'no-restricted-syntax: [error, "*[name=innerHTML]"]' src/fastapi_app/static/js/multiplexer/render/templates/actionRequiredInteractive.ts src/fastapi_app/static/js/multiplexer/render/templates/ttsChrome.ts` (or equivalent grep guard). Document the escape contract in the file header comment of both new template files: "All server-controlled string interpolation MUST flow through the `html` tagged-template helper. Direct `.innerHTML =`/`outerHTML =`/`rawHTML(...)` writes are prohibited."

#### a2 — Dual countdown timers per widget (store setInterval + renderer RAF) doubles wakeup cost

**Where**: `09-phase6b-interactive-widgets-design.md:149` (Q-B5 ratified text: "Local RAF-driven countdown")
**Cluster**: DOS
**Severity**: Minor
**Problem**: Phase 5's `ActionRequiredStore` already emits `tick` events at 1Hz per widget via `setInterval(..., 1000)` (`stores/ActionRequiredStore.ts:291`). Phase 5's `NotificationsListRenderer` already mutates the `.action-required-countdown` text-node on each tick (`render/NotificationsListRenderer.ts:258-259`). Q-B5 specifies an ADDITIONAL renderer-side RAF loop in Phase 6b that fires at 60Hz (browser RAF cadence) to throttle visible-digit updates to 1/sec. For 20 active prompts on a low-power device, that's 20 × 60 = 1200 RAF wakeups per second just to render at 1Hz — when the store is already doing the work. The RAF loop is also "always-on" between `mount()` and `unmount()`, even when no prompt is in the countdown-active state.
**Falsifiability check**: Open DevTools Performance tab, mount Phase 6b with 20 pending action-required widgets, observe RAF callback count over 10 seconds. With the store-tick approach it's ~20 callbacks. With the proposed RAF loop it's ~12000.
**Recommended resolution**: Reuse the store's existing `tick` event for countdown render. Drop the renderer-side RAF loop entirely. Q-B5 expiration transition becomes: "renderer observes `store_action_required_changed{changeKind: 'tick'}` and on each tick where `countdownMs === 0`, transitions widget to `expired_visual`." If sub-second smoothing is desired, use a CSS `transition: ... 1s linear` on the countdown text — pure declarative, zero JS wakeups.

#### a3 — AC9 grep guard lacks explicit emit order

**Where**: `09-phase6b-interactive-widgets-design.md:71` (AC9 description) + L204 (AC9 table row)
**Cluster**: testability
**Severity**: Minor
**Problem**: AC9 says "boot_complete handshake — 4 stable lines (`notifications` + `jobs` + `actionRequired` + `ttsChrome` all `:mounted`)" but doesn't pin the ORDER. The smoke test could grep `-c` for "4 occurrences" and pass even if Phase 6b emits them in a non-deterministic order, masking a real ordering bug (see A8). Phase 6a's AC9 only had two lines so order was implicit; with four, ordering becomes load-bearing.
**Falsifiability check**: Reorder the mount calls in `boot.ts` (e.g., swap actionRequired and ttsChrome), observe AC9 still green. Real bug: a TtsChromeRenderer that mounts BEFORE ActionRequiredRenderer subscribes to a shared bus event that the action-required renderer mutates → races. Test should catch the reorder.
**Recommended resolution**: Tighten AC9 to assert literal order: `notificationsRenderer:mounted → jobsRenderer:mounted → actionRequiredRenderer:mounted → ttsChromeRenderer:mounted`. Implement via Python `re.search` on the captured console log with named groups and offset comparison, OR via `grep -n` + line-number comparison. The order is `(Phase 5, Phase 6a, alphabetic-within-6b)` — stable rule.

### Noted out-of-scope

- The shipped `ActionRequiredStore` auto-expires LOCALLY without POSTing the default (`ActionRequiredStore.ts:310-318`, Q3 ratification from Phase 4). Phase 6b's `expired_visual` state per Q-B5 + A5 maps onto the store's existing `expired` changeKind cleanly once A5 is applied. Not a Pass 2 finding per se; flagged here so the integration is intentional rather than accidental.
- The `safeStringifyMeta` helper from Phase 6a Pass 2 F20 (256KB meta cap, ConfigurationManager-sourced) does not appear to apply to Phase 6b widgets directly (no meta-display path in action-required or TTS chrome). If Phase 6c introduces meta display for action-required prompts, the cap should be re-asserted there.
- Phase 5's `NotificationsListRenderer.tick` text-node-only contract (D-H purity invariant per `NotificationsListRenderer.ts:8`) is the right precedent for Phase 6b's post-mount targeted-mutation contract (design L101). Consider citing it in the design to anchor the convention.

---

## Pass 2 Adversarial — closed 2026-05-11

All 11 Pass 2 Adversarial findings ratified via cosa-voice action-required UI per Phase 6a Pass 2 precedent (8 Majors walked individually + 1 Minors batch + 1 re-frame on A3 + 1 split-vote on Minors batch where user requested a2 explanation). All resolutions applied to `09-phase6b-interactive-widgets-design.md`.

### Ratification record

| ID | Cluster | Severity | Decision | Applied at |
|----|---------|----------|----------|------------|
| **A1** | contract-drift | Major | **Path A** — Add `ActionRequiredStore.respondAndAwait()` non-optimistic method (Phase 0 prereq #8) | Q-B3 row + Phase 0 #8 |
| **A2** | contract-drift | Major | **YES** — Widen `respond()` signature to `string \| ReadonlyArray<string> \| Record<string, string>` (Phase 0 prereq #9) + new POST body shape table | New Cluster 1 sub-section + Phase 0 #9 |
| **A3** | race | Major | **Path A** — Ownership flag `dataset.phase6bOwner` on Phase 5 short-circuit | Mechanism snippet + new Ownership-flag paragraph + R8 risk row |
| **A4** | contract-drift | Major | **YES** — Rewrite Mechanism snippet to use `data-id-hash` + `getById()` (real names) | Mechanism snippet |
| **A5** | contract-drift | Major | **YES** — Strike Phase 0 prereq #7; consume `item.expires_at: number` directly | Q-B5 row + Phase 0 #7 STRUCK |
| **A6** | contract-drift | Major | **Path A** — Extend `AudioStore` with `stop(): void` (Phase 0 prereq #10) | Q-B7 row + Phase 0 #10 |
| **A7** | contract-drift | Major | **YES** — Align all three mount signatures to Phase 6a precedent (`mount(root: HTMLElement)`, no `container` factory option) | Boot wiring snippet + Mechanism snippet + Q-B11 row |
| **A8** | race | Major | **YES** — Pin boot order (renderers first, transports last) + AC9b smoke test + boot.ts ordering comment | Boot wiring snippet + new AC9b row + R9 risk row |
| **a1** | security | Minor | **YES** — New AC2e grep ban on `.innerHTML =` / `rawHTML(` / `.outerHTML =` in interactive template files | AC2e row |
| **a2** | DOS | Minor | **YES** — Drop renderer-side RAF loop; reuse store's existing 1Hz `tick` event for countdown render | Q-B5 row + AC5 enumeration countdown case |
| **a3** | testability | Minor | **YES** — Pin AC9 mount order: notifications → jobs → actionRequired → ttsChrome (alphabetic-within-6b) | AC9 row |

### Cycle state delta

| Pass | Status before | Status after | Notes |
|------|---------------|--------------|-------|
| Q-decisions | ✅ CLOSED 12/12 (2026-05-07) | unchanged | |
| REUSE pre-pass | ✅ CLOSED 28 RE + 5 L3 (2026-05-07) | unchanged | |
| Pass 1 Fitness | ✅ CLOSED 14/14 (2026-05-11) | unchanged | |
| **Pass 2 Adversarial** | ⏳ pending | **✅ CLOSED 11/11 (2026-05-11)** | this section |
| Code-execution plan | ⏳ | **⏳ READY TO AUTHOR** — gated on user go-ahead | unblocks next |
| Implementation | ⏳ | unchanged | |

### Phase 0 prerequisites — net change

| # | Status | Source |
|---|--------|--------|
| 1 | unchanged | `DELETE /api/queue/<bucket>/<id>` |
| 2 | unchanged | `multiSelect` flag on `action_required` payload |
| 3 | unchanged | `AudioStore` notification linkage |
| 4 | unchanged | action-required mount surface |
| 5 | unchanged | CoSA `multiplexer_config.py` commit |
| 6 | unchanged | `JobStore.delete(idHash)` method |
| **7** | **STRUCK** (Pass 2 A5) | ~~`countdown_expires_at` server field~~ — redundant; use existing `expires_at: number` |
| **8** | **NEW** (Pass 2 A1) | `ActionRequiredStore.respondAndAwait()` method |
| **9** | **NEW** (Pass 2 A2) | Widen `respond()` signature to `string \| ReadonlyArray<string> \| Record<string, string>` |
| **10** | **NEW** (Pass 2 A6) | `AudioStore.stop(): void` method |

### Edit zones applied (this closure)

| # | Zone | Findings addressed |
|---|------|---------------------|
| 1 | Status header (L4) | Pass 2 closure status banner |
| 2 | Boot wiring snippet (L50-67 → expanded) | A7 + A8 |
| 3 | Mechanism snippet (L77-92 → expanded) | A4 + A7 + A3 (Path A ownership flag) |
| 4 | Q-B3 row | A1 (reference `respondAndAwait`) |
| 5 | Q-B5 row | A5 + a2 (use `expires_at` + reuse tick event) |
| 6 | Q-B7 row | A6 (reference `AudioStore.stop()`) |
| 7 | Q-B11 row | A7 (no `container` factory option) |
| 8 | New POST body shape table (after Cluster 1) | A2 |
| 9 | AC2e row (NEW) | a1 |
| 10 | AC9 row | a3 (pinned canonical order) |
| 11 | AC9b row (NEW) | A8 |
| 12 | AC5 enumeration countdown case | a2 |
| 13 | Phase 0 prereqs (#7 STRUCK, #8/#9/#10 NEW) | A1 + A2 + A5 + A6 |
| 14 | R8 risk row (NEW) | A3 |
| 15 | R9 risk row (NEW) | A8 |

### Convergence re-grep (verified 2026-05-11)

| Pattern | Expected | Actual |
|---------|----------|--------|
| `data-action-required-id` (struck per A4) | 0 hits | ✅ 0 hits |
| `getByDomElement` (struck per A4) | 0 hits | ✅ 0 hits |
| `countdown_expires_at` (struck per A5) | hits ONLY in struck/historical context | ✅ 2 hits, both struck/historical (Q-B5 "NO new server `countdown_expires_at` field" + prereq #7 STRUCK paragraph) |
| `respondAndAwait` (added per A1) | ≥1 hit | ✅ 6 hits |
| `AudioStore.stop` / `.stop()` (added per A6) | ≥1 hit | ✅ 2 hits |
| `data-id-hash` (added per A4) | ≥1 hit | ✅ 1 hit (Mechanism snippet) |
| `phase6bOwner` (added per A3 Path A) | ≥1 hit | ✅ 3 hits (Mechanism snippet + ownership-flag paragraph + R8 row) |
| `AC9b` (added per A8) | ≥1 hit | ✅ 5 hits |
| `AC2e` (added per a1) | ≥1 hit | ✅ 1 hit |
| `Pass 2 A[0-9]\|Pass 2 a[0-9]` (cross-refs) | ≥10 hits | ✅ 21 hits |

**Convergence verdict**: ✅ all strikes clean (the 2 `countdown_expires_at` hits are intentional documentation of the strike); all additions present; cross-reference density adequate for future audit trail.

### Plan-review pipeline status

```
1. Q-decision walkthrough         ✅ CLOSED 2026-05-07
2. REUSE pre-pass                  ✅ CLOSED 2026-05-07
3. Pass 1 Fitness                  ✅ CLOSED 2026-05-11
4. Pass 2 Adversarial              ✅ CLOSED 2026-05-11 (this section)
5. Code-execution plan             ⏳ READY TO AUTHOR — gated on user go-ahead
6. Implementation                  ⏳ pending code-execution plan
```

### Resume pointer

The next gate is **code-execution plan authoring**: `<date>-phase6b-code-execution-plan.md`. Per Phase 6a precedent (`2026.05.06-phase6a-code-execution-plan.md`), this document includes:
- Per-phase progress table (Phase 0 prereqs → Phase 1 templates → Phase 2 action-required renderer → Phase 3 TTS chrome renderer → Phase 4 delete-button wiring → Phase 5 CSS port → Phase 6 smoke + regression → Phase 7 E2E scheduled-`:8000`)
- AC scorecard (AC1 through AC11b, including new AC2d / AC2e / AC9b)
- Commit-chain table

User gate ratifies the code-execution plan before Phase 0 prereq work begins. Phase 6b implementation Phase 0 starts with the 4 new CoSA-side prereqs (#8 respondAndAwait, #9 widen respond signature, #10 AudioStore.stop, plus the pre-existing #1-#6) before any 6b client code is written.
