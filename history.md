# Lupin Project History

> **Archives**: See [history/README.md](history/README.md) for the full chronological index. Most recent: [2026-05-12 to 05-15](history/2026-05-12-to-15-history.md). History health: ✅ **HEALTHY at 9,853 tokens (39.4% of 25k)** — archived 2026-05-17 by Tiberius 🌑 (session 2d916480), 31,413 tokens moved to archive.

### 2026.05.22 - Session 76351966 (Rio ⚡) | Heartbeat-poker CJ Flow ingestion wiring (gap-close)

Follow-on to the heartbeat-poker run (commit `cd37c3f`): closed the gap surfaced + escalated during I6 — `HeartbeatPokerJob` was not dispatchable through CJ Flow because `agentic_job_factory` had no `heartbeat_poker` entry. Tiberius assigned the close per Rick's follow-through directive.

**Factory wiring**: added the `agent router go to heartbeat poker` branch to `agentic_job_factory.create_agentic_job()` — parses `recipients` (dict list → `RecipientSpec` list), `termination_signal_kinds` (list or CSV), and the `_parse_optional_int` defaults; constructs the `HeartbeatPokerJob` + a `LupinCommonsGateway`. Added `LupinCommonsGateway.from_environment()` — the production IO-boundary constructor (real `CommonsStore` + API key + `requests`); `# pragma: no cover` with reason (exercised by the :8000 integration tier, not unit-mockable in isolation).

**Tests**: 11 factory-wiring unit tests (`test_agentic_job_factory_heartbeat.py`, new) + 1 factory-dispatch smoke test. Full local heartbeat suite — 78 tests green; both heartbeat modules hold gate-enforced 100% line+branch coverage. Integration + E2E skip-marks updated — the missing-wiring clause dropped (integration now venue-only; E2E now task-I7-only); both collect clean (5 tests, `--collect-only`).

**Files** — parent-Lupin (this commit): `src/tests/integration/test_heartbeat_poker_integration.py`, `src/tests/e2e/test_heartbeat_poker_e2e.py`, `history.md` (this entry). CoSA submodule (committed separately, own context): `heartbeat_poker_commons_gateway.py`, `agentic_job_factory.py`, `test_agentic_job_factory_heartbeat.py`, `test_heartbeat_poker_smoke.py`.

---

### 2026.05.22 - Session 76351966 (Rio ⚡) | Heartbeat-poker abstraction implementation (10-task run) + TTS limiter boundary-scan fix

Two bodies of work this session.

**TTS limiter — boundary-scan rewrite.** The notifications TTS preview-fraction slider truncated by sentence count; a newline-separated technical list (no `.!?` punctuation) defeated the splitter and read ~half the list aloud at the 25% stop. Replaced the sentence-count algorithm in `_computeTTSPreview()` with a character-position forward scan: jump to `ceil(length × fraction)`, then scan forward to the next boundary — a sentence terminal, an em/en-dash, or a **newline** (the key fix: a list item ends at a newline even with no punctuation). New `_truncateAtBoundary()` helper; `_splitIntoSentences()` retired; inline self-test rewritten (8 cases, verified in Node). Hyphen-minus deliberately NOT a boundary. The vestigial `tts preview include semicolons` INI key + splainer entry removed.

**Heartbeat-poker abstraction — full 10-task implementation run (Tiberius-managed).** Implemented the approved `src/rnd/v0.1.7/2026.05.20-generic-heartbeat-poker-abstraction-design.md` plan end-to-end: 3 design-tier specs (D1+D4 class spec, D2 Watcher-protocol spec, D3 co-exist/swap/retirement doc); the `HeartbeatPokerJob` `AgenticJobBase` subclass + its three layered exits — clean-signal / dead-man's-switch / hard-cap (I1, I2); a production `LupinCommonsGateway` adapter; the `implementer-watch-protocol.md` Layer-2 doctrine (I3); two new termination-signal kinds in the PIP cascade defaults (I5); the full test pyramid (I6); Manager/Observer protocol `poke_body` compatibility (I9); and the production agentic-pool override (I10). Verified: 66 tests (58 unit + 8 smoke) green, 100% line+branch coverage (`pytest-cov --cov-fail-under=100`) on both heartbeat modules; integration + E2E files written + skip-marked for `:8000`. Swap-validation gates I4a-d/I7/I8 left for the operator-event-driven post-run. One gap surfaced + escalated to Tiberius: `HeartbeatPokerJob` is not yet wired into `agentic_job_factory` CJ Flow ingestion.

**Verification**: TTS — `node --check` + 8/8 inline self-test cases + config-load. Heartbeat — 66 tests green, gate-enforced 100% line+branch on `heartbeat_poker_job.py` + `heartbeat_poker_commons_gateway.py`; INI parse confirmed.

**Files** (parent-Lupin, this commit): `src/fastapi_app/static/js/notifications.js`, `src/fastapi_app/static/html/notifications.html`, `src/conf/lupin-app.ini`, `src/conf/lupin-app-splainer.ini`, `src/rnd/v0.1.7/2026.05.22-tts-limiter-boundary-scan.md` (new), `src/rnd/v0.1.7/2026.05.22-heartbeat-poker-d1d4-class-spec.md` (new), `src/rnd/v0.1.7/2026.05.22-heartbeat-poker-d2-watcher-protocol-spec.md` (new), `src/rnd/v0.1.7/2026.05.22-heartbeat-poker-d3-coexist-and-swap.md` (new), `src/docs/agents/implementer-watch-protocol.md` (new), `src/tests/integration/test_heartbeat_poker_integration.py` (new), `src/tests/e2e/test_heartbeat_poker_e2e.py` (new), `history.md` (this entry).

**Committed separately** (own repos, own contexts): CoSA submodule — `heartbeat_poker_job.py`, `heartbeat_poker_commons_gateway.py`, `system.py`, `test_heartbeat_poker_job.py`, `test_heartbeat_poker_commons_gateway.py`, `test_heartbeat_poker_smoke.py`. planning-is-prompting repo — `plan-review-cascaded-defaults.md`, `plan-review-cascaded-common.md`.

---

### 2026.05.22 - Session 2ce59c03 (Tiberius 🌑) | Voice persona: `request_persona` MCP tool + compaction carry-forward fix

Triggered by a live observation — the Mr. Radio session went through a context compaction and came back re-allocated as Krishna. Rick asked for two fixes, done in his stated order.

**`request_persona` MCP tool** — new `@mcp.tool` (plus `_request_persona` helper + `_persona_error_detail`) in `cosa_voice_mcp.py`, modeled on the speakerphone-toggle tool. Wraps the existing allocate/swap endpoint with the strict `requested_persona_name` query param; maps `200` → ok, `422` → not_in_pool, `409` → occupied, else → error. No degraded bridge-write fallback — allocation stays behind the server's `_voice_persona_lock`. First MCP-surfaced way to request or reclaim a named persona.

