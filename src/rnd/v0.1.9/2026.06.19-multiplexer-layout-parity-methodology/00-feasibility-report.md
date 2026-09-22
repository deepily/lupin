# 00 — Feasibility Report: Can the Multiplexer Reproduce the Notifications Layout?

**Date:** 2026-06-19 · **Branch:** `wip-v0.1.9-2026.06.19-bug-fixing`
**Question owner:** Rick · **Deliverable 1 of 3** (feeds [`01-layout-parity-methodology.md`](01-layout-parity-methodology.md) → [`02-bridging-work-plan.md`](02-bridging-work-plan.md))

> **The brief, restated:** "Using the exact same field names and the exact same classes
> using the exact same source CSS should produce the same layout. I'm just not certain that
> this is possible because the two layouts and naming approaches may have diverged to the
> point where they are not reconcilable." — This document answers *is it possible*, with
> evidence. The *how* is Doc 01; the *work* is Doc 02.

---

## 1. Executive verdict

**Yes — and it is provable without your eyes — once "layout parity" is split into two claims that
have very different answers:**

| Claim | Verdict | Why |
|---|---|---|
| **Style parity** on the surfaces both clients *already render* (page-frame, sender cards, date accordions, messages, action-required widgets) | **Achievable now, provably, largely already done** | The component CSS was ported faithfully; the residual divergences are **finite and enumerated** (Section 4). None are irreconcilable. |
| **Structure parity** of the *whole page* (every element the legacy page shows) | **Not a CSS problem — a function of functional-gap closure** | The multiplexer is missing whole elements/panes (Reading Pane, CC-session strip, card-chrome buttons). Those are absent *DOM*, so no stylesheet can conjure them. Closing them is the [06-10 gap-bridge](../../v0.1.8/2026.06.10-notifications-ui-multiplexer-gap-bridge/README.md) scope. |

So the anxiety in the brief ("diverged beyond reconciliation") dissolves under decomposition:
the **styling** of shared surfaces is reconcilable today; the **completeness** of the page is a
delivery schedule, not a reconciliation question. **Nothing is irreconcilable.** The hard part
was never the CSS — it is finishing the multiplexer's missing functionality, and the layout
follows for free once the DOM exists, *provided* we stop the CSS from being a divergent copy
(Doc 01, Pillar 1).

**Confidence: HIGH** for the style-parity claim (evidence below is class-by-class and
file:line-grounded). **MEDIUM** for the end-to-end "100%" claim, gated entirely on the one real
engineering risk — harnessing the 915 KB legacy monolith to render a fixed fixture on demand
(Section 6).

---

## 2. Why the hypothesis is sound *in principle* (the theorem)

Browser layout is a deterministic pure function:

```
rendered_layout = f( DOM_tree, stylesheet_set, viewport, fonts )
```

Hold all four inputs identical and the output is **bit-identical by construction** — this is not a
hope, it is how the CSSOM cascade is specified. So the brief's hypothesis is not merely plausible;
it is a **theorem**. The entire feasibility question therefore reduces to a single, *tractable*
sub-question:

> **Can we make the four inputs identical — or identical on the subset that matters — and then
> machine-verify that we did?**

That reframing is the whole game. We do not need to "get the look right by iterating." We need to
make the premises true and **prove** they are true. That proof is the automated oracle in Doc 01,
and it is exactly what removes your eyes from the loop.

---

## 3. Why the premises are currently FALSE in practice

The theorem's premises do not hold today. Each is fixable; each is a line item in Doc 02.

### Premise A — "the exact same source CSS" → **FALSE (this is the root cause)**

`/app/notifications` loads the monolith `notifications.css?v=20260530c` (6009 lines).
`/app/multiplexer` loads `multiplexer/notifications-list.css` — a **604-line slice** that was
hand-extracted from the monolith ([notifications-list.css:1-18](../../../lupin_app/static/css/multiplexer/notifications-list.css) documents the extraction). **Two copies of "the same" rules guarantee drift**, and drift has already happened:

