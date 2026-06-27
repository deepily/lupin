# CC-Session Accordion (Notifications #5) — Restore Plan (B1–B5)

**Date**: 2026-06-26
**Status**: 🟡 **DRAFT for cascaded review** — complete + self-contained; NOT yet ratified. Cascaded review is the gate before any implementation.
**Author**: this session (for Rick)
**Accordion**: Notifications / CC-sessions (`section-notifications`, mux `notifications-pane`) — **#1 priority** for the current bug-fix dev branch.
**Source audit refs**: doc `01-mux-vs-legacy-notifications-section-gap-analysis.md` (§0.2 verdict, §2 side-by-side, §4 per-message regressions, §6 buckets B1–B5, §7 evidence appendix); doc `02-reconciliation-with-in-flight-parity-work.md` (coverage map + the B1↔`4b33ceb7` conflict).
**Decision-of-record refs**: `00-index.md` §"Resolved design calls (a)/(b)/(c)" + §"B4 active-bubble TTS mechanism"; TODO Decisions Log 2026-06-26. Cross-cutting mandates: `00-plans-index.md` §"Cross-cutting mandates" (1–7) — **inherited, not restated here**.

---

## 1. Goal & parity target

Restore the CC-session section to legacy top→bottom order and per-message function so the multiplexer matches `notifications.html`'s `#section-notifications`: **Broadcast card (with Recent-Activity re-nested inside it) at the TOP → Focus bar beneath → Sessions list**, the TTS-preview slider living in the section header above the focus bar, the section-header control cluster (count · filter-badge · history-dropdown · clear-all) present, and the per-message ⏸/⏹ + proxy-ratify-link rendered on every bubble but CSS-gated to the single actively-spoken message. "Done" = the §2 Oracle tiers green against a fresh legacy golden, with the five ratified buckets B1–B5 closed and the `4b33ceb7` sibling mount restructured into the legacy nesting.

## 2. Scope

**IN** (the five ratified buckets, decisions (a)/(b)/(c) of `00-index.md`):
- **B1** — section reorder + Recent-Activity re-nest, **restructuring the `4b33ceb7` sibling mount** (decisions (a)+(b)).
- **B2** — relocate the already-built F6 TTS-preview slider into/above the focus-bar section header.
- **B3** — build the section-header controls absent in mux (count · filter-badge · history-dropdown · clear-all), confirmed-absent first.
- **B4** — per-message active-TTS-gated ⏸/⏹ + proxy-ratify-link, replicating legacy render-all + `is-playing-current` CSS gate (decision (c)).
- **B5** — CSS / Oracle Tier-2/3 pass + golden rebaseline, gated last.

**OUT** (owned elsewhere / not this plan):
- Broadcast-to-all compose port, per-CC-card collapse toggle, worker message-count-badge silencing — **already built + committed `4b33ceb7`** (doc 02 §1); we reuse, B1 only restructures the mount.
- The sender-CARD interior (header / voice-row / date-accordions / messages) — internally consistent already (doc 01 §3); F1–F12 lane-owned, largely parity-proven (doc 02 §3). Out of scope except where B4 adds the per-message corner controls.
- Action-Required funnel, TTS-Queue restore, Job-Queues mutation gaps, and the 7 absent accordions — their own plans (`02-`…`11-`).
- The mux-native ADDs (`prediction-vote` 👍/👎, `progress-group-toggle`) — keep as documented supersets; not touched here.

## 3. Source anchors

All paths relative to repo root `/Volumes/data/include/www.deepily.ai/projects/lupin`.

