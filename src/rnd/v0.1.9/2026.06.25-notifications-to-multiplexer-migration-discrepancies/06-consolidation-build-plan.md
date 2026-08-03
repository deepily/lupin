# Multiplexer ↔ Legacy-Notifications Parity — Consolidation Build Plan (DRAFT)

**Date**: 2026-07-01
**Status**: 🟢 **§7 RULED** (Rick, 2026-07-01, María-facilitated walkthrough) + **sanity-checked** (María) — ready for cascaded `/plan-review` (Tiberius spins the review team; María stewards)
**Supersedes**: `../2026.07.01-mux-parity-consolidated-decision-brief.md` (ratified decisions now baked in)
**Home**: this migration-discrepancies directory (`00-index.md` → `05-build-plans/`); this is the master consolidation plan (`06`).
**Provenance**: Live side-by-side session (Claude-in-Chrome), multiplexer `:7999/app/multiplexer` vs legacy `:7999/app/notifications`, DOM-order extraction + code archaeology. Prior tracking: the sibling docs in this directory + the `../2026.07.01-*` verdict docs.

> Terminology note: in prose we say "multiplexer" (not "mux"); file/path/test-ID references keep their literal `mux`/`multiplexer` tokens.

---

## 1. Ratified decisions (Rick, 2026-07-01)

- **D1 — Scope**: finish **and prove** the **6 built accordions** only. NOT the 7 absent panels (Q&A, Submit Agentic Jobs, Filter Settings, Time Saved, System Status, Direct TTS, Debug), NOT a full 13/13 port.
- **D2 — Skin**: **revert the modern reskin → legacy uniform-light look.** No dark chrome, no emerald palette, no glyph-only persona badges.
- **D3 — Menu bar (`lupin-nav`)**: **DROPPED** — present after all (`NavBarRenderer` mounts it; `multiplexer.html:56`).
- **Acceptance**: user-driven side-by-side drive-by **after** implementation (not before).

## 2. Scope boundary — the 6 accordions

| # | Accordion | Multiplexer element | Legacy element | Completion (from Jul-1 tracking) |
|---|---|---|---|---|
| 1 | Action Required | `#action-required-section` | `#action-required-section` | PARTIAL (relocated, headerless, 2px border) |
| 2 | Playing / TTS | `#tts-pane` | `#tts-queue-section` | PARTIAL (transport chrome only) |
| 3 | CC Notifications | `#notifications-pane` | `#section-notifications` | IN-FLIGHT (B1–B5) |
| 4 | Fleet Status | `#fleet-status-pane` | `#section-fleet-status` | DONE (191/191 unit) — prove only |
| 5 | Task List | `#task-list-pane` | `#section-task-list` | DONE (superset) — prove only |
| 6 | Jobs / Job Queues | `#jobs-pane` | `#section-queues` | PARTIAL (display only) |

---

## 3. Lane 0 — Accordion-frame defects (highest-visibility; block the oracle)

### Lane 0a — Accordion header chrome (absent on ALL panes)
**Defect**: no gradient `.section-header` bar / toggle affordance on any multiplexer accordion. The `action-required-section` renders with an empty heading — the smoking gun.
**Root cause (two-part)**:
- CSS: the `.section-header` cluster + per-section gradient variants live in legacy-only `notifications.css` (base `126–177`; gradient variants e.g. `394/514/2951`). The multiplexer links `shared/notifications-surface.css` (has `.collapsible-section` L98 + some gradients) but **not** the header-bar cluster.
- Markup: the 6 pane renderers emit bodies, not a uniform `.section-header` bar.
**ACs**:
1. Port `.section-header` + `.toggle-button` + per-section gradient header variants (LEGACY LIGHT values) into a shared/multiplexer stylesheet linked by `multiplexer.html`.
2. Each of the 6 renderers emits a gradient header bar (icon + title + count + `cursor:pointer` + collapse chevron), class-compatible with the legacy `.section-header` contract.
   - Targets: `NotificationsHeaderRenderer.ts` / `NotificationsListRenderer.ts`, `ActionRequiredRenderer.ts`, `TtsChromeRenderer.ts`, `JobsPaneRenderer.ts`, `FleetStatusRenderer.ts`, `TaskListRenderer.ts` (+ matching `render/templates/*`).
3. Collapse chevron toggles `data-collapsed` (session-only, legacy parity — see `taskListCollapse.ts`, `NotificationsListRenderer.toggleSenderCard`).
4. 100% L/B/F on all touched renderers/templates.