- The 06-17 audit caught `.date-accordion-messages` losing its `border-top`/`background`, and
  `.sender-card` losing its double box-shadow — pure copy-drift.
- The slice even **invented new structure the monolith never had**:
  `#sender-cards-container { display:flex; flex-direction:column; gap:8px }`
  ([notifications-list.css:35-40](../../../lupin_app/static/css/multiplexer/notifications-list.css)),
  whereas legacy spaces cards via `.collapsible-section { margin-bottom:30px }`
  ([notifications.css:117-120](../../../lupin_app/static/css/notifications.css)). Same intent,
  different mechanism → divergent inter-card spacing.

This is the single most important finding: **as long as the multiplexer styles itself from a
*copy*, parity is a moving target you can only chase by eye.** Doc 01 Pillar 1 kills the copy.

### Premise B — "the exact same classes" → **MOSTLY TRUE, with deliberate exceptions**

The port was disciplined: `.sender-card`, `.sender-card-header`, `.sender-card-dates`,
`.sender-active-indicator`, `.date-accordion`, `.date-accordion-header`, `.date-text`,
`.date-count`, `.date-toggle`, `.date-accordion-messages`, `.sender-message`, `.message-time`,
`.message-text`, `.expired-badge`, `.abstract-indicator`, `.progress-group-*` are **verbatim**
(enforced by ratification "Q-C: legacy class names verbatim"). But three *intentional* renames /
mechanism-swaps break the "same classes" premise — see the taxonomy in Section 4.

### Premise C — "the exact same field names" → **PARTIALLY, and it mostly doesn't matter for layout**

The data models genuinely diverged: legacy parses a `senderId` string into a project name; the
multiplexer consumes a typed `SenderRecord` with `display_name`, `unread_count`, `last_active_ts`,
`voice_persona` ([senderCard.ts:44-66](../../../lupin_app/static/js/multiplexer/render/templates/senderCard.ts)).
Legacy reads `notification.timestamp`; the multiplexer reads `notification.ts`.

**But field names drive *content*, and content only perturbs *layout* through string length and
element presence.** A controlled test fixture (Doc 01) holds the rendered strings identical across
both clients, which neutralizes Premise C for the purposes of the layout oracle. Field-name
unification remains desirable for *maintainability* (and for functional parity), but it is **not a
prerequisite** for proving layout parity. This is a useful refinement of your hypothesis: it is
"same classes + same source CSS + same *rendered content*" that yields the same layout — and the
fixture supplies the last term.

---

## 4. The divergence taxonomy — the heart of the answer

Every catalogued difference between the two clients falls into exactly one of four buckets. **This
taxonomy is the feasibility answer**, because it sorts "scary divergence" into "free," "small
fix," "scheduled work," and "irrelevant."

### Category 1 — Additive, layout-neutral → **KEEP, zero action**

Extra attributes the multiplexer adds for its keyed-merge re-render engine. No shared-CSS selector
depends on their *absence*, so they cannot perturb layout.

| Item | Where | Verdict |
|---|---|---|
| `data-id-hash` on cards/accordions/messages | [senderCard.ts:51](../../../lupin_app/static/js/multiplexer/render/templates/senderCard.ts), [dateAccordion.ts:44](../../../lupin_app/static/js/multiplexer/render/templates/dateAccordion.ts), [notificationItem.ts:60](../../../lupin_app/static/js/multiplexer/render/templates/notificationItem.ts) | Harmless — keyed-merge identity |
| `data-date-key`, `data-progress-group` | dateAccordion.ts:45, notificationItem.ts:62 | Harmless |

### Category 2 — Substitutive, breaks **style parity** → **MUST reconcile (small, enumerated, the actual CSS work)**

A class/tag/mechanism the multiplexer renders *differently*, so identical CSS produces a different
box. These are the whole of the genuine layout-reconciliation task — and there are only four.

