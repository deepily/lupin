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
