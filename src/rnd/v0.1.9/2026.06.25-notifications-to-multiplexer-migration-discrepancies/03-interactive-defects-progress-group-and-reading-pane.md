# Interactive Defects + Visual-Parity Checklist (Progress-Group · Reading-Pane · AR/Playing · scaffolding polish)

**Created**: 2026-06-30 (live A/B drill-down on `:7999`, Claude session)
**Branch**: `wip-v0.1.9-2026.06.21-bug-fix-implementation`
**Status**: 🐞 **Two confirmed defects** (Bug #1, #2) + 🎨 **a 15-row visual-parity checklist** (§5) — the mux
currently reads as unstyled scaffolding; **Action-Required + Playing panels are MVP-mandatory** (Rick).
**Parent**: this migration-discrepancies holder · roadmap `../2026.06.30-mux-switchover-mvp-finish-roadmap.md`

## Purpose

Two **interactive** (not layout-order) regressions in the multiplexer, both DOM/console-confirmed against
the live `/app/multiplexer` surface with the legacy `/app/notifications?classic=1` as reference. Both are
small, localized TypeScript fixes with unambiguous root causes. This doc is the SWE-team remediation brief.

A third item — the **NAV top-bar port** — was promoted into the MVP set during the same pass; it is tracked
in the roadmap (`Phase 2.5`), not here. See §4.

## What was verified GREEN (no action needed)

The same drill-down exercised the rest of the mux chrome — all pass, recorded here so the team doesn't re-test:

- **Section-visibility toolbar** — all 6 toggles (Notifications · Jobs · Recent Activity · TTS Audio · Fleet
  Status · Task List) toggle `display` none↔block, restore cleanly, button stays re-toggleable. ✅
- **Collapse-all / Expand-all** — 41/41 cards collapse then fully restore. ✅
- **Per-card accordion** — `data-collapsed` false→true→false; height 394→**98 (header-only)**→394. The
  collapsed header stays actionable/re-expandable. ✅
- **Per-date accordion** — message list 250→0→250. ✅
- **Layout-mode ⇆ toggle** — flips `body[data-layout-mode]` horizontal↔vertical. ✅ **BUT** the horizontal
  2/3+1/3 split could not be exercised end-to-end because opening a Reading-Pane item crashes — see Bug #2.

---

## Bug #1 — Progress-group head rendered per-message (176×) instead of per-group (1×)

**Severity**: High (visual regression + DOM blow-up; the exact symptom Rick flagged).

### Symptom
Inside every CC-session history card, the "progress" accordion handle (▶ `progress-group-toggle`) **repeats
once per "Done: …" message** instead of appearing once. The intended design is **one** progress-group
accordion per card that centralizes all progress-oriented updates under a single collapsible body.

### Evidence (same session `#ef70b5f4`, mux vs legacy)

| Per sender card | Legacy (correct) | Multiplexer (broken) |
|---|---|---|
| `progress-group-entry` (container) | **1** | — |
| `progress-group-head` | **1** | **176** |
| `progress-group-toggle` (▶) | **1** | **176** |
| `progress-group-history` | **1** | **176** |
| `progress-history-entry` (the "Done: …" lines) | **358**, all inside the one history | 0 until a toggle is clicked; clicking *any one* lazily dumps the **full ~175-entry** list under *that* message |

So the mux produces 176 toggle handles that **each** expand the whole history, rather than one handle owning
one centralized history. The histories are lazily filled, so it's not 176× DOM at rest — but it is 176×
heads/toggles/corner-controls and a broken interaction model.

### Root cause
`src/lupin_app/static/js/multiplexer/render/templates/notificationItem.ts`

- **L54**: `const inProgressGrp = typeof notification.progress_group_id === "string" && notification.progress_group_id.length > 0;`
- **L85–95**: `if (inProgressGrp) { …renders .progress-group-head + .progress-group-toggle + .progress-group-history… }`

The head is gated **only** on "does this message belong to a progress group?" — which is true for **every
member** of the group. Because all ~176 "Done: …" messages share one `progress_group_id`, all 176 render a
head. There is no "am I the **head** of this group?" predicate.

### The data model already supports the fix
`render/NotificationsListRenderer.ts:689` `buildHistoryFragment()` already filters
`n.progress_group_id === progressGroupId && n.id_hash !== headIdHash` — i.e. it collects *all members minus
the head* into the single history. So one-head-many-members is already the intended shape; only the per-item
template + its caller diverge.

### Proposed fix
Render the head **once per group_id** and suppress member rows from the flat message stream:

1. Decide the head message per group (legacy = the representative/most-recent; confirm against
   `notifications.js:13788` head vs `:13800` flat, cited in the template's own comments).
2. Pass an `isGroupHead` flag into `renderNotificationItem` (or compute group-head membership in the caller
   that maps notifications → rows — `dateAccordion.ts` / `NotificationsListRenderer`).
3. Gate the head block on `inProgressGrp && isGroupHead`. For `inProgressGrp && !isGroupHead`, **do not emit
   a row** — those messages already live inside the head's lazy history.

### Verification (100% L/B/F mandate)
- Extend the progress-group fixture in the TS unit suite (`src/tests/unit/multiplexer/…`) to assert **exactly
  one** `.progress-group-head` per group across a multi-member group; assert non-head members render **zero**
  flat rows and appear only in `buildHistoryFragment`.
- `c8 --100` on the touched files; `tsc` clean; TS suite green (:7999).
- Layout-Parity Oracle (`parity_oracle.py`) re-run vs the legacy golden — head count must converge to 1.

---

## Bug #2 — Reading Pane crashes (`URIError`) on abstract-indicator click

**Severity**: High (feature non-functional; ~10% of clicks throw; **blocks horizontal-layout verification**).

### Symptom
Clicking a 📋 `abstract-indicator` is supposed to open the Reading Pane with the abstract markdown (and, in
horizontal mode, drive the 2/3+1/3 split). Instead the pane never opens and the console throws:

```
URIError: URI malformed
    at decodeURIComponent (<anonymous>)
    at ReadingPaneRendererImpl.handleDocumentClick   (ReadingPaneRenderer.ts:428)
    at HTMLDocument.onDocClick                        (ReadingPaneRenderer.ts onDocClick)
```

The renderer mounts fine (`boot_complete … readingPaneRenderer:"mounted"`); the failure is per-click.

### Root cause — encode/decode asymmetry
- **Writer** `render/templates/notificationItem.ts:196`:
  `html`<span class="abstract-indicator" data-abstract="${abstract}" …>📋</span>`` — stores the abstract
  **raw / un-encoded**.
- **Reader** `render/ReadingPaneRenderer.ts:428`:
  `const abstract = decodeURIComponent(indicator.getAttribute("data-abstract") ?? "");` — calls
  `decodeURIComponent` on that raw string.

Any abstract containing a bare `%` that is not a valid `%XX` escape throws `URIError`. These abstracts are
prose ("…100% L/B/F…", "12.4%", "50% done"), so `%` is common.

### Measured impact
**31 of 300** sampled live indicators (~10%) throw on `decodeURIComponent`. Example offending snippet:
`"…g+splainer, 100% L/B/F test st…"` (the `% ` after `100` is an invalid escape). The remaining clicks
"work" only by luck of containing no bare `%`. Failure is silent (pane just doesn't open).

### Proposed fix
Make encode/decode **symmetric**. Pick one:

- **(A, preferred)** Drop the decode: read the attribute raw in `handleDocumentClick`
  (`const abstract = indicator.getAttribute("data-abstract") ?? "";`). The value was never encoded, so no
  decode is warranted. Confirm `isAbstractShown()` / `store.open()` are fed the same raw string the second-
  click-toggle path (`ReadingPaneRenderer.ts:429–431`) compares against — keep both sides raw.
- **(B)** Or encode at write time (`encodeURIComponent(abstract)` in `notificationItem.ts:196`) and keep the
  decode. More moving parts; (A) is the smaller, safer change.

> Note the legacy notifications client stores/reads the abstract without this round-trip — (A) matches legacy.

### Verification (100% L/B/F mandate)
- Unit test: render an indicator whose `data-abstract` contains a bare `%` (e.g. `"100% done"`); dispatch a
  delegated document click; assert **no throw**, pane opens, body shows the abstract; second click toggles
  closed (`isAbstractShown` round-trip).
- `c8 --100`; `tsc` clean; TS suite green (:7999).
- After fix, **finish the horizontal-layout E2E**: horizontal mode + open abstract → `.content-shell.pane-open`
  → 2/3+1/3 split renders (the verification blocked today).

---

## §4 — NAV top-bar (cross-reference, not remediated here)
The mux has **no** top nav bar (`Lupin · Home · Notifications · Profile · email · Logout`) — DOM-confirmed
zero `<nav>` / zero logout. Promoted into the MVP set on 2026-06-30 and tracked as **Phase 2.5** in
`../2026.06.30-mux-switchover-mvp-finish-roadmap.md`. Flip-blocking once the Phase-3 redirect makes the mux
the only page. Build it from `lupin-nav.css` (already linked by `multiplexer.html`, never rendered).

## §5 — Visual-Parity Checklist (honest top-to-bottom, 2026-06-30)

> Added after Rick's correction: prior passes scored **element-presence** ("is it in the DOM?") and called
> that parity. That was wrong. Judged on **visual rendering quality** against the live legacy reference
> (`/app/notifications?classic=1`, vertical, CC-Notifications accordion open, Action-Required + Playing
> displayed-then-collapsed), the mux currently reads as **unstyled scaffolding**. This is the spot-check list
> the SWE team should drive the mux against. ✅ = visual parity · ⚠️ = present-but-degraded · ❌ = missing.

| # | Surface | Legacy (reference) | Multiplexer (actual) | Verdict |
|---|---|---|---|---|
| V1 | **Top nav bar** | dark `Lupin · Home · Notifications · Profile · email · Logout` | absent | ❌ (= NAV, Phase 2.5) |
| V2 | **Env title + clock** | `[DEVELOPMENT]: Notifications 2026-06-30 @ 16:31 EDT` | plain centered `Multiplexer`, no env, no clock | ⚠️ |
| V3 | **⚠️ Action Required panel** | bold **blue** full-width accordion + `✓ No pending actions` empty state | `height 0 / transparent / empty` when idle — invisible | ❌ MVP (AR) |
| V4 | **🔊 Playing panel** | bold **green** full-width accordion, ⏸/▶, `🔇 Nothing in the queue` | bare **gray 76px** box "— Stop Skip Queued: 0", unstyled buttons | ❌ MVP (PLY) |
| V5 | **Notifications header** | `Claude Code Notifications: 2546` + spaced `Mine` badge · styled TTS pill · `Today ▾` · red `Clear All` · ▼, right-aligned | cramped `🔔 Notifications 3662History▾Clear all` — **zero spacing**, controls jammed | ⚠️ looks broken |
| V6 | **TTS-fraction control** | styled inline pill inside the header row | orphaned standalone `TTS preview [▮——] 0%` bordered pill, mislocated | ⚠️ |
| V7 | **Broadcast card** | white rounded card; heading with ▼ **inline-right**; pills spaced | heading OK but the **▼ is orphaned on its own line** under the title | ⚠️ |
| V8 | **Recent Activity** | inline filter dropdowns, nested in broadcast card | present (toggled off by default) | ◑ |
| V9 | **Session strip** | rounded/contained; avatars carry **status sub-icons** (persona-allocation 🔉); `Focus: ON`/`Active` dark pills | full-bleed dark bar; avatars **missing the sub-icons**; pills present | ⚠️ |
| V10 | **CC-session card header** | 🐎 `LUPIN #ef70b5f4` + **topic** + **orange persona-name badge** (Mr. Radio) + green **`26 new`** pill + `(670)` + `Last: Just now` | cramped: long `claude.code@lupin.deepily.ai#ef70b5f4` **+ redundant** `#ef70b5f4`, **no topic**, **no persona-name badge**, **no `N new` pill**, just owl icon + `13` | ⚠️ cramped + redundant + missing chrome |
| V11 | **CC card body — progress group** | one ▶ accordion centralizing all progress lines | **176 repeating ▶ handles** (Bug #1) — reads as broken | ❌ (= Bug #1) |
| V12 | **Reading pane / abstract** | 📋 click opens pane | click throws `URIError` (Bug #2) | ❌ (= Bug #2) |
| V13 | **Section-toolbar** | integrated floating toolbar | floats **overlapping the top-left corner**, awkward | ⚠️ |
| V14 | **Fleet Status / Task List collapsed headers** | clean gray rounded bar: emoji · title · count · `updated HH:MM:SS` · ⟳ · ▶ | render correctly when toggled on | ✅ |
| V15 | **Overall gestalt** | contained, carded, colored, polished | bare white page, big centered title, loosely-placed controls — **scaffolding feel** | ❌ |

**MVP-mandatory adds from this pass** (Rick): **V3 Action-Required** + **V4 Playing** panels — non-negotiable
for a viable client. Tracked as **AR** + **PLY** in the roadmap MVP table. The remaining ⚠️ items (V5–V10, V13)
are the **VIS visual-quality gate**: each is "present but renders as raw scaffolding," and collectively they
are why the surface "looks like shit" (Rick's words, accurately). None is a structural gap — they are
spacing / alignment / missing-chrome / colored-panel CSS+template fixes. Recommend a dedicated B6 "visual
polish" pass driven by this table + a fresh Layout-Parity-Oracle Tier-2/3 geometry diff per row.

## Remediation order (suggested)
1. **Bug #2** (smallest; unblocks horizontal-layout verification).
2. **Bug #1** (head predicate + caller row-suppression + fixture).
3. **AR + PLY** colored panels (V3/V4) — MVP-mandatory; restore the blue Action-Required + green Playing
   accordions with empty states. Port from legacy `notifications.html:562–628` + the matching CSS.
4. **VIS visual-polish (B6)** — the V5–V10/V13 ⚠️ rows: header spacing, inline ▼, TTS-pill placement,
   session-strip status sub-icons, CC-card header chrome (topic + persona-name badge + `N new` pill).
5. **NAV** (Phase 2.5) — per the roadmap.

All on the same `wip-v0.1.9-…` bug-fix branch; rebuild the mux bundle (`src/scripts/build-multiplexer.sh`)
and re-run the Oracle + E2E UI snapshot rebaseline (:8000 scheduled). Each ⚠️/❌ row above should end green
against a fresh Tier-2/3 geometry diff vs the legacy golden.