### Legacy (reference behavior — `notifications.html` / `notifications.js` / `notifications.css`)
| Element | Anchor |
|---|---|
| Section shell | `static/html/notifications.html:631` `#section-notifications` |
| Section-header (B3 cluster + B2 slot) | `notifications.html:632-682` — `#notifications-count` (L633), `#notifications-filter-badge` (L634), `.cc-tts-fraction-control`+`#cc-tts-fraction-slider` (L641-665), `#history-dropdown-container` (L666), `#clear-all-notifications` (L675) |
| Broadcast card (TOP) | `notifications.html:692` `#broadcast-submit-card` |
| Recent-Activity (NESTED in broadcast) | `notifications.html:740` `#commons-recent-activity-section` |
| Focus bar (beneath broadcast) | `notifications.html:810` `#cc-session-strip` |
| Sessions list (bottom) | `notifications.html:828` `#notifications-list` |
| Per-msg ⏸ render | `notifications.js:14696` (render-all `notification-corner-pause-btn`) + builder `:13869` |
| Per-msg ⏹ render | `notifications.js:13919` `notification-corner-stop-btn` |
| Pause/resume click → class flip | `notifications.js:14718-14744` (toggles `is-paused-current`) |
| Active-TTS class driver | `notifications.js:14903-14971` (adds/removes `is-playing-current` / `is-paused-current` as audio engages/ends) |
| proxy-ratify-link | `notifications.js:7161` `createProxyRatifyLink()` (gate: `groupId.startsWith('pr-')`) |
| CSS gate (port source) | `notifications.css:381-438` — `.notification-corner-pause-btn{display:none}` + `li.is-playing-current .notification-corner-pause-btn, .sender-message.tts-playing .notification-corner-pause-btn{display:inline-flex}` + `.is-paused-current` palette. **Note the already-present `.sender-message.tts-playing` selector — the mux-friendly (non-`<li>`) hook.** |

### Multiplexer (targets — add/edit)
| Element | Anchor | Action |
|---|---|---|
| Static mount order | `static/html/multiplexer.html:72-200` | **B1** restructure |
| Focus bar | `multiplexer.html:81` `#cc-session-strip` (currently top) | **B1** move below broadcast |
| TTS-preview mount | `multiplexer.html:101` `#tts-preview-slider-mount` (orphan sibling) | **B2** relocate into focus-bar header |
| Sessions pane | `multiplexer.html:104-115` `#notifications-pane`→`#action-required-section`(L110)→`#sender-cards-container`(L113) | **B1** keep contents, reposition pane |
| Broadcast mount | `multiplexer.html:133` `#broadcast-card-mount` (currently bottom, sibling) | **B1** move to TOP, nest commons inside |
| Recent-Activity | `multiplexer.html:138-184` `#commons-activity-pane` (separate sibling) | **B1** re-nest INSIDE broadcast card |
| Boot mount wiring | `multiplexer/boot.ts:456-484` (`createCommonsActivityRenderer`/`createBroadcastCardRenderer`/`createTtsPreviewSliderRenderer` + `getElementById` lookups) | **B1/B2** re-point mount targets |
| Broadcast renderer | `multiplexer/render/BroadcastCardRenderer.ts` + template `render/templates/broadcastCard.ts` | **B1** host the nested commons slot |
| Commons renderer | `multiplexer/render/CommonsActivityRenderer.ts` + `render/templates/commonsActivityEntry.ts` | **B1** mount into broadcast subtree |
| TTS-preview renderer | `multiplexer/render/TtsPreviewSliderRenderer.ts` + `render/templates/ttsPreviewSlider.ts` | **B2** placement contract only (component done, F6) |
| Section-header (B3) | **NEW** — section-header chrome around `#notifications-pane`; no current mux equivalent (`#section-toolbar-mount` L72 is a *different* mechanism — per-section visibility) | **B3** build |
| Message bubble | `multiplexer/render/templates/notificationItem.ts:60-110` (`.sender-message`, flat + progress-group branches) | **B4** add corner ⏸/⏹ + ratify-link |
| Sessions renderer | `multiplexer/render/NotificationsListRenderer.ts` | **B4** wire click delegation + class driver |
| Active-TTS state source | `multiplexer/stores/AudioStore.ts` (`state()` = idle/playing/paused; `queueLength()`, `pause()/resume()/skip()/stop()`) + `audio/SequentialAudioManager.ts` | **B4** — see §8 open question: AudioStore does **not** currently expose the *id_hash* of the message being spoken |
| TTS chrome (existing class helper) | `multiplexer/render/TtsChromeRenderer.ts` + `render/templates/ttsChrome.ts:67-69` (already ports `is-playing-current`/`is-paused-current`) | **B4** reuse the class vocabulary |
| Shared CSS surface | `static/css/shared/notifications-surface.css` (736 lines) — does **not** yet contain corner-btn / section-header / `cc-tts-fraction` selectors | **B5** port from `notifications.css` |