| # | Divergence | Legacy | Multiplexer | Reconciliation |
|---|---|---|---|---|
| C2-a | **Persona badge** | `<span class="persona-badge">` + inline `style` | `<button class="sender-persona-badge">` + `popovertarget` ([senderCard.ts:87-89](../../../lupin_app/static/js/multiplexer/render/templates/senderCard.ts)) | Button carries UA styles (border, font) a span does not. Either re-add legacy class as alias, or generalize the shared rule to cover both selectors + reset the button. *Intentional* (no-globals/popover); keep the button, fix the CSS. |
| C2-b | **Accordion collapse** | `.collapsed` class on `.date-accordion-messages` | `[data-collapsed]` attr on `.date-accordion` ([dateAccordion.ts:46](../../../lupin_app/static/js/multiplexer/render/templates/dateAccordion.ts)) | Shared rule must fire for **both** selectors, or the two converge on one mechanism. One-line CSS union. |
| C2-c | **Inter-card spacing** | `.collapsible-section { margin-bottom:30px }` | `#sender-cards-container { gap:8px }` | Different spacing model + value. Pick one; encode in the shared sheet. |
| C2-d | **Message direction** | `.incoming` **and** `.outgoing` off `isResponse` — **confirmed live, not dead code**: on cold load every responded notification renders outgoing ([notifications.js:15014](../../../lupin_app/static/js/notifications.js)) and is **split into two bubbles** — incoming prompt + a synthetic `{id}-response` outgoing reply ([:14317-14330](../../../lupin_app/static/js/notifications.js)); plus the `→` time marker ([:14125](../../../lupin_app/static/js/notifications.js)) | **always `.incoming`** — Notification model has no direction field ([notificationItem.ts:59](../../../lupin_app/static/js/multiplexer/render/templates/notificationItem.ts)) | **D3 RESOLVED → `.outgoing` is a DAY-ONE capability — supported from the start, NOT deferred, NOT exempt** (Rick, 2026-06-20). Work: `notificationItem.ts` gains a **direction** param (drop the hardcoded `.incoming`); the store/adapter **splits a responded notification into incoming-prompt + outgoing-response**, mirroring legacy `:14317-14330`. **Load-time outgoing** (responded items echo their answer on page load) consumes the server's existing `response_value` — **F5-independent**, lands in the core slice. **Live outgoing** (real-time echo of user-sent/dictated replies) **pulls the send-path (F5) forward into scope** rather than deferring outgoing. The `.outgoing` CSS is already ported, so it lights up immediately; the canonical fixture carries a responded pair so the oracle verifies outgoing styling from day one. |

> Note: two divergences the 06-17 audit flagged are **already fixed** in current source —
> `--persona-color-rgb` is now set ([senderCard.ts:62-65](../../../lupin_app/static/js/multiplexer/render/templates/senderCard.ts))
> and `.incoming` is now applied ([notificationItem.ts:59](../../../lupin_app/static/js/multiplexer/render/templates/notificationItem.ts)).
> The page-frame trio (`.container`/`body`/`h1`) is also restored via
> [page-frame.css](../../../lupin_app/static/css/multiplexer/page-frame.css). So C2 is the *residual*
> set after the audit's Phase A/B landed.

### Category 3 — Missing elements, breaks **structure parity** → **= functional gaps (Doc 02 / 06-10 gap-bridge)**

Whole DOM the multiplexer never emits. No stylesheet can style absent nodes. These are *also* the
functional-parity gaps — which is why **layout parity and functional parity are the same project**,
not two.

