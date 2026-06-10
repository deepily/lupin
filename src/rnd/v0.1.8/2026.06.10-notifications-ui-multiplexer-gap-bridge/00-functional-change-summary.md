# Notifications-UI Functional-Change Summary (since anchor `26898e1`)

**Author:** Rachel 🕊️ (for Tiberius 👑) · **Date:** 2026-06-10 · **Lane:** docs-only analysis
**Deliverable 1 of 3** — see [`01-gap-analysis.md`](01-gap-analysis.md) and [`02-bridging-work-plan.md`](02-bridging-work-plan.md).

## Purpose

This is the **inbound** half of the gap-bridge: every user-facing capability added to (or
changed in) the legacy JS notifications client since the multiplexer work paused. The anchor
is commit `26898e1` (2026-05-29, the v0.1.7 merge `#17`) — the last point at which the
multiplexer TS rewrite and the JS monolith were roughly in lockstep. Everything below landed
in `notifications.js` / `notifications.html` / `notifications.css` **after** that anchor and
must be absorbed by the multiplexer before the JS client can be deprecated.

> **Path note:** through `9211e5c` (2026-06-06) these files lived at
> `src/fastapi_app/static/...`; commit `2b044b5` (2026-06-08) renamed the tree to
> `src/lupin_app/static/...`. Same `NotificationsUI` class, same files.

## Surface sizes (current)

| File | Lines |
|---|---|
| `src/lupin_app/static/js/notifications.js` | 19,375 |
| `src/lupin_app/static/html/notifications.html` | 1,257 |
| `src/lupin_app/static/css/notifications.css` | 5,961 |

## Feature Inventory (grouped, not one-per-commit)

### F1 — Master-Detail "Reading Pane" (the dominant shared widget)
**User-visible:** In horizontal layout, clicking an abstract-indicator icon or a doc-link opens
a right-side Reading Pane rendering the abstract (sanitized markdown) or embedding a doc in an
iframe. The pane has Back, Close, and a **bust-out (⤢)** button that pops content into a new
browser tab (docs as URL, abstracts as rendered HTML) then closes the pane. The section toolbar
re-centers whether the pane is open (`ratio/2`) or closed (50%). Iframe docs fill edge-to-edge
at full height (was a ~150px "postage stamp"). A **second click on the same indicator toggles
the pane closed**; a different indicator switches content. Center-column scroll position is
preserved across open and close.

- **Commits:** `cd6cc99` (centering, iframe embed/size, bust-out, focus-height doubling),
  `9211e5c` (scroll preservation), `97bfb8c` (abstract-icon toggle), `498e98e` (split-ratio leak fix).
- **JS:** `_openContentPane`, `_closeContentPane`, `_bustOutContentPane`, `_renderContentPaneEntry`,
  `_backContentPane`, `_updateToolbarPosition`, `_applyPaneSplitRatio`, `_normalizeDocLinkHref`,
  `_abstractAlreadyShown`, `_captureCenterScrollAnchor`, `_restoreCenterScrollAnchor`.
  State: `_contentPaneHistory` (depth 10), `_paneSplitRatio` (default 0.667 → pane = 1/3), `_layoutMode`.
- **DOM/CSS:** `#content-pane*`, `#content-pane-bustout` (`data-testid=notifications-content-pane-bustout`),
  `.content-shell.pane-open`, `.content-pane-body:has(iframe)`, `--toolbar-center-x`.
- **Server dep:** doc iframe needs `X-Frame-Options: SAMEORIGIN` on `/app/docs` only (set server-side); loads `/app/docs?path=...`. No new endpoint.
- **E2E:** `test_layout_mode_toolbar_centering.py`, `test_abstract_indicator_toggle.py`; smoke `test_doc_viewer_iframe_embedding.py`.

### F2 — Action-Required in the Reading Pane
**User-visible:** When a blocking decision arrives in horizontal mode, the live
`#action-required-content` is lifted into the Reading Pane at a forced 50/50 split, and the home
section is hidden. While it owns the pane, abstract/doc opens are suppressed. When the AR queue
drains, content moves home and the prior pane content + divider ratio are restored. Layout-mode
switches and page-reload restores both route correctly.

