# 01 — Layout-Parity Methodology: Single-Source CSS + an Automated Oracle

**Date:** 2026-06-19 · **Deliverable 2 of 3** (reads from [`00-feasibility-report.md`](00-feasibility-report.md); feeds [`02-bridging-work-plan.md`](02-bridging-work-plan.md))

This is the *defensible, non-ad-hoc process* the brief asked for. It has exactly two pillars, which
map one-to-one onto the brief's two requirements:

> 1. "a process that … utilizes the raw CSS utilized by the notifications client" → **Pillar 1: Single-Source CSS**
> 2. "a way for testing the layout that does not require my personal eyes" → **Pillar 2: The Layout-Parity Oracle**

The pillars are complementary, not alternatives. Pillar 1 makes the layout *correct by
construction*; Pillar 2 *proves* it stayed correct. Together they convert "make it look the same"
from a craft into a **measured invariant**.

---

## Pillar 1 — Single-Source CSS (use the raw CSS, delete the copy)

### The principle

> **Layout parity that depends on two humans keeping two stylesheets in sync is not parity — it is a
> truce that drift will break.** The only durable guarantee is that the bytes that style a sender
> card on `/app/notifications` are the *same bytes* that style it on `/app/multiplexer`.

Doc 00 §3 established the root cause: the multiplexer styles itself from `notifications-list.css`, a
604-line hand-extract of the 6009-line monolith. Pillar 1 eliminates the extract.

### Three candidate strategies (with the recommendation)

| Strategy | Mechanism | Drift risk | Collision risk | Verdict |
|---|---|---|---|---|
| **S1 — Direct-link the monolith** | `multiplexer.html` `<link>`s the full `notifications.css` | **Zero** (literally the same file) | **HIGH** — duplicate global resets, dead `.sender-card[data-pinned-conv-mode]` cascades, `.action-required-*` defined twice, specificity fights with `reading-pane.css` | **Reject.** The monolith carries 5000+ lines of page-specific + retired rules that collide with the multiplexer's own sheets. |
| **S2 — Shared extracted sheet** | Factor the *contract* rules (page-frame + cards + accordions + messages + action-required) out of the monolith into `css/shared/notifications-surface.css`; **both** pages link it; neither page keeps a private copy | **Zero** (one file, two `<link>`s) | **LOW** — the shared sheet contains only the agreed contract surfaces; page-specific chrome stays in each page's own sheet | **RECOMMEND.** Single source of truth, no dead cascades, reviewable. |
| **S3 — Generated projection** | A build step slices documented line-ranges of the monolith into the extract; CI asserts the slice is byte-identical to the source ranges | Low (caught by CI) | Low | **Fallback.** Works, but line-range slicing is brittle under edits; only choose if S2's extraction is judged too invasive. |

**Recommended: S2.** Create `css/shared/notifications-surface.css` as the *single* home for the
contract rules. `notifications.html` drops those rules from its monolith (or links the shared sheet
ahead of the monolith and lets the monolith shrink over time); `multiplexer.html` replaces
`notifications-list.css` + `page-frame.css` with the shared sheet. From that point, **a change to a
sender-card rule is physically impossible to apply to one client and not the other** — parity is an
invariant of the file system, not of anyone's diligence.

> The multiplexer **keeps its own** `reading-pane.css`, `session-strip.css`, `jobs-pane.css`, etc.
> for surfaces that are multiplexer-specific or where divergence is *intended*. Pillar 1 unifies
> only the **contract surfaces** — the ones that must look identical.

### The Layout Contract (the invariant the shared CSS depends on)

A stylesheet is only deterministic against a DOM it can select. So Pillar 1 ships with a written
**Layout Contract**: the minimal set of `(tag, class, selector-driving-attribute)` tuples that
`notifications-surface.css` relies on. Example rows:

```
sender card        : div.sender-card[ data-* additive-ok ]
  header           : div.sender-card-header
  persona badge    : <button.sender-persona-badge> ∪ <span.persona-badge>   (C2-a union)
  …
date accordion     : div.date-accordion   ; collapsed ⇔ .date-accordion-messages.collapsed
                                              ∪ [data-collapsed="true"] .date-accordion-messages   (C2-b union)
message            : div.sender-message.incoming | .outgoing
```

The contract is the *referee* for Doc 00's Category-2 reconciliations: each C2 row resolves either
by changing the renderer to satisfy the contract, or by widening the contract (and the shared CSS)
to admit both forms via a selector union. **The contract — not a screenshot — is the definition of
"the same."** It lives next to the shared sheet and is asserted by Tier 1 of the oracle.

---

## Pillar 2 — The Layout-Parity Oracle (no human eyes)

A four-tier ladder, cheap-and-static at the bottom, precise-and-browser-based in the middle, with
the existing pixel test demoted to a backstop. **Tiers 0–3 are deterministic and *explanatory* —
when they fail they name the node and the property, so no one has to look at anything.**