| Missing surface | Legacy source | Tracked as |
|---|---|---|
| `.sender-project-name`, `.sender-session-id/-copy/-name`, `.sender-status`, `.sender-delete-btn`, `.sender-toggle` | notifications.js sender-card header | Layer B (card chrome) |
| `.date-delete-btn` | notifications.js accordion header | Layer B |
| `.notification-corner-pause-btn` / `-stop-btn` | notifications.js message | Phase-6 interactive (deferred in extract, see [notifications-list.css:12-13](../../../lupin_app/static/css/multiplexer/notifications-list.css)) |
| Reading Pane, CC-session strip, Commons activity, Fleet-Status, prediction vote, missed badge | F1–F12 | [01-gap-analysis](../../v0.1.8/2026.06.10-notifications-ui-multiplexer-gap-bridge/01-gap-analysis.md) |

### Category 4 — Data/content divergence → **IRRELEVANT to the layout oracle (neutralized by fixture)**

`parsed.project` vs `display_name`; `timestamp` vs `ts`; abstract `encodeURIComponent` vs plain.
These change *what text appears*, not *how the box lays out*, and the shared test fixture pins the
rendered strings so they cannot leak into a layout diff. In scope for *functional* parity; out of
scope for *layout* parity.

---

## 5. The decomposition that makes "100%" tractable

```
Layout parity (whole page)
├── Style parity   ── shared surfaces render pixel-identical given identical content
│      ├── Premise A: single-source CSS        (Doc 01 Pillar 1 — kills the copy)
│      └── Category 2: reconcile 4 substitutions (small, enumerated)
│      └── PROVABLE TODAY, mostly already true
│
└── Structure parity ── every legacy element is present to be styled
       └── Category 3: close functional gaps    (Doc 02 / 06-10 gap-bridge)
       └── A SCHEDULE, not a reconciliation problem
```

The oracle (Doc 01) **measures both axes continuously**: style parity as computed-style equality on
shared nodes, structure parity as "every contract node present." As functional gaps close, the
structure-parity score climbs monotonically toward 100% — and the *per-node failure list is exactly
the remaining work*. Even a *failing* oracle is a precise, actionable artifact, never a vague "looks
off."

---

## 6. The one genuine risk (and why it is bounded)

**Harnessing the legacy client as a render oracle.** The multiplexer is built for testing — it has
`window.__multiplexerTestHook` for deterministic fixture injection (used across the existing
`test_multiplexer_*_visual.py` suite). The **915 KB `notifications.js` monolith is WebSocket-driven
and exposes no equivalent clean render entry point.** To compare both clients on the *same* fixture
we must either (a) drive legacy through its real ingestion path (inject WS frames), or (b) **capture
a one-time "golden" DOM + computed-style snapshot from legacy and freeze it as a tracked artifact**,
then test the multiplexer against the golden.

Doc 01 recommends **(b) golden-capture** as the backbone (fast, deterministic, no live legacy
process), with an occasional **live dual-render recalibration** to refresh the golden. This bounds
the risk: we harness legacy *once per golden refresh*, not every test run.

Secondary, smaller: the visual-baseline dir `io/test-suite/visual-baselines` is **gitignored** —
so the structural/computed-style goldens (small JSON, ideal for git) need a **tracked** home, not
that directory. Trivial, but must be deliberate.

---

## 7. Bottom line for the decision-maker

- **Is identical layout possible?** **Yes.** The premises are false today only because the
  multiplexer styles from a *copy* (Premise A) and made *four* deliberate substitutions (Category
  2). Both are fixable; neither is irreconcilable.
- **Is "100% identical whole page" possible now?** Not until the **functional gaps** (Category 3 /
  F1–F12 / Layer B) close — but that is the *already-scoped* parity work, and the layout comes
  **for free** with the DOM once Premise A is fixed.
- **Can it be verified without your eyes?** **Yes** — that is the entire point of Doc 01's oracle,
  which proves the theorem of Section 2 by measuring the CSSOM directly.
- **Recommended next move:** ratify the methodology in Doc 01 (single-source CSS + the oracle) and
  the sequencing in Doc 02. The CSS-reconciliation slice is small and could land in one session; the
  oracle is the durable investment that makes "done" mean *measured*, not *eyeballed*.