- **Commits:** `e1ed26a` (built), `498e98e` (50/50→1/3 restore fix).
- **JS:** `_enterActionRequiredPaneMode`, `_exitActionRequiredPaneMode`; state `_actionRequiredInPane`,
  `_arPaneStash`; hooks in `addActionRequiredNotification`, drain handler, layout switch, restore path,
  and the `_openContentPane` guard.
- **E2E:** `test_action_required_in_pane.py`.

### F3 — Focus-mode card height boost
**User-visible:** With CC focus mode ON, the focused sender card's per-day message lists grow to
**500px** (double the 250px default); non-focus cards stay 250px.

- **Commits:** `23d3726` (375px), `cd6cc99` (→500px). **CSS-only.**
- **CSS:** `body:has( #cc-strip-toggle[data-focus-active="true"] ) .sender-card:not([data-focus-hidden]) .date-accordion-messages { max-height: 500px }`.
- **E2E:** assertion in `test_cc_session_strip_and_focus.py`.

### F4 — Broadcast / commons-activity "Show more" toggle fix
**User-visible:** Broadcasts arriving via WebSocket while the Recent Activity panel is collapsed
now correctly surface a "Show more" toggle once content gains layout (was permanently hidden due
to a 0×0 measurement).

- **Commit:** `23d3726`.
- **JS:** `revealToggleIfOverflowing()` closure + `ResizeObserver` fallback inside the commons-activity row renderer; DOM `#commons-recent-activity-body.collapsed`.
- **E2E:** `test_commons_activity_toggle.py`.

### F5 — STT insert-at-caret
**User-visible:** Dictation into any of the 8 STT-enabled text fields inserts at the caret
(replacing only a highlighted range) instead of select-all+overwrite; caret lands after inserted
text so repeat dictation appends.

- **Commit:** `8ad6f38`.
- **JS:** `_insertTranscriptionText(inputElement, text)`, called from the shared `onTranscription` callback.
- **E2E:** `test_stt_insert_at_cursor.py` (8 cases incl. wiring-chain guard).

### F6 — TTS preview-fraction slider finer granularity
**User-visible:** The TTS preview-percentage slider steps in **12.5% increments** (9 stops 0–100%); default stays 25%.

- **Commit:** `e5a72e2`.
- **DOM:** `#cc-tts-fraction-slider` (`step` 25→12.5), `#cc-tts-fraction-value`, `#cc-tts-fraction-ticks` datalist (9 options); drives `this.ttsPreviewFraction` (localStorage; INI default seed).
- **E2E:** `test_tts_controls.py` (`TestTTSFractionSlider`).

### F7 — "N missed while away" badge + Reset (messaging-coordination plane, lever D)
**User-visible:** On WS auth, a "Missed: N missed while away" indicator shows if undelivered
notifications accumulated offline. A **Reset** button soft-dismisses them (`is_hidden=True`
server-side, reversible) and zeroes the badge live — no confirm prompt. Shows only when count > 0.

- **Commits:** `722e624` (badge + lever D outbox/inbox), `c0db33d` (Reset + dead-global fix), `bbde599` (confirm removed).
- **JS:** `_surfaceMissedNotifications(count)` (from `auth_success.undelivered_count`), `resetMissedNotifications()`;
  state `notificationState.undeliveredCount`.
- **DOM:** `#missed-status`, `#missed-reset-button` (inline `onclick="window.notificationsUI.resetMissedNotifications()"`).
- **Server dep:** WS `auth_success` envelope now carries `undelivered_count`; new endpoints
  `GET /api/notifications/undelivered` + `POST /api/notifications/undelivered/dismiss`; repo methods
  `get_/count_/dismiss_undelivered_for_recipient`.