```
Tier 0  CSS Source Identity      static  — both pages reference the same shared-CSS hash
Tier 1  DOM Contract Conformance  browser — each renderer emits the contract skeleton
Tier 2  Computed-Style Isomorphism browser — corresponding nodes have equal CSSOM   ◄ the core proof
Tier 3  Geometry Isomorphism      browser — corresponding nodes have equal box geometry
Tier 4  Pixel Screenshot Diff     browser — existing assert_snapshot(), as a backstop only
```

### Tier 0 — CSS Source Identity (static, milliseconds, :7999/unit)

Assert that `notifications.html` and `multiplexer.html` both `<link>` the *same*
`notifications-surface.css` (compare the resolved href / content hash). This is Pillar 1, mechanized:
if it passes, the two clients are *styling from the same bytes*, and copy-drift is impossible. A
pure-Python test — no browser. **This single check is what makes the brief's hypothesis true; the
remaining tiers verify the DOM half.**

### Tier 1 — DOM Contract Conformance (browser, per-renderer)

Feed each renderer the **same canonical fixture** (below). Render into headless Chromium. Walk the
produced subtree and extract a normalized **layout skeleton**: for every element, its
`(tagName, sorted class-list ∩ contract-classes, contract-driving data-attrs)`. Assert the skeleton
**conforms to the Layout Contract**.

- Run it against the **multiplexer** → catches "forgot `.incoming`", "renamed a contract class",
  "dropped `.date-accordion-messages`".
- Run it against **legacy** → proves the contract is *faithful* to legacy (the contract is not
  fiction).

Tier 1 compares each client to the *contract*, independently — so it localizes a regression to one
client without the noise of a direct cross-diff. Precedent exists: the suite already reads class
lists and attributes via `get_attribute("class")` / `evaluate_all(...)`
(`test_cj_flow_pause_schedule.py`, `test_commons_activity_toggle.py`,
`test_multiplexer_phase6c_smoke.py`).

### Tier 2 — Computed-Style Isomorphism (browser, cross-renderer) — **the core proof**

The theorem of Doc 00 §2 made operational. The contract guarantees both skeletons are
*alignable*; walk the legacy and multiplexer subtrees **in lockstep** and, for each corresponding
node pair, read `getComputedStyle` for the **layout-relevant property set** and assert equality:

```
display, position, top/right/bottom/left, float, clear,
box-sizing, width, height, min/max-*,
margin-*, border-*-width, border-*-style, padding-*,
flex-*, grid-*, gap, align-*, justify-*, order,
font-family, font-size, font-weight, line-height, letter-spacing, white-space,
color, background-color, background-image, box-shadow, border-radius, opacity, transform
```

(Deliberately **excludes** text content, timestamps, and animation mid-states — Category-4 noise.)

When this passes for the contract subtree, **layout parity is demonstrated** — not estimated,
*demonstrated*, because computed style *is* the input to layout and we have shown it equal. When it
fails, the diff is surgical:

```
DIVERGENCE  .date-accordion-messages  [sender#3 › date#1]
  background-color : legacy rgb(250,250,250)  ·  mux rgba(0,0,0,0)
  border-top-width : legacy 1px              ·  mux 0px
```

That line *is* the bug report. No screenshot, no opinion, no eyes. Precedent:
`test_multiplexer_phase6a_smoke.py:328-349` already reads `getComputedStyle(document.body)` for
color/background/font/margin/padding; `test_multiplexer_layout_mode_toolbar_centering.py:45-49`
already reads CSS custom properties via `page.evaluate`. Tier 2 generalizes that to a tree walk.

### Tier 3 — Geometry Isomorphism (browser, cross-renderer)

For the same node pairs, read `getBoundingClientRect` and assert the **relative geometry** matches
within a tight tolerance (≈ ±1px): same size, same offset relative to the `.container` origin.
Catches layout errors that are *emergent* (a sibling's width pushing a node) rather than
property-local, which Tier 2 can miss. Precedent:
`test_multiplexer_layout_mode_toolbar_centering.py:89-98` already asserts `getBoundingClientRect`
geometry.

### Tier 4 — Pixel Screenshot Diff (backstop, not the gate)

The **existing** `assert_snapshot()` harness (`pytest-playwright-visual-snapshot==0.5.1`, threshold
`0.1`, deterministic font flags already wired in `e2e_ui/conftest.py:35-67`). Demoted from "the
test" to "a backstop": it is the least precise (says *different*, not *why*) and most flaky (AA,
fonts), but it cheaply catches whole-page emergent issues Tiers 1–3 don't model (z-index stacking,
overflow clipping, paint). Keep it; stop *relying* on it as the parity definition.

---

## The shared fixture (what "same input" means concretely)

Both clients must render the **same logical content** so any layout delta is attributable to
CSS/DOM, never data (Doc 00 §3, Premise C). Because the data models differ, the fixture is a single
**canonical scenario** expressed through a thin **dual adapter**:

