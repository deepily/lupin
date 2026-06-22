# Multiplexer ↔ Notifications: Layout-Parity Methodology & Feasibility (2026-06-19)

**Engagement:** Rick-directed — bring the new **multiplexer** client into ~100% functional + layout
sync with the legacy **`notifications.js`** client, via a *defensible, non-ad-hoc* methodology that
(a) uses the **raw notifications CSS** rather than a re-extracted copy, and (b) **tests the layout
without Rick's eyes**. This is as much a **feasibility report** ("is identical layout even
possible, given how far the two have diverged?") as a plan.

## The one-sentence answer

**Identical layout is possible and provable** — the brief's hypothesis ("same field names + same
classes + same source CSS → same layout") is a *theorem* (layout is a deterministic function of
DOM + CSS + viewport); it is only *false today* because the multiplexer styles from a **604-line
copy** of the 6009-line monolith (drift) and made **four** deliberate class/mechanism substitutions
— both fixable, neither irreconcilable.

## Documents

| # | Doc | What it answers |
|---|---|---|
| 00 | [Feasibility report](00-feasibility-report.md) | *Is it possible?* The theorem, why the premises are currently false, the **4-category divergence taxonomy**, the **style-parity vs structure-parity** decomposition, and the one real risk (harnessing the legacy monolith). **Verdict: yes, conditionally + provably.** |
| 01 | [Layout-parity methodology](01-layout-parity-methodology.md) | *The defensible process.* **Pillar 1 — Single-Source CSS** (delete the copy; one shared sheet, two `<link>`s; the Layout Contract). **Pillar 2 — the Layout-Parity Oracle** (Tiers 0–4: CSS-hash → DOM-contract → computed-style → geometry → pixel-backstop), the dual-shaped fixture, golden-capture. |
| 02 | [Bridging work plan](02-bridging-work-plan.md) | *The route to ~100%.* Builds on (does not duplicate) the 06-10 gap-bridge. Workstreams WS1–WS4, gates G0–G6, sequencing, venue routing, and **6 decisions for ratification**. |

## TL;DR

- **Layout parity decomposes into two very different claims.** *Style parity* on the surfaces both
  clients already render (page-frame, sender cards, accordions, messages, action-required) is
  **achievable now, provably, and largely already landed** (the 06-17 audit's page-frame/`--persona-color-rgb`/`.incoming`
  fixes are in current source). *Structure parity* of the whole page is **not a CSS problem** — it is
  a function of closing the multiplexer's missing functionality (the 06-10 F1–F12 / Layer-B gaps).
  **Nothing is irreconcilable; the hard part is finishing features, and the layout follows for free.**
- **Root cause of the "looks different" drift:** the multiplexer styles from
  `multiplexer/notifications-list.css` — a hand-extracted **604-line slice** of `notifications.css`
  (6009 lines). Two copies guarantee drift, and it has already drifted (and even *invented* new
  container structure). **Pillar 1 deletes the copy.**
- **Removing your eyes is the design center, not an add-on.** The oracle proves parity by reading the
  **CSSOM directly** (`getComputedStyle` / `getBoundingClientRect`) on a fixed fixture and asserting
  equality node-by-node. A failure is a surgical `node + property + legacy-value + mux-value` line —
  the bug report *and* the to-do list, no screenshot judgement required. The existing pixel
  `assert_snapshot()` harness is kept as a **backstop**, demoted from "the definition of done."
- **The four residual style divergences (Category 2)** are small and enumerated: persona badge
  (`<button>` vs `<span>`), collapse mechanism (`[data-collapsed]` vs `.collapsed`), inter-card
  spacing (`gap` vs `margin`), and message direction (always-`.incoming`). Three are one-line CSS
  unions; the fourth is **settled (D3): `.outgoing` is supported day-one** — legacy renders outgoing
  bubbles on cold load (splits a responded notification into prompt + reply), so the multiplexer does
  the same from the start: a renderer/model responded-split plus pulling the F5 user-send path
  forward. **Not deferred, not exempt.**
- **Near-term milestone:** G0–G3 (single-source CSS + reconcile C2 + stand up the oracle). C2-a/b/c
  are a focused CSS session (most already done); **C2-d — day-one `.outgoing` (D3) — adds a
  renderer/model responded-split and pulls the F5 user-send forward**, so budget beyond pure CSS.
  The long pole — G4 structure parity — is the already-scoped 06-10 work, now **oracle-gated**.

## Decisions awaiting ratification (full table in Doc 02)

D1 CSS strategy (**rec: shared extracted sheet**) · D2 spacing model (**rec: legacy margin**) ·
D3 message direction (**RESOLVED: `.outgoing` supported day-one** — renderer/model split + pulls F5 forward; not deferred) · D4 oracle authority (**rec:
computed-style gates, pixel advisory**) · D5 golden artifact home (**rec:
`src/tests/e2e_ui/fixtures/golden/`, git-tracked**) · D6 v0.1.9 scope (**rec: land G0–G3 + oracle
now; hand G4 to the 06-10 lane**).

## Sources

Current source read directly (`render/templates/{senderCard,notificationItem,dateAccordion}.ts`,
`css/multiplexer/{page-frame,notifications-list}.css`, `css/notifications.css`,
`html/{multiplexer,notifications}.html`, `routers/pages.py`); prior R&D
[`2026.06.10-notifications-ui-multiplexer-gap-bridge/`](../../v0.1.8/2026.06.10-notifications-ui-multiplexer-gap-bridge/README.md)
(functional gap F1–F12 + Layer B) and
[`2026.06.17-multiplexer-css-parity-audit.md`](../../v0.1.8/2026.06.17-multiplexer-css-parity-audit.md)
(page-frame root cause); test infra (`e2e_ui/conftest.py`, `pytest.ini`,
`test_multiplexer_*_visual.py`, `build-multiplexer.sh`).