- **E2E:** `test_system_status.py` (`TestMissedResetButton`).
- **Bug fixed here:** the Reset and Logout buttons referenced dead `window.freshQueueUI`; corrected to `window.notificationsUI`.

### F8 — Prediction-hint thumbs vote + markdown/confidence fixes
**User-visible:** Under a prediction hint (shown only when confidence ≥ 50%), 👍🏼/👎🏼 vote buttons
send a human-confirmed training signal (up = reinforce, down = steer away); cast vote highlights.
Also: code fences in message bubbles now render as styled `<pre>/<code>`; the "22123%" confidence
overflow is clamped to [0,100].

- **Commit:** `bbde599`.
- **JS:** `_buildPredictionVoteControls(notification, confidencePct)` (MIN_PCT=50), `votePrediction(id, vote)`;
  state `_predictionVoteContext`; `renderMarkdownInline` delegates fenced content to `renderMarkdown`.
- **DOM/CSS:** `.prediction-hint-vote`, `.prediction-vote-up/-down` (inline onclick), `.message-text code/pre`.
- **Server dep:** `POST /api/notify/prediction-vote/{id}`; `ProxyDecisionEmbeddings` clamp + `record_hint_vote`; 4 new INI keys (incl. `prediction hint vote min confidence threshold = 0.50`).
- **E2E:** `test_prediction_hint_vote_e2e.py`.

### F9 — Reap event → focus-bar badge drop + broadcast refresh
**User-visible:** When a worker session is reaped, its focus-bar strip badge disappears live and
the broadcast recipient list refreshes — no reload.

- **Commit:** `8702cb3`.
- **JS:** `case "session_reaped"` → `senderPersonaMap.delete`, `_setPersonaBadgeOnCard(id,null)`,
  `_removeStripIcon(id)`, `_applyHideInactiveStripFilter()`, `window.broadcastPanel.refreshSessions()`.
- **Server dep:** new WS/notification event `session_reaped` (producer `dismiss_sessions`); re-fetch hits `/api/commons/active-sessions`.
- **E2E:** none in `e2e_ui/` (unit only — `test_session_spawner_reap.py`).

### F10 — Spin-up persona symmetry + bubble-hover removal
**User-visible:** A freshly spawned worker appears on **both** the focus bar and broadcast recipient
list immediately (no reload). The redundant native tooltip (`title=`) was removed from all 4
`.message-text` bubble render paths.

- **Commit:** `282be5d`.
- **JS:** `voice_persona_assigned` case extended with `parseSenderId` + `_addStripIcon` (idempotent) + `broadcastPanel.refreshSessions()` + `_applyHideInactiveStripFilter()`; `title=` removed from 4 sites.
- **E2E:** none in `e2e_ui/` (JS unit only).

### F11 — Focus-bar manager-lineage badge
**User-visible:** Each spawned worker's strip icon shows a corner badge of the **manager that
spawned it** (manager color + initial, top-left, opposite the speaker badge). Roots get none.
Appears on first render (live-patched), survives cold reload (hydrated), clears on release/reap.

- **Commits:** `457ff14` (built), `e1ed26a` (cold-reload hydration + polish), `a9ea8ab` (first-render live-patch fix).
- **JS:** state `managerPersonaMap`; populated in `voice_persona_assigned` (`payload.manager_persona`) and senders-visible hydration; cleared in `voice_persona_released` + `session_reaped`; helpers `_applyManagerBadge`, `_setManagerBadgeOnStripIcon` (via `_addStripIcon`).
- **CSS:** `.cc-strip-icon .cc-strip-manager-badge` (18px, `--manager-color`), `data-has-manager`.
- **Server dep:** `voice_persona.py` `_resolve_manager_persona` (reads bridge `spawned_by`); ships `payload.manager_persona`; cold-reload hydration via `_manager_persona_for_sender_id`.
- **E2E:** `test_manager_badge_strip.py`; server unit `test_voice_persona_manager_badge.py`.