**Compaction carry-forward fix** — the `register_session.py` carry-forward gate was keyed on `is_context_clear`, which is True only when the transient session UUID rotates. A compaction can keep the same id, so the persona was dropped, the defense-in-depth block released it, and Phase 4.5 re-rolled (Mr. Radio → Krishna). Dropped `is_context_clear` from the gate: whenever a prior bridge holds a valid `voice_persona` dict it is preserved — across `/clear`, `/compact`, resume, and `--continue`. The fix is live immediately (SessionStart hooks are re-exec'd per event).

**Verification**: 30/30 unit tests (19 new for the tool, 11 register_session incl. 2 new compaction/resume cases); 38/38 sibling MCP tests pass (no regression); 100% branch coverage on all new code; live E2E against `:7999` exercised the `409 occupied` and `200 ok` response paths.

**Files**: `src/lupin_mcp/cosa_voice_mcp.py`, `src/lupin_cli/claude_code/hooks/register_session.py`, `src/tests/unit/test_cosa_voice_mcp_request_persona.py` (new), `src/tests/unit/test_register_session_preservation.py`, `src/tests/smoke/test_mcp_smoke.py`, `src/rnd/v0.1.7/2026.05.22-voice-persona-request-tool-and-compaction-carry-forward.md` (new), `history.md` (this entry).

---

### 2026.05.21 - Session 679e8f04 (Mr. Radio 🦉) | Recent Activity filter strip + Focus-bar chronological lock + Master-detail two-pane layout experiment

#### Checkpoint 3 | 2026.05.21 19:10 EDT | Iframe doc-link interception — root-cause fix; master-detail experiment pinned pending cascade review

Post-Checkpoint-2 follow-up. Rick kept hitting "localhost refused to connect" when clicking doc-links **inside** the Reading Pane's iframe. Earlier patches (document-viewer.html render-time URL rewrite, parent-page click interceptor) didn't resolve it because the failure is architectural, not a regex gap:

- **Clicks inside an iframe do NOT bubble to the parent document.** The parent's `document`-level click interceptor is structurally blind to iframe-internal clicks — an iframe is a separate browsing context.
- The only handler for iframe-internal links was `document-viewer.html`'s own render-time rewrite. That file is **cache-fragile**: the iframe lazy-loads `/app/docs?path=...` AFTER the parent page is interactive, so parent hard-reloads never bust it — the iframe kept serving a stale cached `document-viewer.html` predating the rewrite.

**Fix — parent-owned iframe link interception**: the iframe is same-origin, so the parent can script into it via `iframe.contentDocument`. New `_bindIframeLinkInterception(frame)` attaches a delegated click handler to the iframe's document on every `load`. `/app/docs?path=` links route through `_openContentPane` (Back-history participates); external links open in a new tab; same-origin non-doc relative links navigate natively. Parent code is `?v=`-cache-busted so it is always current — the stale-`document-viewer.html` problem becomes irrelevant. `_normalizeDocLinkHref` broadened to strip `127.0.0.1` / `0.0.0.0` loopback prefixes, not just `localhost`. `document-viewer.html`'s own rewrite retained as harmless defense-in-depth (regex similarly broadened).

**Status**: master-detail experiment **PINNED** per Rick — the iterative tail-chasing is paused pending a fresh cascaded plan-review run (Tiberius managing). Cache buster `v=20260521i`.

**Files**: `src/fastapi_app/static/js/notifications.js` (+`_bindIframeLinkInterception`, broadened `_normalizeDocLinkHref`), `src/fastapi_app/static/html/notifications.html` (cache buster), `src/fastapi_app/static/html/document-viewer.html` (regex broadening).

**Commit**: c1d611e

---

#### Checkpoint 2 | 2026.05.21 18:30 EDT | Master-detail two-pane layout experiment — design + 7 iteration cycles + draggable splitter

Second feature of the session, designed + implemented + iterated through Rick's voice feedback over the late afternoon. Switchable two-pane "horizontal" layout: existing `.container` collapses to ~2/3 width inside a new `.left-column`; new `<aside class="content-pane">` Reading Pane occupies the right ~1/3; draggable splitter between; persistent split ratio; section-toolbar floats horizontally over the top-center of the content area.

**Process pattern (re-applied from morning feature)**: pre-impl exploration → item-by-item walkthrough of 6 design choices via `ask_yes_no` / `ask_multiple_choice` → reuse-review pass → Phase 1/2 implementation → iterative tweaks driven by live visual feedback on `:7999`.

**Locked decisions (walkthrough)**: Reading Pane name; iframe for doc-links; Close + Back only (no Forward); mode-toggle button at top of `.section-toolbar` with `⇆` icon; respect-toggle on narrow viewports; never-interrupt-pane on notification arrival.

**Iteration log (visual feedback rounds)**:
1. Initial skeleton — Rick reported: iframe "localhost refused to connect" + empty pane occupying screen + container stretched + content jammed against scrollbar.
2. `document-viewer.html` rewrites absolute `http://localhost:port/` URLs to host-relative on render (universal fix — every doc-viewer user benefits); `.pane-open` class on `.content-shell` gates the 2-pane flex split; `scrollbar-gutter: stable` + 18-22px pane padding.
3. Draggable splitter (`notifications_pane_split_ratio` localStorage, clamps to `[0.30, 0.85]`, default 0.667); 80% max-width on container for breathing room.
4. Toolbar reposition attempt #1 — kept vertical column, anchored right.
5. Rick clarified "horizontal row, over the center of content area" — re-flipped to horizontal row.
6. Centering formula flipped from "over pane" to "over container" (`ratio/2 * 100%` not `(1+ratio)/2 * 100%`).
7. Toolbar pushed from `top: 136px` → `top: 56px` (just below `.lupin-nav` at 56px); `padding-top: 52px` on `.container` to clear the H1 from under the toolbar.

**Final geometry summary**:
- `body[data-layout-mode="horizontal"]` attribute gates all horizontal-mode CSS.
- `.content-shell.pane-open` activates flex-row split (left column flex:ratio, pane flex:1-ratio via inline JS).
- `.section-toolbar`: `position: fixed`, `flex-direction: row`, `width: max-content`, `top: 56px`, `left: var(--toolbar-center-x)`, `transform: translateX(-50%)`. JS pushes `(ratio/2)*100%` into the CSS variable on init/toggle/drag.
- `.content-pane`: sticky, `min-width: 360px`, body has `scrollbar-gutter: stable` + generous padding.
- `.content-pane-splitter`: 6px col-resize divider, hover/dragging visual state, body gets `.splitter-dragging` class during drag.

**Cross-cutting fix**: `document-viewer.html` now rewrites absolute-localhost anchors on render — universal benefit.

**Files**:
- `src/fastapi_app/static/html/notifications.html` (content-shell wrapper + content-pane skeleton + layout-mode-btn + splitter)
- `src/fastapi_app/static/css/notifications.css` (mode-gated horizontal layout rules + splitter + toolbar repositioning + pane padding)
- `src/fastapi_app/static/js/notifications.js` (constructor hydration + 9 new methods including `_initMasterDetailLayout`, `_toggleLayoutMode`, `_openContentPane`/`_closeContentPane`/`_backContentPane`, `_renderContentPaneEntry`, `_initPaneSplitter`, `_applyPaneSplitRatio`, `_updateToolbarPosition` + `.abstract-indicator` mode-branch)
- `src/fastapi_app/static/html/document-viewer.html` (absolute-localhost link rewriter)
- `src/rnd/v0.1.7/2026.05.21-master-detail-two-pane-layout-experiment.md` (NEW design doc with Resolved Design Choices + Reuse Review tables)
- `history.md` (this entry)
- `.claude-session.md` (Checkpoint 2 entry)

**Cache busters bumped**: `v=20260521a` → `g` across the 7 iteration cycles.

**Commit**: b599303

---

#### Checkpoint 1 | 2026.05.21 14:50 EDT | Part A filter strip + Part B chrono lock + Playwright e2e suite all green

**Two related broadcast/strip enhancements designed, implemented, tested**:

**Part A — Recent Activity Filter Strip** (`#commons-recent-activity-section`):
- Three inline native `<select>` dropdowns inside the existing `.commons-recent-activity-controls` flex row (no chip sub-row, dual-refresh consolidated to the single existing `↻` button per Rick's redundancy callout)
- Axes intersect with boolean AND: **Direction** (Sender · Recipient, mutex), **Kind** (All · Heartbeats · Personas · Broadcasts — 4-option per Rick's walkthrough amendment), **Persona** (chip per active session, sourced from `/api/cosa-voice/voice-persona/pool`)
- "Personas" predicate tightened to `topic.startsWith("dm-") && metadata.kind !== "heartbeat"`; "Broadcasts" unifies `broadcasts` + `broadcast-acks` topics; Direction=Recipient is a silent no-op when Kind=Broadcasts (broadcasts fan out)
- Filter dropdowns are **client-side instant** over the in-memory raw-entry cache — no server hit on change. The existing `↻` reload button is the only server-hit path (refreshes activity stream + persona dropdown options in one click, sticky-when-valid persona selection)
- **Filter state persists across page reload** via `notifications_commons_activity_filter` localStorage key (matches existing `notifications_*` convention)
- Filter-aware empty-state copy ("No activity matches the current filter" when any axis is active)

**Part B — Focus-bar Chronological Lock** (`#cc-session-strip`):
- `_addStripIcon` now stamps `data-created-at` from `persona.assigned_at` and ALWAYS appends (kills the `insertAtTop=true` prepend branch)
- `_promoteStripIcon` renamed to `_markStripIconActivity` — unread-badge pulse preserved untouched, `insertBefore` DOM reposition removed
- New `_sortStripIconsChronological()` helper runs once after `loadConversationHistory()` in the startup chain; subsequent runtime adds just append
- Backend plumbing verified intact end-to-end: `voice_persona_helpers.py` stamps `assigned_at` on allocation; `_voice_persona_for_sender_id` preserves it through to the senders-visible endpoint and the `voice_persona_assigned` WS event. **No backend changes needed.**

**Persistence layer** (also added beyond the chrono lock):
- Augmented the global `toggleSection()` helper with a write-through for two tracked accordions: `notifications_broadcast_card_open` + `notifications_recent_activity_open`
- `applyPersistedAccordions()` runs on `DOMContentLoaded` (before first paint) to avoid flicker on reload
- Existing focus-mode persistence (`notifications_cc_focus_state`) verified wired — Rick's "not implemented" report appears to be a misperception; the localStorage round-trip is in place with belt-and-suspenders restore via `_restoreCcUiAfterLoad()` after `loadConversationHistory()` completes

**E2E Playwright suite — three rounds to ALL GREEN**:
- Round 1: 4 pass / 9 fail — controller-global typo in test file (`window.__notifications_controller__` vs canonical `window.notificationsUI`)
- Round 2: 11 pass / 2 fail — typo fixed; remaining 2 were test-timing bugs (dropdown init-lag after page reload + `wait_for_selector` waiting for `visible` on a correctly-collapsed element)
- **Round 3: 13 pass / 0 fail / 2 graceful skips** (`TestStripChronologicalOrder` skips gracefully when fewer than 2 CC strip icons hydrate on the test server, which has no live CC sessions)

**Incidents logged + memory updates**:
- Accidentally bounced `:8000` while my first submitted test was mid-flight (chained `refresh-test-server.sh` as a polling-loop prelude). Job vanished, server self-recovered, re-submitted cleanly with new `scheduled_at`. Lesson: bounce commands NEVER belong inside a polling loop.
- Saved new feedback memory: `feedback_never_defer_test_fixes_hold_fire_exception.md` — Rick's directive that hold-fire windows do NOT pause completing in-flight test fixes I wrote. "You wrote the code. You make it pass 100% coverage. Full stop!"

**Cross-session coordination**: Three DM exchanges with Tiffany 💍 (lupin-mobile session 1b3f8c46) tracking the design deltas — initial inventory ask, post-walkthrough delta, post-amendment delta. Mobile parity work continues unblocked; the only cross-cutting wire item (`voice_persona.assigned_at` plumbing) is verified intact.

**Files**:
- `src/fastapi_app/static/html/notifications.html` (3 dropdowns inserted + `toggleSection()` augmented with localStorage write-through + `applyPersistedAccordions()` early-paint restore)
- `src/fastapi_app/static/css/notifications.css` (flex-wrap + `.commons-activity-filter-select` styling)
- `src/fastapi_app/static/js/notifications.js` (constructor hydration of 3 new `*_KEY` constants + `_commonsActivityFilter` + `_commonsRawEntries`; filter predicate / re-render / change handlers / persona-pool refresh / augmented reload button; strip chronological-lock surgery)
- `src/rnd/v0.1.7/2026.05.21-recent-activity-filter-and-focus-bar-chronological-lock.md` (NEW — design doc with item-by-item walkthrough decisions + reuse-review pass + implementation-complete status)
- `src/tests/e2e_ui/test_commons_activity_filters_and_strip_chrono.py` (NEW — 15-test Playwright suite across 5 classes)

**Commit**: 35581a8

---

### 2026.05.20 - Session 173c0b35 (Tiberius 🌑) | Persona resuscitation commit + Run-4 post-game convergence + Heartbeat-Poker design WIP

#### 2026.05.20 PM | End-of-day wrap

**Persona resuscitation work committed** at `c9db97c` — Rachel's three-thread fix bundled: (1) `start-cc-with-tmux.sh` forwards three `COSA_VOICE_PREFERRED_PERSONA__*` env vars into the tmux session via `-e` flags (the actual fix for why Tiberius was randomly allocated); (2) Roscoe → Tiffany persona rename swept across `lupin-app.ini` + splainer + 5 R&D docs + 1 test fixture; (3) four temporary `[LOOKML-DEBUG]` stderr prints in `register_session.py` phase 4.5 (flagged in-source for removal once Sam confirms allocation runs clean). 10 files, +103/-52.

**Run-4 cascade post-game with María 🌸**: 4-DM convergence cycle on `dm-tiberius` (`0cfea56f` → `67ccf3f8` → `830f4833` → `52df46e2` → `569eeba8` → `614b41ab` → `830f4833`). Positions reached:
- Q1 inverse density-vs-doctrine — HOLD on operationalizing pending Runs 5-6 controlled-slot experiment
- Q2 forward-asymmetry 38→33→21 monotonic — don't formalize; 4 competing explanations indistinguishable at n=1
- Q3 "Manager ad-hoc'd what should be codified" diagnostic — STRONG FOLD, codified as Step 9 rubric Q#6
- Fold-order revised respecting dependency graph: 7 candidates + 1 placeholder
- Dual-administer gate timing: keep default Runs 5-6, HARDen at Run 7 if +2/3 ratio holds
- New candidate added: Observer-side probe-as-mitigation channel (per-stage INI keys; M=8 Stage 0, M=4 default, M=2 Stage 2)
- 4 pre-committed re-evaluation gates locked at design-doc §10.18.12

**PIP-side codification pass shipped** by María at commit `adcd96d` (10 files, +744/-17; committed not pushed per Rick's EOD directive). Bilateral review completed Lupin-side: 8/8 ratification checkpoints verified; 2 non-blocking observations filed as v1.2 polish candidates.

**Lupin TODO.md updated**: closed `[LUPIN-PIP]` v1.1 codification line item with full 7-candidate map; added 2 new entries (`start-cascade-heartbeat.sh --observer` flag + `commons_send_to` recipient pool-key vs display-name routing priority bump).

**Generic Heartbeat Poker abstraction design — WIP**: Rick proposed abstracting the cascade heartbeat shell-script into a Lupin-side `AgenticJobBase` subclass with N recipients + schedulable for off-peak execution. Conversation walked through 3 use cases (Observer / Manager / Watcher-of-implementer), landed two-layer architecture (generic poker + per-recipient doctrine), resolved Q1 (Path A — one minimal class), Q2 (3-layered exits: clean signal + dead-man's-switch escalation + hard cap), and concurrent-poker routing (two independent jobs, recipient routes via `poke_body` JSON metadata). Parked at Q3 (relationship to existing daemon) and doctrine-home open Q.

**Files**:
- Working tree at close: `TODO.md` (modified) + `src/rnd/v0.1.7/2026.05.20-generic-heartbeat-poker-abstraction-design.md` (NEW, ~260 LOC, WIP design doc)
- Committed: 10 files at `c9db97c`

**Standing playbook**: commit-only history.md tradition; Rick authorized EOD push at session-end.

---

### 2026.05.20 - Session 387b9201 (Tiberius 🌑) | Phase 7a Run 4 cascade-complete — implementer-handoff-ready

#### 2026.05.20 03:30 | Phase 7a Telemetry — Run 4 cascade closed 🟢 + Step 0 + Step 9 doctrine v1 validated

Managed Run 4 of cascaded plan-review workflow for Phase 7a Telemetry. **Cascade-complete 03:30:47 UTC; total wall-clock ~1h 30min** (Step 0 light-review through Step 9 close). Phase 7a implementer-handoff-ready.

**Cast**: Mr Radio 🦉 (Stage 0 Author), Rachel 🕊️ (Stage 1 Usability/Reuse), Krishna 🦚 (Stage 2 Risk/Anti-pattern + Step 9 light-review), Rio ⚡ (Stage 3 Ownership/Convention), María 🌸 (Observer + doctrine consultant), Tiberius 🌑 (Manager).

**Cascade outcomes**:
- Stage 1: 🟢 closed-clean (1F + 2P + 5 reuse confirms; cap-2 1/2 used)
- Stage 2: 🟡 closed-with-quibbles → cleanup folded (9 closed + 1 cosmetic + 4 doctrine-sweep quibbles; cap-2 1/2)
- Stage 3: 🟢 closed-clean (4 closed + 1 withdrawn; cap-2 1/2)
- Step 9: 🟢 close-clean post-revision (2 friction points + candidate #6 placeholder; cap-1 1/1)
- Net cap utilization: **8 of 14 possible revision turns = 57%**; 50%+ headroom preserved across every cap surface

**Manager footers (4 ratifications)**:
- R-3 Path A pin: drop `crash` from ReportingObserver registered types (PII safety; sanitizer-design deferred to v2 OSQ-T-6)
- Footer 2 Option A pin: block-on-config-fetch over non-blocking + replay
- Footer 2 sub-revision: Option A + 500ms `Promise.race` bounded timeout + safe-defaults fallback
- Closure-context references KEEP ruling (multi-surface sweep mandate is about active-claim violations, not historical scrubbing)

**Tier discipline outcome**: T1+T2 silent Manager-unilateral throughout; zero T3 escalations; zero T4 wake-ups; Rick stayed asleep as designed.

**Step 0 doctrine v1 validation**: ✅ STRONG. Pre-cascade recon (R-7a-1..R-7a-6 resolved upstream) eliminated browser-API archaeology from reviewer cycles. 3 reviewers concurred. Q→F→S→D recon shape empirically clean. 1 minor v2 candidate identified (persona-conventions sub-section).

**Step 9 doctrine v1 validation**: ✅ STRONG with empirical bonus. **Dual-administer cold-context test is ADDITIVE, not redundant** — Manager self-test surfaced 3 friction points; Krishna's external test surfaced 2 ADDITIONAL beyond mine. Net 5 cold-context observations. Empirical basis for promoting `light_review_required = true` to a hard requirement after Run 5+6 evidence.

**5 v1.1 doctrine candidates surfaced** (full codification in synthesis doc §5):
1. Heartbeat-daemon kickoff codification (Tiberius)
2. 4-tier clarification doctrine T1/T2/T3/T4 (Tiberius)
3. Heartbeat-tick-vs-peer-DM injection-density mitigation — **new failure-mode #6: signal-density-obscures-needle** (Tiberius + María phantom-detection catch)
4. Author-side grep-sweep checklist (Krishna)
5. Multi-surface footer-ratification close protocol with non-adjacent surfaces + synthesis-doc 7th-canonical-surface refinement (Rio + Mr Radio + Krishna refinement)
6. PLACEHOLDER — Explicit closure-context markers (filed for Run 5 evidence-gathering)

**Cascade-learning-loop forward-asymmetry empirical anchor**: Stage 1→2→3 wall-clock monotonically decreasing (38→33→21 min effective). Worth charting across Runs 1-4 for §10.18.

**Tiffany-rename-pass empirical refinement** (Mr Radio's catch): user-initiated rename operations CAN revert non-adjacent edit regions in one pass. Author-side grep-sweep checklist must enumerate ALL canonical surfaces independently — "the area I just touched" assumption is unsafe.

**Files**:
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/15-phase7a-telemetry-design.md` (cascade-ratified, ~470 LOC)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/16-phase7a-cascade-synthesis.md` (NEW, ~360 LOC, implementer-handoff doc)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/14-phase7a-telemetry-pre-cascade-recon.md` (Stage 0 background, untouched in cascade)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/13-phase7-slicing-manifest.md` (Step 0 inputs, untouched in cascade)

**Standing playbook**: commit-only no-push per [[never-auto-commit-push]]. All work uncommitted in working tree awaiting Rick's morning go-ahead.

**Manager-side phantom-lag observed**: 13-min lag at 02:33-02:46 UTC due to cascade-scheduler heartbeat ticks 11-14 obscuring Krishna's Stage 2 peer-DM. María's observer probe at 02:43:47 cleared. Mitigated for second half of run via proactive `commons_read` every N ticks. v1.1 doctrine candidate #3.

---

### 2026.05.20 - Session 32a6e563 (Mr. Radio 🦉) | Phase 7 slicing manifest + Phase 7a pre-cascade recon + Stage 0 design doc

#### Checkpoint 2 | 2026.05.20 02:10 | Phase 7a pre-cascade recon + Stage 0 design doc + manifest amendments — cascade Run 4 inputs ready

Continued Phase 7 planning track in parallel with Roscoe 🤠's Phase 6c implementation (Rick clarified parallel-track at ~01:40 UTC). Per Tiberius 🌑's direction across DMs `9d91b3a5` → `9e011230`:

**Option 1 — 7a Telemetry pre-cascade recon doc** (DM `9d91b3a5` greenlight): authored `14-phase7a-telemetry-pre-cascade-recon.md` (~280 LOC). Empirical anchor #2 for Step 0 doctrine (anchor #1 was the slicing manifest's §Pre-cascade recon framework, ratified 01:20 UTC). Per-item shape Question → Finding → Source → Decision per Tiberius's spec. Resolved 6 recon items:
- R-7a-1 OTel packages: `@opentelemetry/api` + `sdk-trace-web` + `exporter-trace-otlp-http` (skip `auto-instrumentations-web`; defer `sdk-metrics` to Q-T4 reviewer call)
- R-7a-2 Long Tasks: Chrome ✅, FF ✅ at floor, Safari ❌ — feature-detect at boot
- R-7a-3 Telemetry sink: env-driven INI key `multiplexer otel collector endpoint`; default empty (no-op); collector deployment OUT OF SCOPE
- R-7a-4 ReportingObserver: Chrome ✅, FF + Safari ❌ — feature-detect; Chrome-only signal at zero cost elsewhere
- R-7a-5 User Timing Level 3: unconditionally; meets Phase 1 floor (Chrome 114+ / FF 125+ / Safari 17+ per Phase 6c design doc line 88)
- R-7a-6 `observability/` directory stubs: Stage 0 design doc + code-execution phase owns creation; recon does NOT pre-stub

Tabulated 8 decisions for Stage 0 author + 8 open items deferred to cascade Stages 0-3. Tiberius's recon-doc verdict (DM `9e011230`): 🟢 GREENLIT. "High-quality. Question → Finding → Source → Decision shape is exactly what Step 0 doctrine should adopt as canonical recon-section template."

**Option 3 — Step 0 doctrine cross-ref to manifest footer** (DM `9d91b3a5` greenlight, concurrent): added §Doctrine cross-refs section to `13-phase7-slicing-manifest.md` footer linking PIP commit `bbb3e47` (Step 0 codification by Tiberius + María 🌸) + Step 9 (RATIFICATION-CLOSED 2026-05-19, validation-pending-Run-4). Phase 7a's first cascade = first live test of BOTH doctrines simultaneously.

**Option 2 — Stage 0 design doc** (initially HELD; ratified via Rick's cast spin-up): Tiberius reported (DM `9e011230`) that Rick spun up Rachel 🕊️ + Rio ⚡ + Krishna 🦚 explicitly to "assist Mr Radio in the plan creation and cascaded review process" — implicit ratification of author rotation. Authored `15-phase7a-telemetry-design.md` (~480 LOC) mirroring `10-phase6c-persona-focus-recorder-design.md` shape:
- Single cluster T (Telemetry) with **Q-T1..Q-T7** PROPOSED stances:
  - Q-T1: 6 canonical User Timing anchors
  - Q-T2: `createLongTasksObserver()` factory with null-on-Safari
  - Q-T3: ReportingObserver for `['deprecation', 'intervention', 'crash']`
  - Q-T4: 3 OTel span types (page-load, key-action, Long Task events); sdk-metrics deferred
  - Q-T5: perf budgets — boot<1500ms, first-queue-render<200ms, longtask<5/min (TBD-at-code-write per AC10b)
  - Q-T6: head-based sampling via `TraceIdRatioBasedSampler`; second INI key `multiplexer otel sampling rate`
  - Q-T7: telemetry init BEFORE renderer mount; `[multiplexer] telemetry:initialized` handshake
- **14 ACs** with Convention 3 EXECUTOR tags, Convention 4 TBD markers (AC-7a-8b + AC-7a-10b), Convention 5 N/A note (no `:8000` rows in 7a), Persona 2.A point 9 conditional-executability on AC-7a-8b + AC-7a-10b
- **Step T1-T7** sequential execution sequence per `feedback_pip_plan_review_is_sequential`
- **5 NEW + 9 EDITED** files enumerated
- **4 OSQs** with PROPOSED stances
- **13-point Persona 2.A rubric self-audit** + 17 feedback memories audited; no violations at draft time

Tiberius's Stage 0 first-scan verdict (DM `97c56ec9`): "Quality looks comprehensive at first scan (480 LOC, 7 Q-decisions, 14 ACs, full self-audit)." HOLD Stage 1 dispatch pending Step 0 doctrine §5.3 light-review by María 🌸 (6-criterion rubric). Rick's "Tiberius appears to be pleased" + explicit commit go-ahead resolved the conditional approval gate from his prior directive.

**Manifest amendment housekeeping**: §Per-slice file naming table renumbered from 3-doc-per-slice → 4-doc-per-slice (added recon docs). 7a: 14/15/16/17. 7b: 18/19/20/21. 7c: 22/23/24/25. 7d: 26/27/28/29. Review findings 94-97 unchanged.

**Coordination state**:
- Stage 1 dispatch to Rachel 🕊️ pending María's light-review verdict (~15-20 min wall-clock)
- If María 🟢 → Stage 1 fires; if ⚠️ gaps → I do 1 author-revision turn (CAPPED, no Round-2)
- Cap 2/2 author-revision-turn-cap + 3 discussion-turn-cap per cascade rules
- Step 9 synthesis-and-handoff doctrine will kick in after cap reached
- Phase 6c implementation track (Roscoe 🤠) continues independently; my last empirical state remains Node C through Step C2

**Parallel-session safety**: Roscoe 🤠's Phase 6c Node C work in flight (10 modified + 5 new files under `src/fastapi_app/static/js/multiplexer/`); my manifest section in `.claude-session.md` continues to list those as "NEVER staged from this context."

**Files** (this commit):
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/14-phase7a-telemetry-pre-cascade-recon.md` (NEW)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/15-phase7a-telemetry-design.md` (NEW)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/13-phase7-slicing-manifest.md` (MOD — file-naming table renumber + §Doctrine cross-refs footer)
- `TODO.md` (status updates on Phase 7a workstream)
- `history.md` (this Checkpoint 2 entry)
- `.claude-session.md` (Checkpoint 2 section + Touched Files update)

**Commit**: 54a1e19

---

#### Checkpoint 1 | 2026.05.20 01:35 | Phase 7 slicing manifest authored + ratified — sequencing Option A, pre-cascade recon ON, both op-phases decoupled

Coordinated with Tiberius 🌑 (session `387b9201`) on Phase 7 plan slicing for the multiplexer migration. Authored `13-phase7-slicing-manifest.md` (~280 lines) mirroring the Phase 6 slicing manifest shape + density. Phase 7 = Hardening (production readiness); roadmap §3 carves it into 4 sub-areas, all now sliced.

**Slice boundaries**:
- 7a Telemetry — User Timing + Long Tasks + ReportingObserver + OTel browser SDK
- 7b CSP — Content Security Policy report-only → enforce; new `/api/csp-report` endpoint scoped to `/app/multiplexer`
- 7c Trusted Types — `multiplexer/shared/trustedTypes.ts` policy + `require-trusted-types-for 'script'` CSP directive (HARD dep on 7b)
- 7d Accessibility — WCAG 2.1 AA + ARIA + keyboard nav + screen-reader pass + `prefers-reduced-motion` for Phase 6c animations

**Tiberius's review** (commons DM `93d42689`): 🟢 GREENLIT. "Draft is excellent." Sanity-check answers: slice boundaries match his mental model; no 5th sub-area missing; sizing right. Five strong-points called out; three minor observations (one folded into §Recommended order Per-slice point 2: 7a→7b sequencing means CSP report-only catches if OTel CDN needs allow-listing passively before enforce).

**Rick's ratifications** (cosa-voice blocking tools, sequential per Tiberius's recommended ordering):
1. Sequencing: **Option A** — 7a → 7b → 7c → 7d (recommended; telemetry-first per "observability before launch")
2. Pre-cascade recon: **ON** — 4-8h author-side homework before any design-doc cascade fires
3. 7b iterative-tightening: **DECOUPLED** as operational close-out phase (not second cascade)
4. 7d audit-driven cycle: **DECOUPLED** as operational close-out phase (not second cascade) — bundled with #3 in one `ask_multiple_choice` per Tiberius's suggestion

**Coordination state**:
- Phase 7 implementation gated on Phase 6c close (Roscoe 🤠's Node C in flight)
- First-slice author assignment TBD (Rick's call when 6c ships); Rachel 🕊️ likely continues as canonical author
- Mr. Radio returns to Persona 3 (Usability/Reuse Reviewer) for the cascade itself
- Step 0 doctrine cross-ref pending Tiberius + María 🌸's codification commit on PIP side

**Doctrine note from Tiberius**: my manifest's §Pre-cascade recon section is empirical validation that Step 0 cascade-prep is a real workflow phase — work today shaping doctrine for future cold-cast authors.

**Parallel-session safety**: Roscoe 🤠's Phase 6c Node C work is in flight in the working tree (10 modified + 5 new files under `src/fastapi_app/static/js/multiplexer/`); my manifest section in `.claude-session.md` explicitly lists those as "NEVER staged from this context" per `feedback_verify_staging_before_commit` and `feedback_lupin_only_never_cosa`. Only my one new file + the four tracking files commit.

**Files** (this session, this commit):
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/13-phase7-slicing-manifest.md` (NEW — slicing manifest authored + ratified)
- `TODO.md` (NEW top entry — Phase 7 ratified + next-move handoff items)
- `history.md` (this entry)
- `.claude-session.md` (new session section appended + checkpoint tracking)

**Commit**: ee31ed0

---

### 2026.05.19 - Session b4623e3d (Roscoe 🤠) | Phase 6c implementation — Nodes D + B + A + C fully shipped

#### Checkpoint 2 | 2026.05.20 02:10 | Phase 6c COMPLETE — Node C closure + structural bug-fix; 11/11 visual regression GREEN

**Phase 6c implementation is done.** Node C fully shipped (recordingManager port + SenderCardRecorderRenderer + sender-card-recorder.css + boot wiring + 29 unit tests + smoke + Section C visual file + :8000 baseline + regression). All four nodes' visual regressions now pass.

**Final tier roll-up** (D + B + A + C):

| Tier | Result |
|---|---|
| Unit cases (Phase 6c new) | 122 PASS (D 37 + B 31 + A 25 + C 29) |
| Multiplexer unit sweep | all PASS (~670 tests) |
| c8 coverage | 99.98% lines / 99.68% branches / 100% functions; tail gaps c8-ignored with same-line "smoke-tier" rationale |
| Phase 6c smoke @ :7999 | 23/23 PASS in ~24s |
| Visual baselines @ :8000 | 4 captures, all clean (`auto_fix_on_failure: False`) |
| **Visual regression @ :8000** | **11/11 snapshots match** — D 3/3, B 3/3, A 3/3, C 2/2 |

**Bug found + fixed mid-regression**: `SenderCardRecorderRenderer.paintAllVoiceInputs` only ran once at mount when zero `.cc-voice-input` footers existed yet. Late-arriving sender cards (the only kind in practice — they come from `store_senders_changed` emissions) never got Record buttons painted. First regression run reported "1 of 2 C-snapshots failed" → investigation revealed `wait_for_selector` for `.record-button` was TIMING OUT, not pixel-diffing. Fix: added a `bus.on("store_senders_changed", () => paintAllVoiceInputs())` subscription + matching unsubscriber in unmount(). Local Playwright probe confirmed `.record-button` appears within 3s of notification injection after the fix.

**Re-baseline rationale**: every sender card snapshot's `.cc-voice-input` footer now shows the Record button (whereas pre-fix snapshots had empty footers). Re-baselined all 4 nodes against the fixed bundle. Second 8-job batch confirmed all 4 nodes regression-green.

**Note on commit timing**: parallel-session interaction with Mr. Radio 🦉's Phase 7 planning track on history.md caused the initial commit (`ea3412b`) to land WITHOUT this entry. This Checkpoint 2 paragraph + commit `[pending]` amend brings the history back in sync.

**Outstanding before merge**: per Rick tonight — this checkpoint commit, no backup, no push. Wind-down for the night.

**Commit**: 83c8863 (amended from ea3412b)

---

#### Checkpoint 1 | 2026.05.19 23:30 | Phase 6c Nodes D + B + A shipped end-to-end; Node C partial through Step C2

Implementer-pass on Tiberius's Phase 6c execution plan (`src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/12-phase6c-execution-plan.md`, 749 LOC). Three of the four cascade nodes (D, B, A) are fully shipped end-to-end across the full test pyramid; Node C's chip-port runway (footer mount + AudioRecorder TS port) is landed and ready for Step C3 (recordingManager) to follow.

**Highlights**:
- **93 new Phase 6c unit cases** across 8 new test files (D 37 + B 31 + A 25). All multiplexer unit tests still pass.
- **c8 100% gate GREEN** on every multiplexer-wide pass: 8450 statements / 1787 branches / 642 functions / 8450 lines. Same-line `c8 ignore` comments cite specific defensive paths (polyfill fallbacks, FileReader error path, MediaRecorder error path under happy-dom) per the project's 100% mandate exception clause.
- **23/23 Phase 6c smoke tests pass on `:7999`** in ~24s end-to-end (5 D + AC-D9 canary + AC-D11 boot handshake + AC-D12 perf gate + 8 B + AC-B15 grep-gate + 6 A).
- **3 visual regression files** authored (Section D 3 snapshots, Section B 3 snapshots, Section A 3 snapshots).
- **3 `:8000` baseline submissions** queued via `POST /api/test-suite/submit` with `auto_fix_on_failure: False` per `feedback_baseline_capture_disable_tfe`: D `ts-0acbd8ef`, B `ts-db9d94ab`, A `ts-9fca0827`.
- **AC-B15 hard-verification grep-gate** holds across the whole session: D-CSS (`conversation-mode-pin.css`) has zero `@keyframes focus-flash` declarations; B-CSS (`focus-tray.css`) owns the SSOT keyframe. Smoke includes a runtime regression check.
- **Cross-renderer DOM-wipe bug found + fixed during Node B smoke** — NotificationsListRenderer's `replaceWith` re-render wiped `data-focus-hidden` on every store_senders_changed; FocusTrayRenderer now tracks `lastPinnedId` and re-stamps the attribute on every reconcile while focusModeActive=true (works because FocusTrayRenderer subscribes LAST in boot order, firing after the upstream wipe). Flagged to Tiberius as empirical anchor for the Step 9 "cross-renderer DOM-interaction matrix" doctrine candidate now being co-authored with María 🌸.

**Synthesis-doc gaps surfaced + resolved during pre-flight**:
- **Recon-D2 mic_monopoly wire-field**: server has no such field, no emitter. Escalated to Rick via Tiberius's `ask_multiple_choice`. Path δ defer ratified — mic-monopoly indicator becomes a Phase 6c follow-on (TODO entry filed by Tiberius in commit `3c870fb`). AC-D3 drops to 8 cases, AC-D10 drops to 5; AC-D4 unchanged.
- **Recon-D2-bis conversation_mode_changed type rename**: server emits `speakerphone_changed` with `payload.on`; smoke tests + plan reference `conversation_mode_changed` with `payload.active`. Path III bridge ratified by Tiberius unilaterally (wire-compat decision, not scope decision) — SenderStore.handleConversationModeUpdate listens for both type strings and reads `payload.active ?? payload.on`. AC-D3 covers both type strings × both field names (14 cases shipped).
- **Recon-A5 slugify**: new helper at `render/templates/slugify.ts` — single source of truth shared by `senderCard.ts` (Step A1) + `personaModal.ts` (Step A2). Regex `[^a-zA-Z0-9_-]/g → -` for HTML id-safe slugs.

**Outstanding before merge** (next-session todos):
- Node C Steps C3-C7 (recordingManager port + SenderCardRecorderRenderer + sender-card-recorder.css + boot wiring with AuthManager order + ≥24 unit tests + smoke + visual + `:8000` baseline)
- AC-D14, AC-B14, AC-A13 regression runs on `:8000` — pending Rick slot-coordination (NOT standing permission for non-baseline runs); will batch as one slot-ask when Rick returns

**Coordination notes**:
- Tiberius 🌑 (session `387b9201`) shipped 3 handoff docs + mic-monopoly TODO in commit `3c870fb`; my implementation work is the runtime side of that bundle.
- María 🌸 + Tiberius are co-authoring "Step 9 synthesis-and-handoff doctrine" as a meta-process improvement; the cross-renderer DOM-wipe bug-find from Section B smoke is their empirical anchor for a "cross-renderer DOM-interaction matrix" Step 9 check.

**Files**: 31 (10 new source TS, 3 new CSS, 9 new test files, 7 modified source/HTML, 2 modified tests, 1 stylelintrc, history.md).
**Commit**: c7df5d5

---

### 2026.05.19 - Session 4e724860 (Tiberius 🌑) | websocket-events.md doc fix — `speakerphone_changed` documented + `conversation_mode_changed` deprecation noted

Closed a documentation gap surfaced during Roscoe 🤠's Phase 6c Node D pre-flight investigation. Rick asked "who listens for `conversation_mode_changed`, where does it originate, is it in the INI website-events list?" — answered with the cascade-design-gap context: the event was renamed to `speakerphone_changed` during the Speakerphone solo/chorus refactor (Phase 3 of `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/`, landed 2026-05-13), but `src/docs/websocket-events.md` was never updated.

**Three edits** (all targeted, no scope creep):
1. **Summary table** (L27): added `speakerphone_changed` row in the Notifications category, mirroring the `commons_activity` row shape (notification_queue_update wrapper).
2. **Per-event detail section** under Notifications (L252+): full entry covering rename history (2026-05-13 Speakerphone refactor Phase 3), payload shape (`{session_id, on, displaced?, displaced_by?}`), both client handlers (legacy `notifications.js::handleConversationModeChanged()` line 5552 + multiplexer `SenderStore.ts` STATE_UPDATE_TYPES Set), the Path III forward-compat bridge (accepts both wire names), INI subscription cross-ref (`lupin-app.ini:741`), server-side `valid_types` whitelist cross-ref (`notifications.py:359-364`).
3. **Deprecated Events section** (L466+): added a new "renamed during Speakerphone solo/chorus refactor" table mapping `conversation_mode_changed` → `speakerphone_changed` with the 2026-05-13 rename date. Notes that the deprecated name returns HTTP 400 if pushed.

**Empirical anchor**: Roscoe surfaced this gap during Node D pre-flight (DM `d2419eae`). The cascade design plan referenced the old name; the server only emits the new name. Path III bridge was ratified unilaterally by me (DM `eb826676`) — accept both names client-side as forward-compat. This doc edit captures that bridge contract for future readers.

**Files**:
- `src/docs/websocket-events.md` (MOD — 3 edits, ~30 LOC added net)
- `history.md` (this entry)

**Cross-refs**:
- Origin design: `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/16-phase7-multiplexer-ui-design.md` §"WebSocket `speakerphone_changed` handler"
- Phase 3 rename closure: `src/cosa/history/2026-04-25-to-05-13-history.md:89` (CoSA-side `valid_types` rename log)
- Forward-compat bridge ratification: today's DM `eb826676` to Roscoe + the Phase 6c synthesis doc `11-phase6c-cascade-synthesis.md` §3.D
- Documentation TOUCHPOINTS in CLAUDE.md: this doc is listed under `routers/websocket.py` + `lupin-app.ini websocket available events` row — both touchpoints honored this edit.

---

### 2026.05.19 - Session 4e724860 (Tiberius 🌑) | Phase 6c cascade synthesis + execution plan + design-doc amendments + mic-monopoly follow-on TODO

Three-artifact handoff bundle from Run 3 cascade — translating the 43 ratified findings across 4 sections (A/B/C/D) into an implementation contract Roscoe 🤠 can ship from cold. The synthesis doc (476 LOC) is the canonical why-anchor with per-section ratified AC tables, cross-section dependency map, and §10.14 doctrine candidates brief index. The execution plan (749 LOC) is DAG-first per Roscoe's framing preference with per-node deliverables, function signatures, step ordering, test pyramid, and done-defined. The amended parent design doc flips status to CASCADE-RATIFIED with per-cluster markers and inline cascade-closure narratives for Q-C2 (port-verbatim user escalation) and Q-D1 (manager-unilateral by-concurrence). Mic-monopoly indicator deferred via Path δ ratification (Rick) — filed as Phase 6c follow-on in TODO.md with the system-wide-semantic question to resolve before designing.

**Files**:
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/11-phase6c-cascade-synthesis.md` (NEW, 476 lines)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/12-phase6c-execution-plan.md` (NEW, 749 lines)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/10-phase6c-persona-focus-recorder-design.md` (MOD, cascade-amended status + per-cluster markers + Q-C2/Q-D1 cascade-closure notes)
- `TODO.md` (MOD, mic-monopoly follow-on entry filed under Path δ ratification)
- `history.md` (entry above)

**Commit**: `3c870fb` (2026-05-19, Rick ratified via María's `ask_yes_no` 22:21 UTC).

---

### 2026.05.19 - Session 4e724860 (Tiberius 🌑) | Voice persona pool expansion — +2 personas, Sam→pool / Arnold→overflow swap, generalized overflow loader

Pool expansion driven by Rick's voice directive following the 6-persona-experiment validation in Run 3 cascade. Pool grew from 6 to 8 personas; the overflow slot rotated from Sam to Arnold via a config-only mechanism enabled by a small loader generalization. Color iterations + gender + profile corrections per Rick's voice walkthrough at ElevenLabs.

**Pool composition (final)** — `maria, mr radio, Rachel, Tiberius, Rio, Roscoe, Krishna, sam` (8 personas).

**Two new personas added**:
- **Roscoe** 🤠 — ElevenLabs voice `DXX4Q5Bh1vqK8CciYVPf`, color `#FFD600` (vibrant yellow — Arnold's old hue, now free since Arnold moved to overflow), profile "Upbeat professional female" (gender corrected from initial "male" placeholder per Rick's mid-edit update)
- **Krishna** 🦚 — ElevenLabs voice `ogSj7jM4rppgY9TgZMqW`, color `#1DE9B6` (Material Teal A400, vibrant aquamarine — documented green-rule exception per Rick's explicit override authority), profile "Reassuring warm male"

**Sam ↔ Arnold role swap**: Sam promoted from the reserved overflow slot into the regular pool; Arnold demoted from pool into the overflow slot. Mechanically required a small loader generalization in `voice_persona_helpers.py:load_overflow_persona_from_config` — previously hardcoded the literal "sam", now reads a new `cc session voice persona overflow name` INI key (default "sam" for backward compat) and looks up that persona's existing pool-style INI keys. Backward-compat branch: when overflow_name resolves to "sam" AND no explicit `cc session voice persona sam voice id` key is present, falls back to sourcing voice_id from `elevenlabs tts default voice id` (the pre-2026-05-19 legacy non-explicit path). All 5 existing `TestLoadOverflowPersonaFromConfig` tests still pass byte-clean via the backward-compat branch.

**Sam's transition**: added explicit `cc session voice persona sam voice id = G7ILShrCNLfmS0A37SXS` (same value as `elevenlabs tts default voice id` — now explicit so the regular pool loader can find him uniformly). Color changed from `#00BCD4` (cyan, formerly grandfathered under the `.persona-badge.overflow` styling exception) to `#5E35B1` (Material Deep Purple 600, green-rule compliant). Profile iterated through "System default voice (overflow)" → "Crisp neutral male" → "British male" (final, per Rick's verification of the actual ElevenLabs voice characteristics).

**Rachel lightened to lilac**: `#7B1FA2` (Material Purple 700) → `#CE93D8` (Material Purple 200, lilac) per Rick's directive once Sam's new deep purple made the prior Rachel-Sam pairing too visually close. Lilac preserves Rachel's purple-family identity while widening visual separation from Sam.

**Test verification**: `test_voice_persona_helpers.py` (52 tests) + `test_voice_persona_request.py` (49 tests) = **101 tests green in 2.5s**, zero regressions across all loader generalization + INI changes.

**Voice persona reference page** at `/static/html/test/voice-persona-reference.html` auto-populates from `GET /api/cosa-voice/voice-persona/pool` — no HTML edit needed; after `/api/init` reload, the page renders 8 tiles including Sam in his new deep purple.

**Files modified** (parent Lupin only — CoSA submodule untouched git-wise per `feedback_lupin_only_never_cosa`):
- `src/conf/lupin-app.ini` — pool list updated to 8 personas; Roscoe + Krishna full blocks added; Sam block rewritten (voice id explicit, color changed, profile updated, comment rewritten); new `cc session voice persona overflow name = arnold` key; comment block above Arnold's old position explaining the role change
- `src/conf/lupin-app-splainer.ini` — pool splainer rewritten for 8-persona reality; Roscoe + Krishna entries added; Sam splainer block rewritten (new voice id entry, color rationale updated, profile iteration history); new `overflow name` splainer entry with full backward-compat documentation; Rachel color splainer updated for lilac transition

**CoSA submodule changes on disk (not in parent diff)**:
- `src/cosa/rest/voice_persona_helpers.py` — `load_overflow_persona_from_config` generalized (~50 LoC); reads new INI key with `sam` default; backward-compat fallback to `elevenlabs tts default voice id` when overflow_name="sam" + no explicit voice id; updated Design-by-Contract docstring

**Cross-refs**: original Sam-overflow design at `src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md` (now superseded by the generalized loader); pool architecture at `src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md`; voice persona expansion authorized by Rick's voice directive 2026-05-19 mid-afternoon EDT.

---

### 2026.05.19 - Session 4e724860 (Tiberius 🌑) | Per-repo preferred-persona env-var allocator — Lupin-side implementation + 7 unit tests

End-to-end implementation of Rachel's planning-is-prompting design doc `2026.05.19-cosa-voice-preferred-persona-env-var.md` on the Lupin side. Reads `COSA_VOICE_PREFERRED_PERSONA__<PROJECT_UPPER>` at SessionStart hook time, threads through to the cosa-voice `/allocate` router endpoint with graceful-fallback semantics, fires a `voice_persona_conflict` notification on miss. Narrative goal: each repo gets a stable canonical voice persona across days/sessions/`/clear`s — Rick's two target defaults are `__PLAN=María` and `__LUPIN=Tiberius`.

**Coordination shape**: cross-session pair-collab with Rachel 🕊️ (planning-is-prompting session `b310866d`) via commons DMs. Rachel owns the PIP-side design doc + workflow doc updates (`workflow/session-start.md` Preliminary -1 subsection, `workflow/INSTALLATION-GUIDE.md` one-liner). I own the Lupin/cosa-voice-side allocator + tests. María 🌸 joined the chorus post-Rachel-restart per Rick's narrative-restoration ritual.

**Rick's four §8 ratifications** (via blocking `ask_multiple_choice` + open-ended `converse`): (1) **notify delivery — option α inline** after bridge creation (vs β deferred to `get_session_info` poll); (2) **conflict notify suppression — fire every time** (vs dedupe per holding-session tuple); (3) **global fallback chain — out-of-MVP** per draft; (4) **`/clear` persistence — Path A preserve persona** across `/clear` (env var applies at FIRST allocation only; full session restart is the right ritual to change preference; narrative continuity wins).

**Architecture (minimum blast radius)**: new pure helper `pick_preferred_persona_from_env(project) -> Optional[str]` in `src/cosa/rest/voice_persona_helpers.py` with project-name normalization (lowercase→UPPER, hyphens→underscores, empty/None tolerated). New `preferred_persona_name` query param on `POST /api/cosa-voice/voice-persona/{sid}/allocate` with soft-preference semantics — tries the named persona via existing `allocate_requested_persona_for_session`; on `not_in_pool` or `occupied` allocates random via `allocate_persona_for_session` and pushes a `voice_persona_conflict` notification carrying the conflict kind + requested name + available pool + (for `occupied`) holding session id. Mutually exclusive with the strict slash-command `requested_persona_name` path (422 if both supplied). Outer fast-path preserved so `preferred_persona_name` does NOT override an existing allocation — that's the Path A `/clear`-preserves contract. Response payload extended with `preference_conflict: Optional[dict]` so callers can observe the fallback. Hook side (`src/lupin_cli/claude_code/hooks/register_session.py`) reads env var via the new helper and threads through `_allocate_voice_persona_via_http` as a new query-string param. Zero changes to `allocate_persona_for_session` or `pick_unallocated_persona` — the existing primitives compose cleanly via the orchestration in the router branch.

**Test pyramid**: 7 new unit tests appended to the pre-existing untracked `src/tests/unit/test_voice_persona_request.py` (which already held Arnold's 42 slash-command swap tests). 4 helper-only tests in `TestPickPreferredPersonaFromEnv` (env unset → None; project="cosa-voice" → reads `__COSA_VOICE` via hyphen-to-underscore normalization; project case-insensitive across `plan/PLAN/Plan` → reads `__PLAN`; empty/None/whitespace project → None silently). 3 router tests in `TestPreferredPersonaNameQueryParam` via FastAPI TestClient + dependency overrides covering happy-path (preferred persona available), occupied (held by another live session → fallback + conflict notify with kind=occupied + holding-session-id), invalid-name (`Frobozz` → fallback + conflict notify with kind=not_in_pool). All 49 tests green in 2.4s (Arnold's 42 pre-existing + my 7 new). Zero regressions on the 52-test `test_voice_persona_helpers.py` suite (existing helper coverage preserved). Full import chain verified — `register_session.py` imports `pick_preferred_persona_from_env` without circulars.

**Narrative-restoration arc**: Rick's broadcasts `9c604340` + `a0141fc9` defined the cross-session checkpoint pattern: previous-persona work stays UNCOMMITTED so the git log doesn't pre-model the canonical persona assignment; post-env-var-restart Tiberius (Lupin) and María (PIP) commit their respective trees under correct attribution. Today's narrative twist — Rick did NOT restart my Tiberius session (kept continuity), but DID restart Rachel's session and restored María. So I (continuous Tiberius) take ownership of all uncommitted Lupin work — Arnold's 42 pre-existing test cases + my new helper + router branch + hook integration + 7 new tests. María (restored persona) handles the PIP-side carry-forward independently.

**Surfaced a new bug during the morning's coordination**: cosa-voice persona resolver does not match display-name diacritics. `commons_send_to(recipient="María", …)` returned `recipient_resolution_error` with `resolution_chain_attempted: [exact, case_insensitive, punct_tolerant]`; lowercase `"maria"` (pool key form) succeeded. The candidate_alternatives payload correctly listed the maria session, so the resolver SAW the right session but did NOT match through the diacritic. Filing follow-up bug entry on bug-fix-queue post-checkpoint — proposed fix is a Unicode normalization pass (NFKD + diacritic strip) in the persona resolver, or a display-name-aware lookup augmentation.

**Files (parent Lupin only — CoSA submodule pieces are on disk but per `feedback_lupin_only_never_cosa` not managed from this context)**:
- `src/lupin_cli/claude_code/hooks/register_session.py` (MOD — import `pick_preferred_persona_from_env`; `_allocate_voice_persona_via_http` accepts + threads `preferred_persona_name`; hook callsite reads env var)
- `src/tests/unit/test_voice_persona_request.py` (was untracked Arnold-authored 42 tests; appended import + `TestPickPreferredPersonaFromEnv` 4 cases + `TestPreferredPersonaNameQueryParam` 3 cases — net 7 new tests, 49 total)
- `history.md` (this entry)

**CoSA-submodule changes on disk (not committed from this context)**:
- `src/cosa/rest/voice_persona_helpers.py` — new `os` import + `pick_preferred_persona_from_env` function + docstring
- `src/cosa/rest/routers/voice_persona.py` — `preferred_persona_name` query param + mutual-exclusion 422 + soft-preference branch in `else` path + `voice_persona_conflict` notification push + `preference_conflict` in response payload

**Cross-refs**: design doc `planning-is-prompting/src/rnd/2026.05.19-cosa-voice-preferred-persona-env-var.md` (Rachel's authorship, the canonical specification including §4-§8 implementation/test/decision-points); commons DM topic `dm-tiberius` + `dm-maria` for the morning's coordination thread.

---

### 2026.05.19 - Session 4e724860 (Tiberius 🌑) | Phase 6C cascade Run 3 manager (HYBRID authoring-cascade on multiplexer implementation plan)

End-to-end manager of the inaugural HYBRID `/plan-authoring-cascaded` run, applied to Rachel's pre-existing Phase 6C design doc (`src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/10-phase6c-persona-focus-recorder-design.md`). 4 sections (A: Voice-Persona Modal, C: Sender-Card Audio Recorder, D: Conversation-Mode UI Pin, B: Focus Tray + Toggle). Same 5-persona cast as Run 2 with Rachel 🕊️ swapped to Author (from Usability), Mr Radio 🦉 swapped to Usability/Reuse (from Author), Arnold 🪨 + Rio ⚡ in canonical Viability + Ownership roles, María 🌸 doctrine consultant, me Manager. Heartbeat daemon (PID 570626) ran 48 ticks on 180s cadence; second daemon (PID 615764) launched mid-run for María on Rick's authorization.

**Run 3 cascade results**: all 4 sections fully closed at cap 2/2; 43 findings total (10 Persona-3 + 22 Persona-4 + 4 Persona-5 across 11 reviewer-instances); 39/43 verbatim-accept (91%) + 4 documented-not-revised (cap-preserved cosmetic); 0 votes; 1 user escalation (Section C F2 foundational `audio/webm;codecs=opus` MIME incompatibility, ratified-yes by Rick via `ask_yes_no` 02:48 UTC after his voice-pushback redirect to port the working `AudioRecorder` + `recordingManager` singleton verbatim); 1 Manager-unilateral ratification (Section D Q-D1 Path A by-concurrence — new closure category); 1 counter-proposal (Rachel base64 option-a over my option-b on Section C OSQ-C-3, accepted); 1 reviewer reassignment (Mr Radio → Arnold for Section B Stage 1 due to Anthropic-side rate-limit blocking 78+ min); 1 hard-verification-gate introduced (Section B AC-B15 grep-gate enforcing B-CSS-as-SSOT on `@keyframes focus-flash` — superseded Round-1 post-cascade-fold disposition). Wall-clock 108 min from launch 02:28 UTC to cascade-complete 04:16 UTC. End-of-pipeline §8 summary posted to `pipeline-summary-20260519` commons topic.

**Per-section wall-clock + findings**: A 44 min / 11 (10/11 verbatim); C 57 min / 14 (13/14 verbatim, 1 user escalation); D 62 min / 9 (8/9 verbatim); B 72 min / 9 (8/9 verbatim, 1 reviewer reassignment + 1 hard-verification-gate). All sections hit cap 2/2 — full revision-discipline coverage.

**Cascade-learning-loop validated empirically (finding compression dimension)**: Section finding-counts across Run-order A→C→D→B = 6, 8, 4, 4 at Stage 2. F-Arnold-C3 reproduced F-Arnold-1 in Section C (asymmetric forward-loop: C's Round-1 pre-dated A's lesson). Sections D + B benefited from Rachel's autonomous doctrine carry-forwards (4 proactive applications in Section B Stage 0: directory-wide c8 glob, var-color form, stale-citation caveat, AC2e safe-write). Section B shipped Stage 0 with **zero conditional-executability markers** — only section in Run 3 to achieve this. Rio explicitly cited as "strongest cascade-learning-loop validation to date."

**Mr Radio rate-limit incident** (5th distinct failure mode catalogued for §10.14 — distinct from dormancy / read-side truncation / turn-based limitation / write-side truncation): hit Anthropic `API Error: Server is temporarily limiting requests (not your usage limit)` at ~03:06 UTC, immediately post Section B Stage 1 dispatch. María's diagnostic via Rick's voice channel at 03:17 UTC ("park-and-wait, 5-min cadence, 15-min threshold") prevented misdiagnosis as phantom dormancy. Threshold escalation at 03:32 UTC via `ask_multiple_choice` → timed-out `expired_no_default` (Path B skip-restart: Item #1 fix not loaded in pre-existing MCP subprocesses) → re-fired as `ask_yes_no` per Run-2 workaround → Rick ratified reassignment to Arnold (14-min user-attention block, longest single Run-3 event). Arnold's Persona 3 reassignment caught 4 substantive findings on Section B Stage 1; his canonical Persona 4 at Stage 2 then caught 3 of his own Stage-1 closures' fitness gaps. Rio's fresh-eyes Stage 3 concurred + caught one final cosmetic. **Cascade closed cleanly WITHOUT Mr Radio recovery** — structural answer to rate-limit failure mode is reassignment, not partial-close.

**12 doctrine candidates filed for María's manager-seat §10.14 post-Run-3 redline**: (1) AC-table-doctrine-lag pattern — 3 confirmed instances (F-Arnold-C3 + F-Arnold-D4 + F-Arnold-B-Stage2-3) → formal Persona 2.A point-14 codification; (2) hard-verification-gate vs post-cascade-fold pattern — NEW closure category; (3) visible-text safety on CSS var fallbacks — `currentColor` over `transparent`; (4) symmetric-application discipline (writer + consumer); (5) reviewer-reassignment-due-to-rate-limit closure category; (6) Manager `blocked_waiting_on_user` coordination signal (María's catch — observers can disambiguate scenarios 1 vs 2 from disk-read alone); (7) Q-D1 `manager_unilateral_ratify_by_concurrence` formal closure category; (8) cascade-learning-loop sub-patterns (forward-only-asymmetry + symmetric-application + context-aware-application); (9) rate-limit failure mode catalog entry; (10) Stage-3 cosmetic-cluster as systematic pattern-family (F-Rio-1 + F-Rio-C1 + F-Rio-D1 + F-Rio-B1 = 4 distinct variants); (11) ask_multiple_choice Path-B skip-restart cost validated empirically; (12) 18-min user-attention-block tightening directive.

**Post-cascade fold bundle (final shape, shrunk per AC-B15 hard-gate adoption)**: (1) Q-C2 design-doc `10-phase6c.md` §Cluster C amendment recording Rick's port-verbatim ratification; (2-5) 4 F-Rio-* cosmetic folds (Section A AC-A3/A4 cross-reference; Section C AC-C3 orphan strike; Section D Step D2 pin-move wording; Section B AC-B15 grep-gate wording precision). B-keyframes-removal from D-CSS NO LONGER in bundle — now hard-gated in-cascade via AC-B15 (mechanical grep verification at code-write).

**Rick's midstream interventions**: (a) F2 voice-pushback redirect ("propose a variation of something that already works") that collapsed Section C's Q-C2 from MIME-negotiation-design to port-verbatim-of-AudioRecorder — saved the cascade from shipping a broken endpoint assumption; (b) base64 enhancement consideration raised post-F2 ratification ("not a suggestion, just worth considering") that surfaced OSQ-C-3 deferral as a stand-alone perf R&D candidate; (c) María daemon launch authorization mid-run (addressing turn-based-CC limitation as applying to ALL cascade CC roles); (d) reviewer reassignment ratification at threshold (option B over A1/C); (e) Sam (CoSA) added to closeout chain at 04:17 UTC, resolving Lupin/CoSA git separation for tonight's commit batch.

**Operational notes**: (a) `/plan-authoring-cascaded` workflow was authored by María during this same evening session, parallel with the Run-3 cascade itself — María's PIP-side authoring landed concurrent with cascade kickoff; (b) cascade-as-author HYBRID mode (design doc exists, implementation plan authored within cascade) was the inaugural use of this pattern; (c) all participating sessions retained Run-2 contexts (Path B: skip MCP subprocess restart) — `ask_multiple_choice` default-param fix from V2 Item #1 was therefore NOT loaded, validated empirically by `expired_no_default` timeout on the threshold escalation; (d) Predicted user-attention budget per María's §10.14 estimate was ~7-9 escalations; actual was 1 (F2 user-ratification) + 1 (rate-limit reassignment) + several status walkthroughs — well below ceiling.

**Files (parent Lupin only — CoSA via Sam, PIP via María per coordination chain)**:
- `history.md` (this entry)

(Cascade itself produced no Lupin code changes — all 4 section commons-topic files + dm-* + pipeline-summary live under `io/commons/` which is gitignored. The cascade's output is the ratified implementation plan, which Rachel will materialize into design-doc amendments + code-write in a subsequent session.)

**Closeout coordination chain** (per Rick's 04:09 UTC directive via María): (1) cascade-complete signal fired ✅; (2) Lupin commit-only no push (this commit); (3) Tiberius pings Sam → Sam runs CoSA end-of-session ritual; (4) Sam commits CoSA (independent of Tiberius — addresses my `cosa-edit-vs-manage-git` feedback restriction); (5) María commits PIP independently with matching stretched-day boundary `2026-05-18T00:00 → 2026-05-19T05:00` on LoC Delta.

---

### 2026.05.19 - Session 4e724860 (Tiberius 🌑) | Recent-activity panel UX polish (toggle move + fixed-width header columns)

Quick CSS+JS tweaks to the broadcast-panel Recent Activity section while waiting on María's `/plan-authoring-cascaded` doc-spec authoring. Two user-driven refinements, both verified visually by Rick at :7999 dev:

**Show-more toggle moved into the row header** — previously the `commons-activity-entry-body-toggle` button rendered inline below the body content, which was idiosyncratic vs other UI toggles in the app shell. Rick wanted it inline with the row header near the time. Approach: extended the entry grid from 5 to 6 columns (`icon name chip body toggle time`), moved `body.appendChild( toggle )` to `row.appendChild( toggle )` after `row.appendChild( body )`, and updated the toggle's CSS from `display: inline-block + margin-top: 2px` to `grid-area: toggle + align-self: start + white-space: nowrap`. Persona color preserved via the existing `--persona-color` CSS variable. Hidden-on-no-overflow + click-toggles-expanded behavior unchanged; existing E2E tests at `src/tests/e2e_ui/test_commons_activity_toggle.py` survive because their class-based selectors still find the toggle regardless of parent.

**Name + chip columns fixed-width** — previously `auto`-sized so each row's body started at a different x-position depending on persona-name + chip-content lengths. Rick wanted a consistent left-edge for the body. Two iterations to land the visual: first pass at 100px/110px (too much whitespace per Rick); final at 70px/75px (~31% reduction, "looks great" per Rick). Chip right-aligned within its column via `justify-self: end`. Both name + chip get `overflow: hidden + text-overflow: ellipsis` for graceful truncation on edge cases (e.g. `cascade-scheduler` 17-char name or `cascaded-prototype-input-plan` 29-char topic name). Added `title` attribute on both elements in `_renderCommonsEntry` for full-text on hover when truncated.

**Files**:
- `src/fastapi_app/static/js/notifications.js` (MOD) — `_renderCommonsEntry`: appended toggle to row instead of body; added `name.title` + `chip.title` for hover full-text
- `src/fastapi_app/static/css/notifications.css` (MOD) — `.commons-activity-entry` grid expansion (5→6 columns) + name/chip width fix + chip right-alignment + ellipsis on overflow on both
- `history.md` (this entry)

**Test impact**: zero — E2E tests query toggle/name/chip by class; structure-agnostic queries survive the parent-element change.

---

### 2026.05.18 - Session 4e724860 (Tiberius 🌑) | Cascade Run 2 manager + V2 polish bundle (Items #1 + #3 Lupin-side)

End-to-end manager of Run 2 of the `/plan-review-cascaded` prototype on the toy email-verification fixture, then coordinator of the v2 polish-bundle implementation cycle that followed. Same 5-persona cast as Run 1 (María 🌸 doctrine consultant, Mr. Radio 🦉 Author, Rachel 🕊️ Usability/Reuse, Arnold 🪨 Viability/Gap, Rio ⚡ Ownership-Language Audit, me Manager).

**Run 2 cascade results**: all 4 stages cleared on both sections (Section A 19:53:20 UTC, Section B 20:03:30 UTC); 21 findings total (12 cosmetic / 8 inconsistency / 1 foundational); 5 single-round verbatim re-litigation rounds (100% lowest-friction close); 0 votes; 1 escalation to Rick (Section B Arnold F1 plan-decomposition gap, user-ratified `documented_for_telemetry`); 100% `severity_proposed` → manager-final match rate (21/21); 4 cross-section findings caught + closed consistently; wall-clock ~49 min (vs Run 1 ~55 min). Heartbeat daemon ran 21 ticks on 180s cadence, exited cleanly on `cascade_complete` signal. End-of-pipeline §8 summary posted to `pipeline-summary-20260518` commons topic for archival.

**V2 polish bundle** (5 improvements identified during Run 2 §8 summary, ratified by Rick 2026-05-18T21:10 UTC via bundled manager-funnel ask):
- **Item #1** (Rio): `ask_multiple_choice` MCP tool gained `default: Optional[dict]` keyed by question header. On timeout returns `{"answers": default}` instead of error. Closes the AFK-graceful-escalation gap (Run 2 lost ~10 min to a timed-out `ask_multiple_choice` with no default — the cascade was unrecoverable until I re-fired as `ask_yes_no` which DOES support `default`). Backward-compatible (default=None preserves legacy error-path byte-identically). Pre-call validation rejects invalid defaults at call time, not at timeout.
- **Item #3** (Rachel): cascade-heartbeat daemon extended with per-section message-count budget tracker. Filename-glob section discovery (`cascaded-prototype-section-*.md`), boundary-marker `str.count()` on disk for cheap entry counting, idempotent warn-once-per-section via in-memory dict, DM-to-manager via `CommonsStore.post()` + Phase 3 push (matches `fire_heartbeat()` shape). New CLI args `--budget-threshold` (default 25) + `--section-glob`. Existing launch invocations work unchanged.
- **Items #2 + #4 + #5** (Arnold + Mr Radio in PIP — committed by María separately at SHA `6c8b7b1`): recommendation-as-spoken-headline doctrine for §7 escalation templates, Convention 3 × Convention 4 author Stage-0 self-check in Persona 2 rubric, cluster-bundled re-litigation as playbook default in §6.2 + §DM-Subset Heuristics.

**Coordination wins**: bundled manager-funnel ratification ask saved ~4 user-attention round-trips vs per-item ratification (3 interactions for 5 ratifications). Lesson 12 captured to PIP §10 memo (manager-funnel applies to both findings-up AND proposals-up; bundled > per-item). Meta-validation: my recommendation-led second ratification ask (informally applying Item #2's not-yet-codified doctrine) landed unconditional yes immediately — direct evidence the doctrine fix works even before its formal implementation. Arnold independently dogfooded the same spoken-headline contract during his own classifier-vs-funnel detour around 21:55-22:00 UTC.

**Critical-path Rachel hold/resume episode** (telemetry capture for §10 memo): Rachel correctly held Item #3 post Rick's broadcast `312d4397` (files-touched check-in request) but sent her status-ping to me via `commons_post` (blackboard-only, no push in Phase 1) — I never saw it. Voice-redirect from Rick caused a 2-line argparse revert (byte-clean undo, no real work lost). Diagnosed in one round-trip; re-greened Rachel using Rick's "straighten this out" authority. **Doctrine lesson logged**: status-pings to sleeping recipients MUST use `commons_send_to` or `in_reply_to` on an open question; plain `commons_post` is blackboard-only in Phase 1 and only delivers when the recipient next polls.

**Documentation + commit pattern with María**: mutual independent convergence on the per-repo split (Tiberius=Lupin code-side, María=PIP doctrine-side) at 22:38:07 vs 22:38:19 UTC — both arrived at the same answer from the same playbook within 12 seconds. Prep-don't-commit pattern initially planned (we prepare commit messages + history entries; user fires `git commit`); Rick's broadcast `69cffa07` ("you have a go to document and commit") replaced the consolidated ratification ask with pre-authorization. Worker sign-offs still gathered for intra-team attribution discipline. Commits fire per-repo independently; `git push` stays per-repo user-fire per CLAUDE.md `feedback_never_auto_commit_push.md`.

**Operational note** (also in commit body): Rio's Item #1 `default` param fix requires MCP subprocess restart to take effect in active CC sessions. Python imports cache the OLD code in long-running MCP processes — same pattern as the 2026-05-18 commons_store truncation-fix episode. For Run 3 of the cascade-review prototype, all participating sessions should have MCP subprocesses restarted post-merge so the timeout-default benefit is available to the Manager's escalation calls.

**Followup tracked (NOT in this commit, future session)**: `src/docs/notification-api.md` and related Lupin docs need an update to advertise the new `ask_multiple_choice` `default` param to internal callers per the CLAUDE.md DOCUMENTATION TOUCHPOINTS table mapping (MCP notification-tool surface changes → `src/docs/notification-api.md`). TODO seed for next documentation-refresh session.

**Files (parent Lupin only — CoSA + PIP untouched per nested-repo rules)**:
- `src/lupin_mcp/cosa_voice_mcp.py` (MOD — Rio's V2 Item #1: `default` param signature + validation helper + timeout branch + line-742 instructions block update)
- `src/tests/unit/test_cosa_voice_mcp_default.py` (NEW — Rio's 13 unit tests: 7 validation-helper + 6 integration scenarios; full MCP regression 42/42 green in 1.96s, zero regressions)
- `src/scripts/cascade_heartbeat_scheduler.py` (NEW — heartbeat daemon scaffold from earlier Run-2-prep + Rachel's V2 Item #3 budget-tracker extension; daemon ran 21 ticks of Run 2 cleanly before this commit)
- `src/scripts/start-cascade-heartbeat.sh` (NEW — executable wrapper)
- `src/tests/unit/test_cascade_budget_tracker.py` (NEW — Rachel's 5 unit scenarios: 3 required + 2 defensive bonus; 5/5 green in 0.05s)
- `history.md` (this entry)

**PIP repo touches** (separate repo, María's parallel commit at SHA `6c8b7b1`):
- `workflow/plan-review-cascaded.md` (MOD — Arnold's #2 + #5 + version-history bump)
- `workflow/plan-review-cascaded-personas.md` (MOD — Mr Radio's #4 + version-history bump)
- `src/rnd/2026.05.17-cascaded-plan-review-pipeline.md` (MOD — §10.13 Lesson 12 added)
- `history.md` (MOD — Session 92 continuation entry)

**Audit trail anchor**: commons topic `v2-improvements-complete-2026-05-18` holds all 5 V2 proposal entries + 4 completion entries + my Lupin commit-prep draft. Cross-repo trail discoverable from either repo's commit body via this topic name (no SHA cross-reference per agreement with María — async SHA exchange not worth the complexity).

**Run 3 readiness**: pending (a) MCP subprocess restart on all participating sessions to pick up Item #1; (b) Rick's Run-3 window selection. Heartbeat daemon will need a fresh launch (the Run 2 daemon exited cleanly on cascade-complete); doctrine doc updates from the parallel PIP commit are in-effect immediately on next session-start read (no restart needed for doctrine reads).

---

### 2026.05.18 - Session 4e724860 (Tiberius 🌑) | Cascade Run 1 manager + body-display truncation fix verification + heartbeat daemon for Run 2

End-to-end manager of the inaugural `/plan-review-cascaded` prototype run with María 🌸 as doctrine consultant + 4 reviewer roles (Mr. Radio 🦉 Author, Rachel 🕊️ Usability/Reuse, Arnold 🪨 Viability/Gap, Rio ⚡ Ownership-Language Audit). Cascade surfaced 12 findings across both sections of the toy email-verification plan; manager-absorbed 9; escalated 3 cross-section foundational findings via combined Trigger 1+2 → Rick picked Option 1 (Convention 4 markers). Author closed cluster Round 1. Cascade declared complete at the 2-section ratification gate; Stages 3 on A + 2-3 on B intentionally skipped per Rick's wrap directive once primary value-prop was proven.

**Body-display truncation arc** (the dominant Run-1 dead-air contributor): Rio diagnosed root cause as `ENTRY_SEPARATOR = "\n---\n"` collision with markdown thematic-break syntax at `commons_store.py:46`. Fix: new separator `\n<<<__lupin_commons_entry_boundary__>>>\n` + legacy fallback in `read()` + `_warn_orphan_blocks` defense-in-depth + 200-line migration script with header-lookahead regex + 14+29 unit tests + 100% coverage. Migration ran clean (48 files scanned, 42 mutated, 432 entry-boundaries swapped). Verified post-MCP-restart via probe: 2200-char `---`-laden body round-trips byte-equivalent. Sub-bug B (write-side disk truncation, María 2026-05-17) is DEFINITIVELY SEPARATE per Rio's awk re-verify on `dm-maria.md`; Mr. Radio's fastmcp atomic-write track remains relevant for a future session.

**Heartbeat daemon for Run 2**: Python daemon at `src/scripts/cascade_heartbeat_scheduler.py` + wrapper `start-cascade-heartbeat.sh`. Implements postmortem §6.B + PIP playbook §6.4 spec — manager-only scope, 2-3 min active cadence, 3-strikes dead-man's-switch → priority=high notify, cascade-complete signal-driven termination. Caught + fixed one bug mid-smoke-test (`cascade_is_complete` was matching Run-1's historical wrap-up post; fix scopes detection to content added after `initial_size` captured at daemon start). Smoke test PASSED: `register_status=201`, `dm_dispatched=true`, system-reminder push-wake verified end-to-end.

**Postmortem collaboration** (María authored, I reviewed): `planning-is-prompting/src/rnd/2026.05.18-cascaded-prototype-postmortem.md` + my companion input `2026.05.18-cascaded-prototype-postmortem-tiberius-input.md` answering Q1-Q5 + six additional manager-seat lessons (universal-step-zero, preemptive worker probes, single-escalation-for-clusters, manager-classification audit trail, workarounds-become-doctrine, self-audit discipline). María's 5-item doctrine track also complete: playbook §6.4 rewrite + §Manager System Prompt updates + §6.1 classification audit trail + §Step 4 ack-format clarification + severity-tag schema expansion. PIP playbook now references my heartbeat daemon as the canonical reference implementation.

**Three failure modes catalogued for §10 findings memo**:
1. Body-display truncation (read-side) — REPRODUCED Run-1, FIXED by Rio, VERIFIED 2026-05-18 by me
2. Turn-based-CC limitation (no autonomous ticks) — REPRODUCED throughout, ADDRESSED by my heartbeat daemon
3. Sub-bug B (write-side disk truncation) — STILL OPEN; Mr. Radio's atomic-write investigation track remains relevant

**Files (parent Lupin only — CoSA + PIP untouched per nested-repo rules)**:
- `src/lupin_mcp/commons_store.py` (MOD — Rio's separator fix; 100% coverage)
- `src/scripts/migrate-commons-entry-separator.py` (NEW — Rio's migration script, 100% coverage)
- `src/scripts/cascade_heartbeat_scheduler.py` (NEW — heartbeat daemon, py_compile clean, smoke-tested)
- `src/scripts/start-cascade-heartbeat.sh` (NEW — executable wrapper)
- `src/tests/unit/commons/test_commons_store_separator_collision.py` (NEW — 14 tests)
- `src/tests/unit/commons/test_migrate_commons_entry_separator.py` (NEW — 29 tests)
- 48 commons topic files mutated by migration (entry-boundary separator swap; body content untouched)

**PIP repo touches** (separate repo, not committed by me — María handles):
- `src/rnd/2026.05.18-toy-input-plan-email-verification.md`, `2026.05.18-cascaded-prototype-postmortem.md`, `2026.05.18-cascaded-prototype-postmortem-tiberius-input.md` (NEW)
- `workflow/plan-review-cascaded.md`, `plan-review-cascaded-defaults.md`, `plan-review-cascaded-personas.md` (MOD — postmortem-driven doctrine bundle)

**Run 2 status**: PREP COMPLETE on both fronts. María signaled consolidated ready to Rick. Heartbeat daemon ready to launch. Run-2 window selection is Rick's call. All 6 participating sessions (me + María + 4 reviewers) heading into `/clear` to start Run 2 from fresh contexts.

---

### 2026.05.17 - Session 225e5b2d (Tiberius 🌑) | Coordinator dispatch + Phase 5 unit tests + 100% coverage on model-server carve-out

Day-long session driven by Rick's @all broadcast (`21bb12cd`) authorizing planning-only coordinator work across Tiberius / Mr Radio / Arnold. Three deliverables landed: ratified-plan walkthrough, Phase 5 implementation, end-of-day ritual.

**Coordinator dispatch (broadcast `21bb12cd` → ratifications)**:
- Read TODO.md + bug-fix-queue.md, ranked 6 actionable items in descending importance, dispatched assignments via DM to Mr Radio (Commons DM topic-case + truncation + persona-space cluster) + Arnold (writer-side `owner_user_id` stamper + §6 SessionStart hook bug). Surfaced a NEW sub-bug (persona-with-space breaks derived topic name) during dispatch and folded into Mr Radio's scope.
- Both peers landed plan docs within minutes: Arnold found the §6 root-cause (`register_session.py:811-812` fresh-write bug wiping `user_id` on every `/clear`); Mr Radio ruled out one truncation hypothesis via code review pre-investigation.
- Walked Rick through 13 Q-decisions (11 formal + 2 supplementary) via sequential `ask_multiple_choice` / `ask_yes_no`. Net: 11 ratifications match peer recommendations; 2 diverge (migration α not β; unicode broadening). Plus 2 binding clarifications from Rick: (a) unicode all the way down to INI config — persona keys use exact spelling; (b) 100% coverage across the board, no PR with failing tests, period.

**Phase 5 — Model-server unit tests + 100% coverage**:
- 110 new unit tests across 5 files, all green on first run (~6s total). 100% line + branch + function coverage on both new source files (`speech_to_text_provider.py` 110 stmts / 26 branches; `lupin_model_server/main.py` 100 stmts / 12 branches). Carveout-scoped coverage on three modified files (`embedding_provider.py`, `routers/speech.py`, `fastapi_app/main.py` lifespan switch).
- Q9 hybrid scope honored + Q13 `_run_whisper_with_retry` CUDA-OOM-retry contract pinned via 2 test cases.

**Inter-session intervention**: Rio DMed from lookml session reporting Rick hitting a doc-viewer 404. Diagnosed as URL-shape regression — his emission helper used deprecated `?scope=` query param + missing project prefix in `path=`. Replied with corrected URL shape; he folded into his project CLAUDE.md + feedback memory immediately.

**Files (parent Lupin only — CoSA untouched per `feedback_lupin_only_never_cosa`)**:
- `src/tests/unit/test_speech_to_text_provider.py` (NEW, ~620 LOC, 47 tests)
- `src/tests/unit/test_lupin_model_server_main.py` (NEW, ~370 LOC, 36 tests)
- `src/tests/unit/test_embedding_provider_carveout.py` (NEW, ~205 LOC, 14 tests)
- `src/tests/unit/test_speech_router_carveout.py` (NEW, ~225 LOC, 9 tests)
- `src/tests/unit/test_main_lifespan_carveout.py` (NEW, ~95 LOC, 4 tests)
- `src/tests/conftest.py` (MOD +160 LOC — 3 opt-in fixtures: `reset_speech_provider_singleton`, `reset_embedding_provider_singleton`, `fake_model_server_client`)
- `src/rnd/v0.1.7/2026.05.16-model-server-carveout/02-phase5-unit-tests-and-coverage-design.md` (NEW, ~530 LOC — Phase 5 plan doc)
- `src/rnd/v0.1.7/2026.05.16-model-server-carveout/91-phase5-smoke-audit.md` (NEW, ~135 LOC — 5.0d audit output)
- `src/rnd/v0.1.7/2026.05.16-model-server-carveout/92-phase5-closure.md` (NEW, ~200 LOC — completion report)
- `src/rnd/v0.1.7/2026.05.17-coordinator-walkthrough-ratifications.md` (NEW, ~210 LOC — all 13 ratifications + scope additions)
- `TODO.md`, `bug-fix-queue.md`, `history.md`, `history/README.md` (MOD — entries + bookkeeping)
- `history/2026-05-12-to-15-history.md` (NEW — archive landed earlier today)

**Pre-existing broader-suite failures noted**: full `src/tests/unit/` has 48 unrelated pre-existing failures (TFE / hooks / JWT / answer-correctness). Verified via `git stash` — failures exist before AND after my changes. Phase 5 itself is at 110/110 green; the broader-suite cleanup is a separate workstream.

**End-of-session ritual** (per Rick's 2nd broadcast `197cd263` authorizing Tiberius-lead on backup + push + weekly stats): this entry, commit, push, backup, daily + weekly LoC delta.

---

### 2026.05.16 - Session 3c9fce51 (María 🌸) | Checkpoint 5: cosa-voice MCP discovery-surface expansion (instructions field 65→~300 lines + 6 commons_* docstring upgrades)

Cross-session pair-collab with Tiberius 🌑 (planning-is-prompting `b714e138`) on documenting cosa-voice for fresh CC sessions. Rick triggered the work after observing today's María↔Tiberius DM thread surface multiple inline-discoverability gaps. Tiberius took the boot-time-doctrine side (`planning-is-prompting/workflow/cross-session-communication.md` refresh + thin pointer in `~/.claude/CLAUDE.md`); I took the MCP-server-bound side. Five framework iterations between us before convergence on the 5-surface model (CLAUDE.md / MCP `instructions` / planning-is-prompting workflow / per-tool docstrings / per-turn rider — split by reading timing, not content type).

**Implementation delivered**:
- `src/lupin_mcp/cosa_voice_mcp.py` (+~313 LOC) — instructions field grew from ~3k chars to **21,316 chars** (~5,329 tokens) across **10 sections**: Instructions vs Per-Turn Rider framing, Your Toolkit at a Glance (6-group nav map), Speakerphone Mode (existing + forward-pointer to Startup Protocol), Voice Persona Self-Announcement (existing + forward-pointer), MCP Startup Protocol (Phase A + Phase B), Inter-Session Commons Protocol (3-tier autonomy + reserved topics), Phase 0 DM Workflow (push-vs-poll + receipt etiquette with loop-avoidance step 4 + sender-mailbox convention + cross-session bug-filing pattern + DM-vs-broadcast), Interactive Tool Routing, Failure Modes + Debugging Signals (7 patterns), Deep Doctrine Reference (cross-pointer footer with §-by-§ pointers to Tiberius's refresh)
- 6 commons_* docstrings (`commons_who` / `commons_read` / `commons_post` / `commons_ask_sync` / `commons_ask_async` / `commons_send_to`) upgraded with Tiberius's 7 priorities: tier markers on line 1 (D1 BLOCKING), one example per tool (D2 HIGH), inline failure-mode hints incl. new `register_skip_reason` (D3 HIGH), threading callout in `commons_post` (D4), receipt mechanism in sender docstrings (D5), `expect_reply` side-effect promotion (D6), cross-ref footer (D7)
- `src/rnd/v0.1.7/2026.05.16-mcp-discovery-surface-expansion.md` — NEW R&D doc, status APPROVED FOR CODE-WRITE post-Rick-ratification

**Tiberius review walkthrough** (5 Q-points): section flow + pacing (one real dependency identified, fixed via forward-pointers), tier-marker formulation (landed cleanly), failure-mode hints precision (5 patterns accurate; added #6 persona-cache staleness + #7 topic-file case sensitivity), cross-reference footer accuracy (all 6 pointers correct + added §1.5.3 Threading), receipt etiquette alignment (added step 4 loop-avoidance + sender-mailbox `topic='dm-<sender>'` convention). Verdict: ship as-is. ~30 LOC of polish applied after review.

**Memory saved**: `feedback_mcp_doc_layering_decision_point_vs_doctrine` (now `mcp-doc-layering-five-surfaces-by-reading-timing`) — the 5-surface framework attributed to joint discovery.

**Surfaced 2 bugs during the cross-session DM thread**:
1. Topic-file case sensitivity in `commons_send_to` wrapper — DMs fragment across `dm-Tiberius` (capital T from recipient arg) and `dm-tiberius` (lowercase). Push-mode persona resolution works case-insensitively so DMs still deliver, but topic-files fragment. Filed at TODO.md top with 5-LOC fix proposal.
2. System-reminder body truncation on push-injection — when push fires, the recipient's `<system-reminder>` body may be clipped; canonical body lives in the topic file. Mitigation documented in instructions §"Failure Modes" item #7 + receipt-etiquette step 2 ("always re-fetch via `commons_read` for canonical body").

**Process artifact worth noting** (per Rick's broadcast asking for follow-up summary doc with Tiberius): today's collaboration shape — iterative correction loop (María proposes 5-layer → Tiberius corrects to 3-layer → Tiberius re-corrects back to 5-layer + adds Q2 enrichments → joint memory saved) + DM-thread-as-mini-design-doc + paired-by-DM-paired-by-commit pattern — produced sharper output than either of us would have produced alone. Tiberius and I will draft a follow-up summary R&D doc tomorrow covering this workflow as a replicable template, with a pointer from the project README.

**Files** (this checkpoint — Lupin parent only; CoSA submodule untouched per `feedback_lupin_only_never_cosa`):
- `src/lupin_mcp/cosa_voice_mcp.py` (MOD ~+313 LOC)
- `src/rnd/v0.1.7/2026.05.16-mcp-discovery-surface-expansion.md` (NEW R&D doc)
- `TODO.md` (PRIORITY-1 history-archive deferral entry added at top; case-fragmentation + truncation sub-bugs filed earlier)
- `history.md` (this entry)
- `.claude-session.md` (Checkpoint 5 update — pending)

**Commit**: <pending>

**Health note**: history.md is at 26,032 tokens (104% of 25k limit) at session-end. Rick approved deferring the archive to first-thing next session via `ask_multiple_choice` gate. Tracking in TODO.md PRIORITY-1.

---

### 2026.05.16 - Session 0025f917 (Rio ⚡) | Model-server carve-out: Whisper + 2 encoders moved to lupin-model-server:7998, doom-loop structurally killed

Day-long sequenced design + implementation arc. Rick voice-driven the whole way; I owned execution. Phases 0-5 of the carve-out shipped, INI flipped, dev + test bounced into remote-mode, model-server brought up into freed VRAM, all 9 smoke-test cases green.

**Primary doc**: [`src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md`](src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md) — full design with REUSE pass, Pass 1 Fitness (25 ACs, blast-radius matrix), Pass 2 Ownership Audit (37 actions executor-tagged, 5 USER gates), auth refinement override section, and Part 2 bounce actuals.

**Companion**: [`90-baseline-metrics.md`](src/rnd/v0.1.7/2026.05.16-model-server-carveout/90-baseline-metrics.md) — pre-carve-out measurements (host GPU, per-container VRAM, image size, cold-start time 29.52 s).

**What landed (parent Lupin repo)**:

- **New**: `src/lupin_model_server/{__init__.py, main.py}` (~440 LOC) — minimal frozen FastAPI app on `:7998` exposing `/health` (503 until 3 models in VRAM), `/transcribe`, `/embeddings/{generate,batch,info}`, `/admin/metrics` (Prometheus). Auth via boot-time bcrypt hash of the existing `notification-api-claude-code-dev` key.
- **New**: `docker/lupin-model-server/Dockerfile` (140 LOC) — mirrors `docker/lupin/`'s nvidia/cuda:12.4.1 base + cuda-compat-12-4 purge (RTX 4090 fix), Python 3.11, pinned torch 2.6.0+cu124 + transformers + sentence-transformers + prometheus-client + bcrypt, models baked at build time.
- **New**: `src/tests/smoke/test_model_server_smoke.py` (~250 LOC, 9 test cases) — exercises every endpoint + 3 auth-rejection cases + end-to-end via compute. All passing in 3.02 s.
- **New**: `src/rnd/v0.1.7/2026.05.16-model-server-carveout/{01-design.md, 90-baseline-metrics.md}` — design doc subdirectory.
- **Modified**: `docker-compose.yml` — added `lupin-model-server` service entry (port 7998, GPU 0 pinned via CUDA_VISIBLE_DEVICES=0 per `feedback_lupin_models_always_gpu_0`, healthcheck, ck_live_* key bind-mount); added `LUPIN_MODEL_SERVER_URL` + `LUPIN_MODEL_SERVER_API_KEY_FILE` env vars to compute services.
- **Modified**: `src/conf/lupin-app.ini` — new keys `speech to text provider = local` (defaults preserve behavior) + `model server url`.
- **Modified**: `src/conf/lupin-app-splainer.ini` — matching explanations.
- **Modified**: `src/fastapi_app/main.py` — Phase 3.6 lifespan switch reads provider mode; if `model-server`, SKIP all 3 eager GPU loads + call `SpeechToTextProvider.declare_remote_only()` + run 60-s readiness probe against `:7998/health`. Otherwise unchanged.
- **Deleted**: `docker/whisper/Dockerfile` — legacy Flask-based proto from Jan 2025, dead since the FastAPI migration.

**CoSA-submodule changes (NOT committed from parent context per `feedback_lupin_only_never_cosa`)** — held for separate CoSA-context commit:
- `src/cosa/memory/embedding_provider.py` — extended URL resolver to honor `LUPIN_MODEL_SERVER_URL` env → INI → None; consolidated `_model_server_api_key` into existing `_http_api_key` (single namespace).
- `src/cosa/memory/speech_to_text_provider.py` (new) — mirrors `EmbeddingProvider` architecture: singleton, class-level `_is_in_process_owner` flag, INI-driven `speech to text provider` switch, local + HTTP paths, exp-backoff retry wrapper.
- `src/cosa/rest/routers/speech.py` — `Depends(get_whisper_pipeline)` → `Depends(get_speech_provider)`; legacy `_run_whisper_with_retry` marked deprecated but kept; new `save_upload_to_temp` helper.

**Cross-session collaboration** (cosa-voice MCP `commons_send_to` DMs):
- Rick voice-routed an API-key design question to María (session `3c9fce51`) after I'd overbuilt a parallel `ck_internal_*` namespace.
- María's brief: existing validator is DB-backed bcrypt; frozen container can't reuse it directly; recommended Option (b) — file-based allowlist validator in model-server reusing the `ck_live_*` namespace.
- Rick ratified Option (b). I rolled back my `ck_internal_*` invention (deleted generator script + key file + bcrypt-hash env var), rewired model-server to read the existing `notification-api-claude-code-dev` plaintext, hash at boot, validate via `bcrypt.checkpw`.

**The bounce (Part 2)** — ~32 seconds wall-clock total (faster than 45-60 s predicted because models were baked into the image, no HF downloads at boot):
1. INI flip `local` → `model-server`
2. `docker restart lupin-rest-dev` (10.9 s — old process dies + frees 3.2 GB)
3. `docker restart lupin-rest-test` (11.1 s — another 3.2 GB freed)
4. `docker compose up -d lupin-model-server` (<1 s init + 9.4 s model loads)
5. Compute readiness probes succeed → `:7999` + `:8000` bind, serve via HTTP-proxy

**Three mid-flight bugs caught + fixed in-session**:
1. **HF cache bind-mount PermissionError** — initial compose pointed at a non-existent host dir that overwrote the baked-in image cache. Fix: removed the bind-mount; image is self-sufficient.
2. **Embedding endpoint self-recursion** — `docker restart` doesn't re-read compose, so `LUPIN_MODEL_SERVER_URL` env var never injected. `_resolve_model_server_url()` only checked env, fell back to compute's own URL → infinite recursion → 10-s timeout. Fix: resolver now checks env → INI → None (mirrors speech-provider); `docker compose up -d --force-recreate` to inject the env var.
3. **`/transcribe` 422** — leftover `_authenticated: str = ...` in endpoint signature → FastAPI required-body-field rejection. Fix: deleted the unused parameter; rebuild + recreate.

**Final state**:
- GPU 0 used: **19,889 MiB** (was 23,131 MiB → saved 3,250 MiB, matches Rick's net-savings math)
- GPU 0 free: **4,335 MiB** (was 1,086 MiB → headroom 4× pre-carve-out)
- `:7998/health` 200, 3 models loaded (whisper + code_rank_embed + nomic_embed_text_v1_5), 2,505 MiB VRAM
- `:7999/health` + `:8000/health` 200
- 9/9 smoke tests passing in 3.02 s
- Native browser ASR confirmed working post-fix
- Doom-loop: Layers 1 + 3 structurally GONE from compute containers; Layer 2 (`--reload`) harmless because no GPU dependency to break

**Remaining work for next session** (see TODO.md):
- Phase 4 cleanup: strip `--gpus all` from compute compose entries; drop the 3 model pre-downloads from `docker/lupin/Dockerfile:208-210`; rebuild `lupin:1.0.0-noasr` candidate.
- Phase 5.2-5.5: unit tests for `SpeechToTextProvider`; `mock_model_server_client` pytest fixture; push to 100% coverage on all new/modified files per the Lupin-wide coverage mandate (per `feedback_100pct_coverage_multiplexer` — scope-expanded 2026-05-16).
- Phase 7: CLAUDE.md DOCUMENTATION TOUCHPOINTS row + `~/.claude/skills/server-lifecycle/SKILL.md` update for the new `lupin-model-server` bounce semantics.
- Push (deferred per Rick's no-push instruction at session-end).

**Memory updates this session**:
- New `feedback_lupin_models_always_gpu_0.md` — hard rule from Rick: Lupin models ALWAYS pin to GPU 0, never auto-pick.
- Updated `feedback_100pct_coverage_multiplexer.md` — scope expanded from multiplexer TS to ALL Lupin code per Rick's "Coverage floors are bullshit. Everything has to pass at 100%. Full stop. Everything!" directive mid-Pass-1.

---

### 2026.05.16 - Session 3c9fce51 (María 🌸) | Daily LoC Delta tool — new `cosa.repo.git_loc_delta` sibling of `branch_analyzer`

User-initiated voice-first ask to view an unserialized Claude Code plan via the doc viewer (`/app/docs?path=cosa/...&scope=cosa`) surfaced two adjacent issues: (1) the URL itself referenced a retired `?scope=` param and a non-registered `cosa` project, and (2) the plan `resilient-soaring-turtle.md` at `~/.claude/plans/` was not yet serialized into any repo. Per the plan-serialization mandate, the fix was serialize-first then implement. User chose CoSA-submodule R&D destination (Option B in `ask_multiple_choice` voice gate).

**Plan doc serialized**: [`src/cosa/rnd/2026.05.16-daily-loc-delta-tool.md`](src/cosa/rnd/2026.05.16-daily-loc-delta-tool.md) — Status flipped from "🟢 APPROVED FOR CODE-WRITE" → "🟢 SHIPPED" through a Reduced PIP review:

- **REUSE pre-pass** — all 7 reuse-map citations verified against current code (`file_classifier`, `exceptions`, `git_diff_parser:115-150`, `run_branch_analyzer:69-156`, `quick_smoke_test` template, `to_csv` pattern, `get_project_root()`). 2 minor line-range drifts fixed (R4 `63-155` → `69-156`; R6 usage-clarification note). Sweep check confirmed no existing per-day git-log LoC tool. User-ratified via `ask_yes_no`.
- **Pass 1 Fitness** — 18 ACs derived (8 correctness + 5 coverage + 3 style + 2 edge case), 8 fitness findings filed (F1 `reports/` → `io/` convention alignment, F2 unit-tests-required-not-optional per Testing Ownership Mandate, F3 testing-tier table consolidation, F4 explicit Sweep Check section, F5 formal AC section, F6 edge-case section, F7 exit-code documentation, F8 smoke-test scope decision). All 8 amendments folded in. User-ratified via `ask_yes_no`.

**Implementation shipped** (10 files):
- `src/cosa/repo/git_loc_delta/__init__.py` — package exports
- `src/cosa/repo/git_loc_delta/exceptions.py` — `GitLocDeltaError`, `DateRangeError`; re-exports `GitCommandError`
- `src/cosa/repo/git_loc_delta/git_log_parser.py` — `GitLogParser.iter_changes()` over `git log --numstat`, binary-row skip, malformed-row defense
- `src/cosa/repo/git_loc_delta/daily_aggregator.py` — `DailyAggregator` with `(date, file_type)` bucketing + per-date rollup + summary view; loads `branch_analyzer.FileTypeClassifier` via `ConfigLoader().load()`
- `src/cosa/repo/git_loc_delta/csv_writer.py` — `write_csv()` tidy-long, 6-column stable schema, sorted by `(date asc, added desc)`
- `src/cosa/repo/git_loc_delta/report_formatter.py` — `format_console()` two-table layout + `format_json()` nested dict
- `src/cosa/repo/git_loc_delta/analyzer.py` — `GitLogLocDeltaAnalyzer` orchestrator + `quick_smoke_test()` with 7 ✓/✗ checks
- `src/cosa/repo/run_git_loc_delta.py` — CLI entry with mutually-exclusive date-range group, exit codes 0/1/2, mode-aware default CSV path
- `src/cosa/repo/git_loc_delta/README.md` — comprehensive user docs covering Use Case A (end-of-day daily ritual) + Use Case B (pre-PR summary) + CLI reference + architecture + reuse map + edge cases + future enhancements
- `src/tests/unit/test_git_loc_delta.py` (parent Lupin) — 4 unit tests: parser binary skip, aggregator bucketing, CSV schema stability, empty-input header-only

**Test pyramid — all 5 tiers green**:

| Tier | Result |
|---|---|
| T1 py_compile (9 source + 1 test) | ✅ 9/9 OK |
| T2 import chain | ✅ all resolved |
| T3 unit tests | ✅ 4/4 PASSED in 0.31s |
| T4 quick_smoke_test() | ✅ 7/7 ✓ |
| T5 live CLI on Lupin (today / --branch / --output csv) | ✅ all 3 modes verified |
| T5 live CLI on CoSA submodule (--repo-path src/cosa --branch) | ✅ working |

**Real-world outputs** (current branch state):
- Lupin: 21 days, 216 commits, 532 files, +147,999 / −13,171 (net +134,828). Heaviest day 2026-05-04 (+18,599). File types: markdown (docs work), python (CoSA/agents), typescript (multiplexer refactor).
- CoSA: 17 days, 69 commits, 73 files, +12,561 / −3,272 (net +9,289). 2026-05-05 the only net-negative day (−459 net) due to 625 python deletions.

**Post-ship docs + filename-flip iteration** — after live spin-up on both repos, user voice-requested comprehensive docs + flagged a workflow concern: the original date-stamped default filename (`{YYYY-MM-DD}-loc-delta.csv`) didn't fit a daily-overwrite-per-branch workflow. Two `ask_multiple_choice` decisions ratified:
- **Q1 doc location**: package README at `src/cosa/repo/git_loc_delta/README.md` (CoSA convention, co-located with code)
- **Q2 filename mode**: flip default to mode-aware — `--branch` mode → `{repo}-{branch-slug}-loc-delta.csv` (stable per-branch, daily-overwrite-friendly); `--today` / `--since`/`--until` mode → date-stamped (archival)

Verified post-flip: Lupin run produced `lupin-wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe-loc-delta.csv` (118 rows); CoSA run produced `cosa-wip-v0.1.7-2026.04.23-tracking-lupin-work-loc-delta.csv` (34 rows).

**Pending CoSA-context commit** (per `feedback_lupin_only_never_cosa`):
- [ ] **[LUPIN-COSA]** Commit in a CoSA-context session: 8 source files under `src/cosa/repo/git_loc_delta/` + `src/cosa/repo/run_git_loc_delta.py` + `src/cosa/rnd/2026.05.16-daily-loc-delta-tool.md`. Suggested commit message: `[COSA] Add git_loc_delta sibling — per-day LoC analysis via git log --numstat`

**Workflow notes**: Plan-serialization mandate triggered by user's doc-viewer 404 (file at `~/.claude/plans/` not yet serialized). Reduced PIP review (REUSE + Pass 1 Fitness, both with explicit user gates via `ask_yes_no`) chosen over Full PIP via `ask_multiple_choice` — appropriate for a single-session internal CLI with no API/UI/handoff surface. Documentation-first protocol observed: R&D plan + package README both drafted before final filename-flip code change. Tested everything end-to-end across both Lupin parent + CoSA submodule before declaring shipped.

**Memory rules engaged**: `feedback_walk_through_plan_before_asking_proceed` (substantive findings via notify before every gate), `feedback_pip_plan_review_is_sequential` (REUSE → gate → apply → Pass 1 → gate → apply), `feedback_always_include_pros_cons_recommendation` (per-option pros/cons in `ask_multiple_choice` abstracts), `feedback_tts_body_headline_and_takeaway_only` (spoken `message` carried headlines only; details in `abstract`), `feedback_doc_links_always_in_abstract` (viewer link as line 1 of abstract), `feedback_lupin_only_never_cosa` (CoSA submodule edits OK, git ops forbidden from parent), `feedback_verify_staging_before_commit` (`git diff --cached --stat` before this checkpoint commit), `feedback_never_auto_commit_push` (explicit voice authorization for this commit), `feedback_documentation_step_stops_at_doc` (filename-flip surfaced as separate decision after doc work).

#### Checkpoint 1 | 2026.05.16 19:35 UTC | Daily LoC Delta — Lupin-side artifacts

**Files** (parent Lupin only): src/tests/unit/test_git_loc_delta.py (NEW), TODO.md (MOD), history.md (this entry), .claude-session.md (session section)
**Commit**: 2e0e7e5
**CoSA-side pending**: 10 files awaiting CoSA-context session (Rick claimed EOD ownership)

#### Checkpoint 4 | 2026.05.16 21:18 UTC | Commons-activity entries: collapsible body + markdown rendering

User-requested UI ship after the María↔Tiberius DM thread filled the Recent Activity panel with multi-paragraph content. Two coordinated features in one change:

1. **Two-line clamp by default** — body content wraps in new `.commons-activity-entry-body-content` div with `-webkit-line-clamp: 2`. "Show more ▾" / "Show less ▴" button toggles `.expanded` class on click. Button auto-hides via `requestAnimationFrame` measurement when content doesn't actually overflow the clamp — short DMs stay clean, no redundant affordance.
2. **Markdown rendering** — reuses the established `marked.parse() → DOMPurify.sanitize()` pattern from `broadcast-panel.js:127-139`. Page-loaded `window.marked` + `window.DOMPurify` globals, graceful fallback to plain `textContent` if either lib unavailable. Compact markdown-CSS-reset prevents tall paragraphs / list spacing from blowing up the panel.

**Test pyramid**:

| Tier | Spec | Result |
|---|---|---|
| node --check | `notifications.js` after edits | ✅ syntax clean |
| Existing watcher unit tests | `test_commons_activity_watcher.py` | ✅ **22/22 PASS** (no regressions) |
| New Playwright E2E (Phase 1 — code written) | 10 tests in `test_commons_activity_toggle.py`: clamp, toggle cycle, markdown rendering, XSS sanitization | ⏳ Code shipped; :8000 scheduled run pending Rick's slot confirmation |
| Visual regression baselines | clamped state + expanded state + short-no-toggle state | ⏳ same — needs :8000 slot |

**XSS sanitization tests** specifically:
- `<script>window.__commons_xss_marker = true;</script>` body → asserts marker variable never set
- `<img src='x' onerror='...'>` body → asserts onerror handler never fires + asserts `onerror=` stripped from innerHTML
- Lockes the DOMPurify-via-broadcast-panel-pattern contract for this surface

**Files in commit (Lupin parent — all served by FastAPI :7999 which auto-reloads static files immediately)**:
- `src/fastapi_app/static/js/notifications.js` (MOD — body-section rewrite, ~45 LOC)
- `src/fastapi_app/static/css/notifications.css` (MOD — new clamp/toggle/markdown rules, ~95 LOC)
- `src/tests/e2e_ui/test_commons_activity_toggle.py` (NEW — 10 Playwright E2E tests, ~230 LOC)
- `history.md` (this sub-entry)
- `.claude-session.md` (Checkpoint 4 + touched-files update)

**Commit**: <pending>

#### Checkpoint 3 | 2026.05.16 21:05 UTC | Commons DM push-mode + Git LoC Delta cross-target fix arc (5 fixes, F1-F5)

Live debugging triggered by Rick's challenge of an earlier "awaiting commit" framing exposed 3 latent bugs + 1 deployment gap + 1 test-pyramid gap from the prior two ship arcs (Inter-Session DM Phase 0 yesterday, Daily LoC Delta this morning). Five fixes (F1-F5) landed in one arc with full regression coverage.

**Fixes**:
- **F1**: Replace `os.environ.get("LUPIN_MCP_API_KEY")` (env var was added in commit `9bbf298` without source-side wiring — silent fallback to polling on every push-mode call) with `du.get_api_key("notification-api-claude-code-dev")` — the canonical pattern already used by `cosa.memory.embedding_provider._http_api_key` for embeddings HTTP auth. Rick caught the cleaner abstraction; no new key to mint, no docker-compose changes.
- **F2**: `commons_send_to` was calling the `@mcp.tool`-decorated `commons_ask_async` by name (resolves to `FunctionTool` instance, not callable) — `TypeError: 'FunctionTool' object is not callable` on every invocation. Refactored both wrappers to delegate through a shared private `_commons_ask_async_dispatch()` helper.
- **F3**: Silent push-mode fallback now surfaces `register_skip_reason` ("missing_auth_header" / "missing_api_base_url" / "register_failed_status_N" / "register_failed_422") in the result dict. Previously `push_mode_active: false` with no other signal.
- **F4**: `_default_csv_path` cross-repo bug filed by Tiberius 🌑 session `b714e138` — was using `cu.get_project_root()` (always LUPIN_ROOT) as the base, so cross-repo invocations dumped CSVs into Lupin's `io/` tree instead of the target. Two-stage fix: first pass via `os.path.abspath` regressed the in-tree-from-subdir case, final fix uses `git rev-parse --show-toplevel` from the supplied `--repo-path` to resolve actual repo root.
- **F5**: Added 3 new unit tests covering cross-target invocations — the test class my earlier ship had missed. Locks both the cross-repo case and the no-regression-on-in-tree case.

**Test pyramid — all green**:

| Tier | Result |
|---|---|
| py_compile (4 files) | ✅ OK |
| Import chain | ✅ resolved |
| `git_loc_delta` unit tests (4 existing + 3 new) | ✅ **7/7 PASS** in 0.27s |
| Full commons unit suite (438 + 7) | ✅ **445/445 PASS** in 35.29s, **0 regressions** |
| Live cross-repo (Tiberius's reproducer) | ✅ CSV lands at `planning-is-prompting/io/git-loc-delta/...` (correct) |
| Live in-tree from `lupin/src/` (subdir cwd) | ✅ CSV lands at `lupin/io/git-loc-delta/...` (correct — git toplevel resolution) |
| Live in-tree from `lupin/` (repo root cwd) | ✅ CSV lands at `lupin/io/git-loc-delta/...` (correct, unchanged) |
| Live DM via `commons_ask_async` to running MCP subprocess | ⚠ Stale — returned `push_mode_active: false` with NO `register_skip_reason` (confirms running fastmcp subprocess hasn't reloaded; next CC session picks up fix automatically) |

**Process correction — testing failure acknowledged**: My initial test pyramid for `git_loc_delta` only invoked the tool with `--repo-path .` and `--repo-path src/cosa` — both INSIDE the Lupin tree. I never tested cross-repo, which is the primary use case. Direct violation of the Testing Ownership Mandate ("user is never the tester"). Two memories saved to prevent recurrence: `feedback_tests_must_cover_cross_target_invocations` + `feedback_env_var_read_and_set_land_together`.

**R&D doc**: [`src/rnd/v0.1.7/2026.05.16-commons-dm-and-git-loc-delta-fix-arc.md`](src/rnd/v0.1.7/2026.05.16-commons-dm-and-git-loc-delta-fix-arc.md) — full diagnosis + fix-by-fix breakdown + deployment caveat about fastmcp subprocess staleness.

**Files** (this checkpoint):
- `src/lupin_mcp/cosa_voice_mcp.py` (MOD — F1 + F2, ~70 LOC)
- `src/lupin_mcp/commons_ask.py` (MOD — F3, ~25 LOC)
- `src/tests/unit/test_git_loc_delta.py` (MOD — F5 +90 LOC, 3 new cross-target tests)
- `src/rnd/v0.1.7/2026.05.16-commons-dm-and-git-loc-delta-fix-arc.md` (NEW R&D doc)
- `history.md` (this sub-entry)
- `.claude-session.md` (Checkpoint 3 + touched-files update)

**Commit**: <pending>

**CoSA-side pending** in Rick's EOD batch: `src/cosa/repo/run_git_loc_delta.py` (F4, ~30 LOC) alongside earlier LoC Delta sources + broadcast fan-out watcher fix.

#### Checkpoint 2 | 2026.05.16 20:25 UTC | Bug fix — duplicate broadcast fan-out (consumer-side dedupe in CommonsActivityWatcher)

Rio's `bug-fix-queue.md` "Bug #2 — duplicate notification fan-out" (filed 2026-05-16 morning) diagnosed and fixed. Root cause: producer/consumer asymmetry — `perform_fanout` writes N per-recipient rows to the `broadcasts` topic by design (for `target_session_id`-scoped routing on the HTTP path), the HTTP read path `/api/commons/broadcast-history` collapses N → 1 via `_dedupe_broadcasts_by_id` + `_dedupe_broadcast_acks_by_recipient`, but `CommonsActivityWatcher._tick()` (the WS push path) dispatched one `commons_activity` event per raw row — so the Recent Activity panel saw N rows from one broadcast.

**Fix**: Mirror the HTTP-path dedupe inside the watcher. New `_dedupe_for_dispatch` method in `CommonsActivityWatcher` (~80 LOC), called from `tick()` between sort and dispatch. Cursor advancement uses pre-dedupe max ts so dropped duplicates don't re-surface next tick. Zero changes to write side (per-recipient rows still needed for HTTP-path same-user scoping).

**Test pyramid**:

| Tier | Result |
|---|---|
| py_compile (2 files) | ✅ OK |
| import chain | ✅ resolved |
| Targeted unit (22 watcher tests: 15 pre-existing + 7 new) | ✅ **22/22 PASS** in 0.07s |
| Full commons regression (438 tests) | ✅ **438/438 PASS** in 14.80s, **0 regressions** |
| Live :7999 broadcast smoke | ⏳ Pending Rick's hands-on confirmation |

**R&D doc**: [`src/rnd/v0.1.7/2026.05.16-broadcast-fanout-watcher-dedupe.md`](src/rnd/v0.1.7/2026.05.16-broadcast-fanout-watcher-dedupe.md) — full diagnosis, fix shape, test coverage, 2 pending follow-ups (write-side `broadcast-acks` multiplicity per Arnold's investigation note; persona-stamping asymmetry 4×Mr-Radio + 1×Rio).

**Files** (this checkpoint):
- `src/tests/unit/commons/test_commons_activity_watcher.py` (MOD — +170 LOC, 7 new tests)
- `src/rnd/v0.1.7/2026.05.16-broadcast-fanout-watcher-dedupe.md` (NEW R&D doc)
- `TODO.md` (MOD — fan-out entry flipped NEW → ✅ FIX SHIPPED)
- `history.md` (this sub-entry)
- `.claude-session.md` (Checkpoint 2 added to session 3c9fce51 section)

**Commit**: <pending>

**CoSA-side pending** (per `feedback_lupin_only_never_cosa`): `src/cosa/rest/commons_activity_watcher.py` awaits Rick's EOD batch commit alongside the DM Phase 0 CoSA pieces + LoC Delta CoSA pieces.

---

### 2026.05.16 - Session dfd7b2d8 (Mr. Radio 🦉) | Doc viewer SPA dispatcher 404 fix + /api/docs/health regression

Rick reported a 404 on `/app/docs?path=lupin/src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md` — a doc-link emitted by the path-prefix routing model the 2026-05-15 scope unification put on the wire. Backend served the file fine when called directly (HTTP 200, 16,159 bytes via JWT-authed `/api/docs/file?path=lupin/...`); the bug was entirely in the frontend SPA. The May-15 unification updated `/api/docs/file` to accept `path=<project>/<rel>` form and retired the `?scope=` query param, but it never touched `src/fastapi_app/static/html/document-viewer.html`. The SPA's dispatcher still defaulted `scope` to `'io'` when absent and routed everything to `/api/io/file` — which has no Lupin source paths under it.

**Primary doc**: [`src/rnd/v0.1.7/2026.05.16-doc-viewer-spa-dispatcher-fix.md`](src/rnd/v0.1.7/2026.05.16-doc-viewer-spa-dispatcher-fix.md) — full bug analysis, fix sweep, verification matrix, parked follow-ups.

**Fix shipped (3 production files, 5 test files)**:

1. **SPA dispatcher rewrite** — `document-viewer.html` lines 235-258 replaced with first-segment path-prefix routing. New rules: `io/<rel>` → `/api/io/file?path=<rel>`; `<known-project>/<rel>` → `/api/docs/file?path=<full>`; bare paths fall through to `/api/io/file` (backwards-compat for `notifications.js` job-card links and persisted job metadata). Updated directory-listing breadcrumb generator to emit the new URL form.
2. **`_dir_listing.py::_build_view_url`** (CoSA submodule) — emits path-prefix URLs (`/app/docs?path=<scope>/<rel>`), retiring legacy `?scope=` form. IO binary routes (audio/pdf/image/pptx) unchanged.
3. **`docs_files_health` rewrite** (CoSA submodule) — was crashing with `NameError: ALLOWED_FILES` on every call (legacy whitelist constants were removed in unification but health handler missed). New response shape iterates the scope registry: `{status, project_root, io: {root, exists}, scopes: {name: {root, exists, allowed_prefixes, manifest}}, media_types}`. `/api/docs/health` back to HTTP 200.

**Tests**:

| File | Status |
|---|---|
| `src/tests/smoke/test_doc_viewer_path_prefix_routing.py` | **NEW** — 7 targeted regression tests |
| `src/tests/smoke/test_docs_files_endpoint.py` | Full rewrite (15 tests) — JWT auth + path-prefix form (file was silently failing since May 12 multi-repo auth landed) |
| `src/tests/smoke/test_io_files_endpoint.py` | Added JWT auth + path-prefix view_url assertion |
| `src/tests/smoke/test_external_scopes.py` | Full rewrite (17 tests) for unified routing model |
| `src/tests/unit/test_dir_listing.py` | Updated 9 routing-table assertions to new view_url shape |

**Verification (all on :7999, AI-discretionary)**:

| Layer | Result |
|---|---|
| User's exact URL via `/api/docs/file` | ✅ HTTP 200, 16,159 bytes |
| SPA shell at `/app/docs?path=lupin/...` | ✅ HTTP 200, 20,411 bytes |
| `/api/docs/health` | ✅ HTTP 200 (was 500) |
| Doc-viewer smoke (4 files combined) | ✅ 52 passed, 1 skipped |
| Doc-viewer unit (`test_dir_listing.py`) | ✅ 30 passed |
| Full unit suite | ✅ **4,623 passed, 1 xfail, 0 regressions** |

**Follow-up parked** (NOT done this session):
- `src/tests/e2e_ui/test_doc_viewer_multi_repo.py` + `test_doc_viewer_directory.py` still use legacy `?path=…&scope=…` URLs (10+ call sites). These run on :8000 monopolize-mode — needs a user-scheduled slot with `--update-snapshots` to refresh visual baselines.
- `notifications.js` lines 7110, 7112, 7374, 7379, 7387 + `podcast_generator/job.py` line 335 + `presentation_generator/job.py` similar pattern still emit bare-io-relative `/app/docs?path=…` URLs. Works today via the dispatcher's legacy fallback branch; harmonization to `?path=io/…` is cosmetic.

**Sub-repo edits pending separate sessions** (per `feedback_cosa_edit_vs_manage_git`): `src/cosa/rest/routers/docs_files.py` + `src/cosa/rest/routers/_dir_listing.py` — uncommitted in CoSA working tree; commit from a CoSA-context session.

#### Checkpoint | 2026.05.16 13:44 | Doc viewer SPA dispatcher + health endpoint regression fix

**Files**: document-viewer.html, 5 test files, 1 new R&D doc (+2 CoSA submodule edits pending separate commit)
**Commit**: 656ec0c

---

### 2026.05.16 - Session 0025f917 (Rio ⚡) | Voice persona stale-bridge pool exhaustion fix + Sam-as-overflow

Same-day root-cause + fix for a live bug Rick reported voice-first: 5 fresh CC sessions returned 3 × Rio + 2 × Mr. Radio with 4 of 5 marked `borrowed=true`, at day-start when the pool should have been wide open. Root cause was sharper than just stale state — the in-container bypass of the dead-PID filter (`session_bridge.py:1284-1287`, intentional because host PIDs are invisible from inside `lupin-rest-dev`) counted every leftover bridge with a non-null persona as occupied. Five May-15 bridges (maría, Rachel, Tiberius, Arnold, Mr. Radio) made the pool read 5/6 occupied the moment my session took Rio; every subsequent session fell into the deterministic sha256-mod-pool borrow path, which happened to hash to Rio×2 + Mr. Radio×2.

**Primary doc**: [`src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md`](src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md) — diagnostic evidence table (10 bridge files audited), four-layer solution, phase order, verification matrix, risks/gotchas.

**Four-layer solution shipped**:

1. **Host-side prune at SessionStart** — new `prune_dead_persona_bridges()` in `session_bridge.py`, called from `register_session.py` Phase 4.4 (before Phase 4.5 allocation). Runs only when `_can_trust_host_pids()` returns True. Scrubs the `voice_persona` field on any bridge whose host PID is dead. Fixes the morning-of-day case completely.
2. **mtime-based TTL guard inside container** — `find_active_voice_persona_sessions(stale_threshold_seconds=43200)` now rejects bridges whose file mtime exceeds the threshold (default 12h, INI-tunable via `cc session voice persona stale threshold seconds`). Belt-and-suspenders for the residual case where the host-side prune didn't fire. The cc-notification-listener heartbeat keeps active bridges fresh.
3. **Sam-as-overflow allocation** — replaces the legacy hash-borrow. New `load_overflow_persona_from_config()` reads `cc session voice persona sam {icon, color, profile, display name}` + the existing `elevenlabs tts default voice id` (single source of truth for Sam's `voice_id`). `pick_unallocated_persona` now returns Sam with `overflow=True` when the pool is fully occupied; multiple Sams permitted, multiples of other personas not. `borrowed_persona_for_sid` survives as legacy fallback only when Sam is unconfigured.
4. **UI / mobile overflow badge** — new `.persona-badge.overflow` (dotted border + ✱) in `notifications.css`, distinct from legacy `.persona-badge.borrowed` (dashed + ↻); `notifications.js` composes the state class with overflow-precedence-over-borrowed; mobile dart `VoicePersona` gained `final bool overflow` with liberal `fromJson`.

**Bug #2 logged for follow-up** (separate session): duplicate notification fan-out — single system broadcast rendered 5× and single "completed" status produced 4 × Mr. Radio + 1 × Rio. Filed in `TODO.md` under "📡 NEW — Duplicate notification fan-out (filed 2026-05-16 by Rio ⚡, session `0025f917`)" with a four-step investigation checklist.

**Verification (all on :7999, AI-discretionary)**:

| Layer | Result |
|---|---|
| py_compile sweep across 6 Python files | ✅ all compile |
| `pytest src/tests/unit/test_voice_persona_helpers.py -v` | ✅ **52/52 pass** (34 pre-existing + 18 new) |
| Sam overflow logic inline smoke (3 scenarios) | ✅ free→pool, exhausted→Sam, exhausted-no-Sam→legacy-borrow |
| TTL guard inline smoke (2 scenarios) | ✅ fresh mtime returned, stale mtime filtered |
| New smoke test for pool exhaustion → Sam | authored at `src/tests/smoke/test_voice_persona_allocation.py::test_pool_exhaustion_returns_sam_overflow` (8 synthetic bridges; not auto-run against live state — saved for Rick to run when convenient) |

**New unit-test classes** (18 tests): `TestLoadOverflowPersonaFromConfig` (3), `TestPickUnallocatedPersonaOverflow` (5), `TestFindActiveVoicePersonaSessionsTTL` (4), `TestPruneDeadPersonaBridges` (6).

**Documentation touchpoints updated**: `CLAUDE.md` DOCUMENTATION TOUCHPOINTS row for voice-persona now references both 2026.04.28 (original design) and 2026.05.16 (this milestone); new row for `prune_dead_persona_bridges` + `find_active_voice_persona_sessions` TTL guard. Companion 2026-05-16 Update section appended to the original 2026.04.28 design doc.

**Sub-repo follow-ups pending separate sessions** (per `feedback_lupin_only_never_cosa`):
- `src/cosa/rest/voice_persona_helpers.py` — `load_overflow_persona_from_config` + `pick_unallocated_persona` overflow path + threading through `allocate_persona_for_session` (CoSA submodule — commit in CoSA-context session)
- `src/cosa/rest/routers/voice_persona.py` — pass overflow persona to allocator + extend `voice-persona/sample` voice_id whitelist (CoSA submodule)
- `src/lupin-mobile/lib/features/notifications/data/voice_persona.dart` — `final bool overflow` field + toString update (mobile sub-repo — commit in mobile-context session)

**Files committed this session** (parent Lupin repo): 12 modified + 1 new R&D doc + this `history.md` entry.

**Workflow notes**: User-initiated voice-first bug report → ultrathink + plan-mode → 4-layer plan in single ExitPlanMode → user verbal approval after 10-min review window → 8 phases executed silently with milestone notify at completion. Memory rules engaged: `feedback_walk_through_plan_before_asking_proceed` (substantive findings via notify before any code), `feedback_doc_links_always_in_abstract` (R&D viewer-link as abstract line 1), `feedback_exit_plan_mode_is_not_user_approval` (explicit verbal go-ahead via `ask_yes_no` after harness auto-approval), `feedback_lupin_only_never_cosa` (no git ops on src/cosa/ from parent), `feedback_verify_staging_before_commit` (`git diff --cached --stat` before commit), `feedback_never_auto_commit_push` (no push without explicit ask).

---