```
fixtures/notifications-parity-scenario.json      ← ONE canonical scenario (senders, dates, messages,
                                                     personas, action-required items) — the source of truth
   ├── adapter → legacy wire frames   (timestamp, parsed senderId, …)
   └── adapter → multiplexer store shape (ts, SenderRecord, voice_persona, …)
```

The adapter's field-mapping (`timestamp↔ts`, `parsed.project↔display_name`, …) is **written down**
and becomes part of the parity spec — which doubles as the to-do list for eventual field-name
unification. The scenario is frozen and versioned (it must be *stable* for goldens to mean
anything). Deterministic timestamps, exactly as the existing visual fixtures already do
(`_INJECT_..._JS` with pinned times in `test_multiplexer_phase6b_visual.py`).

## Golden-capture vs live dual-render (the legacy-harness decision)

Per Doc 00 §6, the legacy monolith has no clean render hook. So:

- **Backbone = golden-capture.** Drive legacy *once* with the canonical fixture (via its real WS
  ingestion path in a one-off capture script), serialize its contract subtree's **skeleton +
  computed-style map + geometry map** to a **tracked** JSON artifact
  (`fixtures/golden/notifications-legacy.golden.json`). Day-to-day, Tiers 1–3 run the **multiplexer
  vs the golden** — fast, deterministic, no live legacy process.
- **Recalibration = live dual-render.** On a cadence (or when legacy CSS changes), re-run the
  capture to refresh the golden, and once in a while run *both* clients live in lockstep to confirm
  the golden hasn't gone stale. This is the only time we pay the legacy-harness cost.

> **Tracked-artifact note:** goldens are small JSON and must live in a **git-tracked** path (e.g.
> `src/tests/e2e_ui/fixtures/golden/`), **not** `io/test-suite/visual-baselines` which is gitignored
> (Doc 00 §6). Pixel baselines (Tier 4) stay where they are.

## Component-isolation vs full-page scope

Two render scopes, because confounding context (inherited props, parent flex) can make whole-page
computed-style comparison noisy:

1. **Component-isolation harness** — a tiny static page that mounts *one* contract component (a
   single `.sender-card`, etc.) inside the standard `.container` at a fixed viewport, for **both**
   clients. This is where Tiers 2–3 run cleanest: apples-to-apples, no sibling interference. The
   multiplexer's templates are already pure functions returning `HTMLElement`
   (`renderSenderCard(...)`), so isolating one is cheap; the legacy side uses the golden.
2. **Full-page** — the real `/app/notifications?classic=1` vs `/app/multiplexer`, where Tier 4
   (pixel) and a coarse Tier 1 (contract presence) run, catching integration-level issues.

---

## Where it plugs into the existing harness

| Need | Existing asset | Source |
|---|---|---|
| Browser driver + auth + hydration wait | Playwright-Python, `logged_in_page` fixture, `wait_for_function(window.__multiplexerTestHook…)` | `e2e_ui/conftest.py`, `test_multiplexer_phase6b_visual.py` |
| Deterministic rendering | Chromium font/color flags | `e2e_ui/conftest.py:35-67` |
| Fixture injection (mux) | `page.evaluate(_INJECT_..._JS)` + test hook | `test_multiplexer_phase6b_visual.py` |
| Load both clients | `/app/notifications?classic=1` · `/app/multiplexer` | `pages.py` (flag `legacy notifications redirect enabled` + `?classic=1` escape hatch) |
| Pixel backstop | `assert_snapshot()` | `pytest.ini:39-41` |
| Computed-style / geometry reads | `page.evaluate(getComputedStyle / getBoundingClientRect)` | `test_multiplexer_phase6a_smoke.py:328`, `..._toolbar_centering.py:45,89` |

**Venue:** the oracle mutates nothing and, in golden-replay mode, runs in well under 2 min →
**:7999-eligible** per CLAUDE.md §TESTING VENUES for the component-isolation tiers. The full-page
pixel sweep rides the existing **:8000 scheduled** E2E UI lane. Build dependency: `boot.ts` must be
compiled via `src/scripts/build-multiplexer.sh` (esbuild → `dist/multiplexer/boot.js`) before
browser tiers run — wire it into the harness preamble (today it is a separate manual step).

---

## What the methodology delivers

- **Correct by construction** (Pillar 1): one stylesheet, two `<link>`s — drift becomes impossible,
  not merely discouraged.
- **Proven, not eyeballed** (Pillar 2 Tiers 0–3): parity is equality of the CSSOM, measured; the
  brief's "without my personal eyes" requirement is *the design center*, not an afterthought.
- **Self-documenting failure**: every miss is a `node + property + legacy-value + mux-value` line —
  which is simultaneously the regression report *and* the remaining-work list.
- **Backstopped** (Tier 4): the cheap pixel diff still guards the emergent issues the model omits.