### F12 — Read-only Fleet-Status table
**User-visible:** A new collapsible "🛰️ Fleet Status" section (toolbar jump icon) below
Notifications. Shows active sessions grouped by manager hierarchy (managers as headers with 👑,
workers indented with `└`, "(Unmanaged)" bucket last), auto-polls every 60s, manual ⟳ refresh,
"last updated HH:MM:SS TZ" stamp. **8 columns:** Who · Role · State · Holding-on · Stuck · Liveness
verdict (raw-4-ages hover tooltip) · % Window · Window-size. **Live-only by default**; a
"Show offline (N)" toggle reveals dead sessions in place. Degrade-safe banners.

- **Commits:** `5f52cfd` (built, 6 cols), `cd36378` (live-only + toggle), `a96f213` (toggle no-restamp), `99a7466` (+2 context cols). Server data-source `182ed99` (PID-liveness override — not a UI change).
- **JS (~lines 8449–8870):** `fetchFleetState`, `groupFleetByManager`, `_splitFleetByLiveness`, `toggleFleetShowOffline`, `renderFleetStatusTable`, `_renderFleetRow`, `_formatWindowSize`, `_formatConsumptionPct`, `_formatFleetTimestamp` (Intl/DST), `startFleetStatusPolling`/`stopFleetStatusPolling`, `refreshFleetStatus`. State `FLEET_STATUS_POLL_INTERVAL_MS=60000`, `fleetShowOffline`, `_lastFleetComposite`.
- **DOM/CSS:** `#section-fleet-status`, `#fleet-status-*`, toolbar 🛰️ btn; `.fleet-status-table`, `.fleet-group-*`, `.fleet-row-*`, `.fleet-role-badge`, `.fleet-col-*`. **Gap:** `.fleet-offline-toggle*` has no dedicated CSS (default button styling) — note for porter.
- **Server dep:** `GET /api/arbiter/fleet-state` (JWT reverse-proxy → arbiter `:8001/state`; returns `app_timezone` + `fleet_arbiter.sessions[]` + `context_pressure.personas` map; HTTP 200 `{status:"unreachable"}` on upstream fail).
- **E2E:** `test_fleet_status_panel.py`.

## Cross-cutting mechanisms (port as units, not piecemeal)

1. **Reading Pane** (`#content-pane` / `_contentPaneHistory` / `_paneSplitRatio` / `_updateToolbarPosition`) is shared by F1 + F2. The 50/50-vs-1/3 ratio interaction is subtle: `_openContentPane` must re-assert `_applyPaneSplitRatio()` on every open.
2. **Focus-bar / CC-session strip** (`_addStripIcon`, `_removeStripIcon`, `_applyHideInactiveStripFilter`, `_setPersonaBadgeOnCard`, `senderPersonaMap`, `managerPersonaMap`) is shared by F9 + F10 + F11. Reap and spin-up handlers are deliberate inverses; the manager badge routes through the single idempotent `_applyManagerBadge`.
3. **`window.notificationsUI` is the canonical global** for inline `onclick=` (Reset, prediction-vote, fleet-refresh, fleet-offline-toggle, logout). `window.freshQueueUI` is dead.
4. **`renderMarkdownInline` / `renderMarkdown`** are shared by bubbles, the Reading Pane abstract path, and bust-out HTML; the F8 fence-delegation touches every inline render site.
5. **New/extended WS vocabulary:** `session_reaped` (new), `voice_persona_assigned` (+`payload.manager_persona`), `voice_persona_released`, `auth_success.undelivered_count`. Fleet table is the only **polling** feature (60s) — everything else is WS-reactive.
6. **Two commits lack `e2e_ui/` coverage** (`8702cb3` reap, `282be5d` spin-up/hover) — JS/Python unit only. The 100% coverage mandate will require E2E backfill on port to the multiplexer.

## Source of truth

Verified by reading each commit diff (`git show <hash> -- <files>`) plus the matching R&D design
docs under `src/rnd/v0.1.8/`. Server-dependency endpoint names taken from
`src/cosa/rest/routers/{notifications,voice_persona,arbiter}.py`.