### Lane 0b — Layout-mode toggle (vertical ⇄ horizontal) produces no reflow
**Observed**: clicking the toggle lights the icon but the accordion set never reflows.
**Code state**: handler IS wired — `ReadingPaneRenderer.ts:181` (`onToggleClick`), `:354` (`store.toggleLayoutMode()`), `:240–241` (`body[data-layout-mode]=mode`). `reading-pane.css` gates all horizontal rules on `body[data-layout-mode="horizontal"]` AND `.content-shell.pane-open` (L117–123); pane-closed horizontal is "visually identical to vertical" **by design** (L116 comment).
**Interpretation**: likely a **semantic gap**, not (only) a dead handler — the built feature is "reading-pane-on-the-right, inert until a pane opens," whereas the expectation is "the whole accordion set reflows horizontally." Legacy uses the same left-column + reading-pane model, so parity target needs confirmation.
**ACs** (Q1 RULED — match legacy's TWO modes: **centered** = vertical icon-strip toolbar; **horizontal** = center content shifted right + abstracts + action-required widgets shown):
1. Repro + root-cause: confirm `toggleLayoutMode()` fires + `data-layout-mode` flips at runtime (rule out stale `dist/`).
2. Implement BOTH modes faithfully to legacy: (a) centered/standardized with the vertical icon-strip toolbar; (b) horizontal with center content moved to the right + abstracts + action-required widgets displayed. Legacy is the exact parity target.
3. ▭/⊞ grid `layout-mode-btn`: in scope ONLY if legacy has it working; otherwise out of scope.
4. 100% L/B/F on `ReadingPaneRenderer` + reflow CSS.

### Lane 0c — Accordion ordering & default-visibility
**Observed order (DOM):** multiplexer = CC-Notifications, Action-Required(nested), Jobs, TTS, Fleet, Task. Legacy default-visible = Action-Required, Playing, CC-Notifications, Fleet, Task (Job-Queues hidden).
**Target order for the 6** (legacy relative sequence):
`Action Required → Playing/TTS → CC Notifications → Fleet Status → Task List → Job Queues(hidden)`
**Root cause**: div order in `multiplexer.html` (boot.ts mounts into fixed ids, so DOM-div order = visual order; reordering divs does NOT touch mount sequence / F13 invariant).
**Concrete edits (`multiplexer.html`)**:
1. Extract `#action-required-section` (currently nested ~L147 inside the notifications region) into a standalone **leading** accordion.
2. `#tts-pane` (L172) → position 2 and **remove `hidden`** (legacy shows Playing).
3. `#notifications-pane` (L141) → position 3.
4. `#fleet-status-pane` (L185) → 4; `#task-list-pane` (L192) → 5.
5. `#jobs-pane` (L155) → 6 and **add `hidden`** (legacy hides Job Queues by default) — pending Q3.
**ACs**: DOM order + default-visibility match legacy; F13 mount invariant preserved; section-toolbar toggle state stays consistent with new default-visibility.

## 4. Lane 1 — Finish accordion functionality

- **CC Notifications (B1–B5)**: section reorder (→ Lane 0c), Recent-Activity re-nest, per-message TTS chrome, visual polish. Plans: `05-build-plans/01-cc-session-B1-B5.md`.
- **Jobs**: add deferred mutations — delete / delete-all / retry / time-window / pagination / filter-badge. Plan: `05-build-plans/04-job-queues-mutation-gaps.md`. Targets: `JobsPaneRenderer.ts`, `templates/jobBucket.ts`, `jobCard.ts`.
- **TTS Audio**: per-item queue list, Clear-all, focus-resume (only transport chrome exists). Plan: `05-build-plans/03-tts-queue-full-restore.md`. Targets: `TtsChromeRenderer.ts`, `templates/ttsChrome.ts`.
- **Fleet Status / Task List / Recent Activity**: verify-only (functionally complete).

## 5. Lane 2 — Skin revert (modern → legacy light)

| Divergence | Anchor(s) | Revert target |
|---|---|---|
| Emerald/Tailwind greens (Playing/TTS) | `tts-chrome.css:61,147,149,153` (`#34d399/#10b981/#059669`) | legacy Bootstrap greens (map from `notifications.css`) |
| Emerald greens + border (Action Required) | `action-required.css:89,178,180,184` | legacy filled bar + Bootstrap green |
| AR 2px border → 3px filled bar | `action-required.css` (border rules) | legacy `#action-required-section .section-header` (`notifications.css:514`) |
| Glyph-only persona badge (R4) | `templates/senderCard.ts`, `notifications-list.css` | inline icon **+ name** (legacy) |
| Dark chrome (broadcast/focus bar, any dark bg) | sweep `css/multiplexer/*` for dark hexes | legacy light surfaces |

**ACs**: no dark-surface or emerald declarations remain on the 6 accordions; persona badge shows inline icon+name; AR uses filled bar; visual-regression golden rebaselined against **legacy** (not self).

## 6. Lane 3 — Prove

- **Layout-Parity Oracle Tier-2 (computed-style, the core skin/row-style proof) + Tier-3 (geometry ±1px frame proof)** vs legacy golden — now includes header + ordering geometry (unblocked by 0a/0c). Methodology: `../2026.06.19-multiplexer-layout-parity-methodology/`. *(Tier↔concern mapping per the harness `test_tier2_tier3.py:1-3/128/179` — Tier-2 = computed-style isomorphism "core proof"; Tier-3 = geometry. See §7 Q4 correction.)*
- **Functional unit tests** at **100% L/B/F** (`pytest --cov --cov-fail-under=100`; TS `c8 --100`) per the 100% Coverage Mandate.
- **Trackers to close**:
  - **H2** env-label + live clock — scaffolding exists (`NotificationsHeaderRenderer.ts:102–201`, `#env-label`/`#clock`); wire `sys_time_update` frame + verify render (not greenfield).
  - **R5** session topic — field + template exist (`shared/types.ts:475`, `senderCard.ts:161`), but `.sender-session-name` renders empty; wire the population path (`session_topic` control → `SenderStore` → `SenderRecord.session_name`).
- **Rebuild compiled `dist/`** — several gaps may be "source exists, build stale"; rebuild + confirm shipped before proving.
- **Venue routing**: :7999 for unit + inline smoke; **:8000 scheduled** (`POST /api/test-suite/submit`) for E2E UI + visual regression + integration (final gate). Per §TESTING VENUES.

## 7. Resolved questions — Rick's rulings (2026-07-01, María-facilitated walkthrough)

1. **Horizontal layout semantics (Lane 0b) → RULED: match legacy exactly; legacy has TWO modes.** (a) **Centered/standardized mode** — the toolbar is a vertical strip of icons. (b) **Horizontal mode** — the center content shifts to the **right**, and all **abstracts + action-required widgets** are displayed. Build to replicate both modes faithfully; the ▭/⊞ grid toggle is in scope only if legacy has it working. *(This ruling supplies the pre-build legacy confirmation the draft had deferred to the drive-by — see Lane 0b ACs.)*
2. **Reskin carve-outs → RULED: full revert to legacy light, NO exceptions** (Rick: "I actually liked the legacy light look"). Every modern element reverts; zero standing oracle carve-outs.
3. **Jobs default-visibility → RULED: hidden by default** (legacy parity); still fully built per D1 — apply the Lane-0c `hidden` on `#jobs-pane`.
4. **Prove-gate → RULED: geometry proof mandatory + row-style/computed-style fidelity on the 6 accordions; page-chrome oracle a non-blocking fast-follow.** Computed-style fidelity is what verifies the Q2 full-revert actually landed.
   > ⚠️ **TIER-LABEL FACTUAL FIX (F-Sam-D1, 2026-07-01 — harness-grounded, manager-ruled factual correction; Q4 SUBSTANCE UNCHANGED).** Rick's ruling as originally transcribed said "Tier-2 (geometry) mandatory + Tier-3 (row-style fidelity)… Tier-3 verifies the Q2 revert" — the tier↔concern labels were INVERTED vs the harness. Ground truth (`src/tests/parity_oracle/test_tier2_tier3.py:1-3/128/179`): **Tier-2 = computed-style isomorphism (the "core proof" — this is the skin/color/row-style verdict that verifies the Q2 full-revert); Tier-3 = absolute geometry ±1px (`GEOM_TOL_PX=1.0`, the mandatory frame proof).** The ruling's SUBSTANCE is untouched — BOTH proofs are mandatory on the 6 accordions; only the tier NUMBERS attached to each concern are corrected to match the harness. So: Tier-3 (geometry) mandatory frame + Tier-2 (computed-style) skin-revert verdict.

**Sanity-check (María, 2026-07-01):** plan is sound + cascade-ready — D1–D3 ratified, file:line-anchored, honestly scoped (prove-only Fleet/Task matches verified reality), sequencing sound (0a/0c reshape the oracle frame → land first). The one flag (Q1's legacy-behavior confirmation deferred to post-build) is now **closed** by Rick's two-mode description above. Minor: re-confirm the acceptance/drive-by venue given 2026-07-01 server work (pgvector migration; `:7999` briefly down, recovered).

## 8. Sequencing

```
Lane 0a (header chrome) ─┐
Lane 0c (ordering)      ─┼─► Lane 1 (finish) ─► Lane 2 (skin revert) ─► Lane 3 (prove) ─► drive-by acceptance
Lane 0b (layout toggle) ─┘
```
Rationale: 0a/0c reshape the frame the oracle measures, so they land first; skin revert (2) after functional completion (1) to avoid re-styling churn; prove (3) last; user drive-by is the final human gate.

## 9. Coverage & venue mandates (non-negotiable)
- 100% lines/branches/functions on all touched code; `# pragma: no cover` / `c8 ignore` only for genuinely-unreachable defensive branches with same-line reason.
- No :8000-bucket suite run against :7999; submit only via `POST /api/test-suite/submit` (self-authorized on verified-idle server).

---

**Next**: resolve §7, run `/plan-review`, then spin the build lanes.