## 4. Dependencies & prerequisites

**Inherits all 7 cross-cutting mandates** from `00-plans-index.md` (100% L/B/F · Oracle Tiers 0–4 · single-source CSS · venue routing · manage-don't-build/lane isolation · coordinate-with-in-flight-crews · doc touchpoints). Below are the plan-specific prereqs.

### 4.1 Pre-req checks BEFORE any B1 code (gating)
1. **Confirm per-card collapse actually shipped in `4b33ceb7`** (NOT stranded on Rachel's `mux-section-toolbar-accordion-toggle` branch). Doc 02 §1 records it as double-owned: DFB Lane B claims "already wired, 11/11" folded into `4b33ceb7`, *and* D06/Rachel's branch is commit-held with no ref. **B4/B1 must verify** the collapse toggle is live in the `4b33ceb7` tree before restructuring — otherwise B1 restructures a mount whose collapse owner is unmerged, risking a double-ownership collision (doc 02 §"per-card-collapse double-ownership question"). Verification = grep the `4b33ceb7` working tree for the collapse handler + run the 11/11 lane test; if absent → coordinate the merge order with Rachel first.
2. **Coordinate with Tiberius's crew before restructuring `4b33ceb7`** (mandate 6). The `4b33ceb7` commit is **push-held for Rick** (store item `34466d69`) on `wip-v0.1.9-2026.06.21-bug-fix-implementation`; the full-parity build is mgr **Tiberius 👑** (`704c71b2`), verification **Krishna 🦚** (`0d69e015`), Foundation merged `3a5d87eb`. Because `4b33ceb7` is push-held, B1 can restructure it *before it lands upstream* (no revert of pushed history) — but only after confirming no unpushed follow-up from Tiberius's crew targets the same broadcast/commons mounts (doc 02 §6 prereq ii).

### 4.2 The B1 ↔ `4b33ceb7` conflict (doc 02 §2 — must resolve in execution)
`4b33ceb7` mounted `#broadcast-card-mount` (L133) **above** `#commons-activity-pane` (L138) as **two siblings** ("mirrors legacy order" per the L130-132 comment — but the mounts don't). Rick's B1 ruling (decisions (a)+(b)) wants the **opposite topology**: commons **nested inside** the broadcast card, whole broadcast block at the **TOP**, focus bar beneath. So B1 is not a greenfield add — it **edits freshly-committed, push-held code**. Sequence B1 to fold into / land on top of `4b33ceb7`.

### 4.3 Component / data prereqs
- **B2** rides the **done** F6 `TtsPreviewSliderRenderer` (100% L/B/F per doc 02 §1) — only a *placement* contract is net-new; no component rebuild.
- **B4** depends on an **active-TTS → notification-id_hash signal** that AudioStore does not currently expose (§8 OQ-1). Legacy ties `is-playing-current` to a specific list item via the TTS-queue activation path (`notifications.js:14903-14971`). The mux AudioStore only models `state()` (idle/playing/paused) with no per-notification identity. **This is a prerequisite design decision**, not a code detail — flagged for reviewers.
- **B3** `#history-dropdown-container` (legacy `notifications.html:666`) is populated by a history-dropdown component; confirm the mux has (or needs) an equivalent before building the slot.
- **INI/endpoints**: commons hydrate `/api/commons/broadcast-history` (CommonsActivityRenderer), `store_session_strip_changed` event (recipient/persona-filter refresh) — both already wired (`boot.ts:452-465`); B1 must preserve them across the re-nest. No new endpoints anticipated.

## 5. Work breakdown

Each bucket: **what · files · ACs (functional + structural) · Oracle tier(s)**. Buckets are ordered; B5 is gated last.

### B1 — Restore section order + re-nest Recent-Activity (restructure `4b33ceb7`)
**What**: Reorder the `multiplexer.html` mount points to legacy top→bottom — Broadcast card (TOP) → Focus bar → Sessions — and re-nest `#commons-activity-pane` *inside* the broadcast card subtree (currently a sibling at L138). Restructures the `4b33ceb7` sibling mount (§4.2).

**Files**:
- `static/html/multiplexer.html` — move `#broadcast-card-mount` (L133) above `#cc-session-strip` (L81); move `#cc-session-strip` below broadcast; relocate `#commons-activity-pane` (L138) to render *within* the broadcast card. Net target order: `#section-toolbar-mount` → `<h1>` → **broadcast-card-mount (with commons nested)** → **cc-session-strip (focus bar)** → `#missed-badge-mount` → `#notifications-pane` (sessions) → `#jobs-pane` → fleet/task/tts panes.
- `multiplexer/boot.ts:456-484` — re-point `getElementById` mount lookups; ensure CommonsActivityRenderer mounts into the broadcast subtree (a child slot inside `broadcastCard.ts`), not the standalone pane. Preserve `store_session_strip_changed` subscription + `/api/commons/broadcast-history` hydrate.
- `multiplexer/render/templates/broadcastCard.ts` — add a child mount slot (e.g. `#broadcast-recent-activity-slot`) hosting the commons subtree, mirroring legacy nesting (`notifications.html:740` inside `:692`).
- `multiplexer/render/BroadcastCardRenderer.ts` / `CommonsActivityRenderer.ts` — adjust mount wiring to the nested slot.

**ACs**:
- *Structural*: mount document-order in `multiplexer.html` is broadcast → focus-bar → sessions (verified by DOM-spine assertion, Oracle T1). `#commons-activity-pane` (or its renamed slot) is a **descendant** of `#broadcast-card-mount`'s rendered card, not a sibling (T1 parent assertion).
- *Functional*: broadcast send still works; Recent-Activity still hydrates from `/api/commons/broadcast-history`; persona-filter still refreshes on `store_session_strip_changed`; focus toggle + hide-inactive toggle on the strip still function in their new position.
- *Conflict-resolution*: the change lands as an edit folded into / on top of `4b33ceb7` (push-held), with §4.1 pre-req checks passed.
- **Oracle**: **T1 (DOM-contract — primary gate)** for order + nesting; T0 (CSS-hash unchanged where untouched); T3 (geometry) deferred to B5.

### B2 — Relocate TTS-preview slider into the focus-bar section header
**What**: Move the F6 `#tts-preview-slider-mount` (orphan sibling at `multiplexer.html:101`) into/above the focus-bar section header, matching legacy's placement in the section header (`notifications.html:641-665`, right-aligned via `margin-left:auto`).

**Files**:
- `static/html/multiplexer.html` — relocate the `#tts-preview-slider-mount` div from L101 into the section-header chrome built in B3 (above the focus bar), or into the focus-bar header region per the resolved topology.
- `multiplexer/boot.ts:478-484` — update the mount lookup if the element id/position changes (keep the id stable to avoid a renderer change).
- No `TtsPreviewSliderRenderer.ts` / `ttsPreviewSlider.ts` change — component is done (F6); placement-only.

**ACs**:
- *Structural*: `#tts-preview-slider-mount` is a child of the section-header region above `#cc-session-strip`, not a standalone sibling (T1).
- *Functional*: slider still reads/writes the StorageService-backed fraction with the INI default seed (`boot.ts:478-483` seed path preserved); drag does not toggle any accordion (legacy uses `event.stopPropagation()` — replicate).
- **Oracle**: T1 (placement) + T2 (computed-style: right-alignment / `margin-left:auto`) at B5.

### B3 — Build section-header controls (count · filter-badge · history-dropdown · clear-all)
**What**: Build the section-header control cluster the mux lacks. Doc 01 §2 marks these "0 refs" in mux; `#section-toolbar-mount` (L72) is a *different* mechanism (per-section visibility). **First confirm absent vs renamed** (methodology §5 step 5) before building.

**Files**:
- `static/html/multiplexer.html` — add a section header above `#notifications-pane` carrying: count span, filter-mode badge, history-dropdown container, clear-all button (legacy ids `#notifications-count`, `#notifications-filter-badge`, `#history-dropdown-container`, `#clear-all-notifications` — port verbatim where the mux delegated-listener convention allows, or document the rename).
- **NEW** renderer (or extend an existing section renderer) under `multiplexer/render/` to drive count/badge state from the NotificationStore + wire clear-all + history-dropdown.
- `multiplexer/boot.ts` — mount + wire.
- `static/css/shared/notifications-surface.css` — section-header styles (port from `notifications.css`, B5).

**ACs**:
- *Pre-req*: documented grep proving each of the four controls is **absent (not renamed)** in the mux bundle before building (methodology §5 step 5).
- *Functional*: count reflects live notification total; filter-badge reflects current filter mode; clear-all clears the list (disabled when empty, per legacy `disabled` default at `notifications.html:678`); history-dropdown opens/loads history.
- *Structural*: header sits above the focus bar / sessions per legacy order (T1), with the B2 slider slotted in (right-aligned).
- **Oracle**: T1 (presence + order) + T2 (computed-style) at B5.

### B4 — Per-message active-TTS-gated ⏸/⏹ + proxy-ratify-link
**What**: Add `notification-corner-pause-btn` (⏸/▶) + `notification-corner-stop-btn` (⏹) + proxy-ratify-link to **every** message bubble, but **CSS-gate visibility to the single actively-spoken message** — replicating legacy render-all + `is-playing-current` gate. **A static per-bubble render is the wrong implementation** (`00-index.md` §B4, decision (c)).

**Files**:
- `multiplexer/render/templates/notificationItem.ts:60-110` — render the two corner buttons (`display:none` by default) into both the flat and progress-group branches; render the proxy-ratify-link when `progress_group_id` starts with `pr-` (legacy gate `notifications.js:7168`).
- `multiplexer/render/NotificationsListRenderer.ts` — (1) delegated click listeners: pause-btn toggles `is-paused-current` on its `.sender-message` and calls `AudioStore.pause()/resume()`; stop-btn calls `AudioStore.stop()`; ratify-link calls the acknowledge endpoint (port `createProxyRatifyLink` behavior). (2) an **active-TTS class driver** that adds/removes `is-playing-current` / `is-paused-current` / `tts-playing` on the bubble matching the currently-spoken notification, driven off the AudioStore state transitions (legacy analog `notifications.js:14903-14971`).
- `multiplexer/stores/AudioStore.ts` and/or `audio/SequentialAudioManager.ts` — **likely an extension** to expose *which* notification id_hash is currently being spoken (see §8 OQ-1); reuse the existing `is-playing-current`/`is-paused-current` vocabulary already in `templates/ttsChrome.ts:67-69`.
- `static/css/shared/notifications-surface.css` — the gate selectors (B5): `.sender-message.tts-playing .notification-corner-pause-btn{display:inline-flex}` etc. (port from `notifications.css:381-438`; note `.sender-message.tts-playing` already exists there as the non-`<li>` hook).

**ACs**:
- *Structural*: every `.sender-message` carries the two corner buttons in the DOM (T1), but only the bubble matching the active TTS message has them visible (computed `display` ≠ none — T2). Proxy bubbles (`pr-` group) carry the ratify-link; non-proxy bubbles do not.
- *Functional*: when TTS reaches a message, exactly that bubble's ⏸/⏹ become visible; pause flips ⏸↔▶ via `is-paused-current` and pauses/resumes audio; stop halts + advances; ratify-link opens ratification + retires the batch. Exactly one bubble visible at a time (Rick's constraint, `00-index.md` §B4).
- *Negative*: a static-render regression (controls visible on non-active bubbles) **fails** the suite.
- **Oracle**: T1 (presence on all bubbles) + **T2 (the active-gate: visible only on `.tts-playing`)** — the load-bearing tier for B4 + T3 (corner geometry) at B5.

### B5 — CSS / Oracle Tier-2/3 pass + golden rebaseline (gated last)
**What**: Single-source the CSS for everything B1–B4 touched into `css/shared/notifications-surface.css` (never fork a copy — mandate 3); run the Tier-2/3 pass; rebaseline goldens. Gated on B1–B4 structural ACs green (methodology §5 steps 7–8 — CSS diff only after DOM is clean).

**Files**:
- `static/css/shared/notifications-surface.css` — port the corner-btn gate (`notifications.css:381-438`), the section-header cluster styles, and the `cc-tts-fraction` slider placement styles; the legacy `notifications.css` links the shared sheet before its monolith (mandate 3).
- Golden captures under the Oracle fixtures (legacy `:8000` capture cost per mandate 2).

**ACs**:
- *Structural*: zero forked CSS — all new selectors live in the shared surface; legacy + mux both consume it.
- *Visual*: T2 computed-style parity on header controls, slider alignment, corner-btn states; T3 geometry parity on the reordered section (broadcast/focus/sessions) and corner-btn placement; T4 pixel backstop only where T0–T3 leave residual.
- *Rebaseline*: new goldens captured for the reordered section + per-message corner controls; the two documented CC-card carves (doc 02 §4 — AR read-only↔interactive node; CC-card ~51px height re-scoped into F5-v) remain carved, not regressed.
- **Oracle**: T0→T4 full sweep; this bucket is where T2/T3/T4 gate.

## 6. Test strategy & venue routing

Inherits mandate 1 (**100% lines/branches/functions** — Python `pytest --cov-fail-under=100`; TS `c8 --100`; `# pragma: no cover` / `c8 ignore` only for genuinely-unreachable defensive branches with a same-line reason) and mandate 4 (venue routing).

- **:7999 (AI-discretionary)** — TS unit tests for every new/edited renderer + template (B1 mount-nesting, B2 placement, B3 header renderer, B4 corner-control template + class driver + click delegation); `c8 --100` on lane-owned files; the storeless parity harness (`testkit/parityFixture.ts`) for DOM-spine assertions (Oracle T1); inline `quick_smoke_test`/import-chain + `py_compile` for any Python touched. WebSocket smoke (`src/scripts/run-websocket-smoke-tests.sh`) if B4's audio-state wiring touches the audio WS path.
- **:8000 (scheduled via `POST /api/test-suite/submit`, self-authorized on a verified-idle server — `list-pending` first; never side-door)** — E2E UI + visual regression (`src/scripts/run-e2e-ui-tests.sh --bg`, includes `-k visual`) for the reordered section + active-TTS gate; the integration FINAL gate (`src/tests/run-integration-tests.sh --bg`) before any merge. Golden rebaseline (`--update-snapshots`) after B5 structural green.
- **New fixtures**: a CC-session fixture mounting broadcast(+nested commons) → focus → ≥2 sessions with ≥1 progress group + ≥1 proxy (`pr-`) message + an active-TTS state, to exercise B1 nesting, B3 header, and the B4 single-active gate (methodology §5 step 7 ground-truth render).
- **Negative test (B4)**: assert corner controls are NOT visible on non-active bubbles (guards against the static-render anti-pattern).

## 7. Oracle & visual parity

Tiers per mandate 2 (methodology `2026.06.19-…/01-layout-parity-methodology.md`):
- **T0 CSS-hash** — confirm untouched nodes' CSS unchanged; flag the shared-surface additions (B5).
- **T1 DOM-contract** — **the primary gate for B1/B2/B3** (order + nesting + presence). DOM-spine must include `multiplexer.html` mount order (methodology §2: position is decided by mount order, not the renderer).
- **T2 computed-style** — **the load-bearing gate for B4** (active-TTS visibility gate) + B3 header alignment + B2 slider right-alignment.
- **T3 geometry** — reordered-section geometry + corner-btn placement (B5).
- **T4 pixel backstop** — residual only.

**Golden captures needed** (legacy `:8000` capture cost): (1) reordered CC-section (broadcast-top → focus → sessions); (2) Recent-Activity nested inside broadcast; (3) section-header control cluster; (4) per-message corner controls in the active-TTS state (one bubble visible). Rebaseline gated on B1–B4 structural ACs green (methodology §5 steps 7–8). Preserve the two inherited carves (doc 02 §4).

## 8. Risks & open questions (for reviewers)

- **OQ-1 (load-bearing — B4): AudioStore exposes no per-notification identity.** `AudioStore.ts` models only `state()` ∈ {idle, playing, paused} (no id_hash of the message being spoken). Legacy drives `is-playing-current` from the TTS-queue activation path keyed to a specific list item (`notifications.js:14903-14971`). The mux needs an **active-TTS → notification id_hash signal** to gate exactly one bubble. **Decision needed**: extend AudioStore / SequentialAudioManager to emit the currently-spoken notification id (cleanest), or have NotificationsListRenderer correlate via a separate channel? This is a design prerequisite, not a detail — it determines B4's seam and its test surface.
- **OQ-2 (B1 sequencing): per-card collapse double-ownership.** Doc 02 §1 lists the collapse toggle as owned by *both* DFB Lane B (folded into `4b33ceb7`, "11/11") and D06/Rachel (`mux-section-toolbar-accordion-toggle`, commit-held). §4.1 pre-req #1 must resolve which is canonical **before** B1 restructures the mount, or B1's edit collides with an unmerged collapse owner. Reviewers: confirm the merge order with Rachel + Tiberius.
- **OQ-3 (B1 ↔ `4b33ceb7`): restructuring push-held code.** B1 edits the freshly-committed, push-held `4b33ceb7` to invert its sibling topology (broadcast+commons siblings → commons nested in broadcast, broadcast at top). Safe because unpushed (no history revert), but requires confirming no unpushed follow-up from Tiberius's crew touches the same mounts (§4.2 / doc 02 §6 prereq ii). Reviewers: is folding into `4b33ceb7` preferred over a stacked commit on top of it?
- **OQ-4 (B3): is the legacy history-dropdown component portable?** `#history-dropdown-container` (`notifications.html:666`) is populated by a JS history-dropdown the mux may not have. Confirm whether B3 ports the component or just the slot.
- **OQ-5 (B4): proxy-ratify-link endpoint reuse.** `createProxyRatifyLink` (`notifications.js:7161`) calls an acknowledge/retire endpoint. Confirm the mux apiClient already exposes it (else B3/B4 add a thin wrapper).
- **Risk**: B1's mount reorder is a convergence-file edit (`multiplexer.html`, `boot.ts`) — **manager-serial-merge** (mandate 5), not a parallel-lane free-for-all, to avoid colliding with Tiberius's `multiplexer.html` edits.

## 9. Lane decomposition & estimate

Convergence files (manager-serial-merged — mandate 5): `multiplexer.html`, `boot.ts`, `css/shared/notifications-surface.css`, the EventBus/`types.ts` union (if OQ-1 adds an audio-id event).

| Lane | Buckets | Files (lane-owned vs convergence) | Rough size | Notes |
|---|---|---|---|---|
| **L-order** | B1 + B2 | `multiplexer.html`*, `boot.ts`*, `broadcastCard.ts`, `BroadcastCardRenderer.ts`, `CommonsActivityRenderer.ts` | M (mostly mount/nesting rewiring; no new component) | Must land first / fold into `4b33ceb7`; gates the rest. *=convergence |
| **L-header** | B3 | new section-header renderer + template, `multiplexer.html`*, `boot.ts`* | M–L (new renderer + confirm-absent grep + history-dropdown decision) | Depends on L-order's header region existing for B2's slider slot |
| **L-tts** | B4 | `notificationItem.ts`, `NotificationsListRenderer.ts`, `AudioStore.ts`/`SequentialAudioManager.ts`*, `types.ts`* | L (gated on OQ-1 design) | Heaviest; the active-TTS id signal is the long pole |
| **L-css** | B5 | `css/shared/notifications-surface.css`* | S–M (port + rebaseline) | Gated LAST on L-order/L-header/L-tts structural-green |

**Sequencing**: L-order → (L-header ∥ L-tts) → L-css. Pre-req checks §4.1 block L-order. Total: a medium-sized multi-lane effort dominated by B4's AudioStore extension (OQ-1) and B1's `4b33ceb7` restructure coordination.

**Doc touchpoints** (mandate 7): on completion update `00-index.md` (mark B1–B5 closed), this folder's discrepancy ledger, `src/docs/websocket-events.md` only if OQ-1 adds an audio-id event, and the layout-parity methodology golden manifest with the new captures. No `lupin-app.ini` keys anticipated.
