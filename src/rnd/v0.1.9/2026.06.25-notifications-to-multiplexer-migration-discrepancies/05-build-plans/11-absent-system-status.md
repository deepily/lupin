# System Status — Build Plan (absent → build)

**Date**: 2026-06-26 (this session, for Rick)
**Status**: 🟡 **DRAFT for cascaded review** (run on Rick's dev `:7999`, not the laptop).
**Author**: build-plans corpus, plan 11 of 11 (accordion #11).
**Source audit refs**: doc `04-remaining-accordions-audit.md` §"#11 System Status" (verdict ❌ **TRULY ABSENT** — the mux `fleet-status-pane` is a DIFFERENT concept: a multi-host fleet table, NOT local WS/auth/session/health status); master verdict table row 11.
**Decision-of-record refs**: TODO Decisions Log 2026-06-26 (total 13/13 parity through-line); doc 04 §"Resolved" ruling (g) "Port ALL 7 absent accordions → total 13/13 parity … System-Status … sequenced after CC-session + the 3 partials." Note (g) explicitly lists System-Status while the audit prose flags it as *"maybe"* an intentional dev/diagnostic drop — **§8 surfaces that tension for a final reviewer call.**

> Shared template + cross-cutting mandates live in [`00-plans-index.md`](00-plans-index.md). This plan inherits all 7 cross-cutting mandates (100% L/B/F · Layout-Parity Oracle T0–T4 · single-source CSS · venue routing · lane isolation · in-flight-crew coordination · doc touchpoints) **by reference** — they are NOT restated here.

---

## 1. Goal & parity target

Build a new `SystemStatusRenderer` mux pane that surfaces the **local transport / auth / session diagnostics** the legacy `#section-status` "System Status" accordion provided (legacy `notifications.html:1069-1133`): live WS-connection pills for the queue + audio channels, authentication state + signed-in user, the "missed while away" count + reset, the per-channel session ids with copy buttons, a WS health indicator, and the two admin actions config-reload + logout. "Done" = every legacy `#section-status` row has a working mux equivalent bound to the **mux transport facades / `AuthManager` / the existing stores** (not a re-implemented WS stack), at 100% L/B/F, visually matched to the legacy section per the Oracle tiers. **This pane is unrelated to and does NOT merge into `fleet-status-pane`** (different concept — see §8 for the merge question that the reviewers must still rule on).

## 2. Scope

**IN**
- W1 — **`SystemStatusRenderer` + `SystemStatusStore`** scaffolding: a new top-level section/pane (`#system-status-pane`), owns its subtree (FleetStatus/JobsPane "renderer owns its DOM" convention), mounts via the boot 8-line handshake, registered in the section-toolbar toggle list.
- W2 — **WS connection pills** (queue + audio): a state→[label,class] map over the mux `ConnectionState` vocab, driven by `connection_state_change` EventBus events filtered by `payload.transport` (live updates, not poll-only) + a manual ⟳ refresh that reads `transports.queue.state` / `transports.audio.state`.
- W3 — **Auth status + user display**: signed-in email + admin badge from `AuthManager` (`getCurrentUserEmail()` + a roles/admin accessor — see §4 gap), "Not authenticated" / "Token expired" states.
- W4 — **Missed count + Reset**: reuse the existing `MissedStore` (`count()` / `reset()` → `POST /api/notifications/undelivered/dismiss`) — render the count + a Reset button; do NOT re-implement the dismiss path.
- W5 — **Session id(s) + copy buttons**: render the mux session id(s) with a 📋 copy-to-clipboard affordance + transient checkmark feedback. (Legacy showed two ids — queue + audio; the mux uses **one shared** id for both transports — **resolved in §4 / open in §8**.)
- W6 — **WS health indicator** (`#ws-health-status` equivalent): a derived health string from connection state(s). The mux has **no existing WS-health monitor** (grep → only fleet/commons "health" hits, unrelated) — derive a minimal health verdict from the two `ConnectionState`s rather than porting legacy's separate heartbeat monitor (**design call — §8**).
- W7 — **Admin actions**: config-reload (`↻ Reload` → `GET /api/init`, with a `#config-status` result line) + logout (clears tokens via `StorageService.clearTokens()` and redirects/re-auths). **Both gated behind the reviewer ruling in §8** on whether admin/dev actions belong in the production mux UI.

**OUT** (explicit)
- Any re-implementation of the WS transport, reconnect, or token-refresh stacks — this pane is a **read-mostly view** over `transports.*`, `AuthManager`, `MissedStore`. No transport behavior changes.
- Fleet-status content (multi-host table) — that is `fleet-status-pane`, a separate accordion (#6, already a faithful port). No merge in this plan (the *question* of merging is raised in §8, but the default scope keeps them separate).
- The `#section-direct-tts` / `#section-debug` dev blocks that sit adjacent in legacy — those are plans 09 / 10.
- New server endpoints — `GET /api/init`, `POST /api/notifications/undelivered/dismiss`, and the WS endpoints all already exist. Pure front-end (TS/CSS) plan.

The ratified ruling this executes: doc 04 §"Resolved" (g) — total 13/13 parity, no "obsolete" drops (subject to the §8 dev-drop reconsideration).

## 3. Source anchors

### Legacy reference behavior (read-only — DO NOT port verbatim; mirror semantics)
- **HTML** `static/html/notifications.html` — `#section-status` block **L1069-1133**:
  - header + `#refresh-status-btn` (↻, `refreshAllStatus()`) **L1070-1079**.
  - `#queue-ws-status` **L1084**, `#audio-ws-status` **L1088** (pills).
  - `#auth-status` **L1092**.
  - `#missed-status` + `#missed-reset-button` **L1096-1097** (`resetMissedNotifications()`).
  - `#user-display` + `#logout-button` **L1101-1102** (`logout()`).
  - `#queue-session` / `#audio-session` `<code>` + `.copy-btn` 📋 (`copyToClipboard('queue-session'|'audio-session')`) **L1106-1117**.
  - `#ws-health-status` **L1121**.
  - `#reinit-config-btn` (↻ Reload, `reinitializeConfig()`) + `#config-status` **L1125-1130**.
- **JS** `static/js/notifications.js`:
  - `refreshAllStatus()` **L1356-1398** — spins the ↻ button; calls the four sub-refreshers in order.
  - `refreshWebSocketStatus()` **L1400-1432** — reads `this.queueChannel.state` / `this.audioChannel.state` (string facade state), maps via a stateMap (`DISCONNECTED/CONNECTING/AUTHENTICATING/CONNECTED/BACKOFF/OPEN_CIRCUIT` → [label,class]); "Not initialized" when channel missing.
  - `refreshAuthStatus()` **L1434-1471** — `getStoredTokens()`, `isTokenExpired()`, `refreshAccessToken()`, `parseJWTPayload()` → email + `roles.includes('admin')` → `#auth-status` + `#user-display`.
  - `refreshSessionDisplay()` **L1473-1479** — writes `this.queueSessionId` / `this.audioSessionId` to `#queue-session` / `#audio-session`.
  - `copyToClipboard(elementId)` **L1481+** — clipboard write + checkmark feedback (skips empty / `'-'`).
  - `checkWebSocketHealth()` / `updateWsHealthStatus(text, statusClass)` **~L1092 region** — writes `#ws-health-status`.
  - `reinitializeConfig()` **L1295+** → `fetch('/api/init')`; writes `#config-status` + spins `#reinit-config-btn`.
  - `resetMissedNotifications()` **L15689+** (button wired **L15680**) → dismiss endpoint.
  - `logout()` + `handleAuthFailure()` — clear tokens / redirect.

### Server endpoints (all already mounted)
- `GET /api/init` — config reload + snapshot reload (no restart). Used by W7 config-reload.
- `POST /api/notifications/undelivered/dismiss` — `MissedStore.DISMISS_ENDPOINT` (`stores/MissedStore.ts:39`). Used by W4 (already wired in the store).
- `/ws/queue/{sessionId}` + `/ws/audio/{sessionId}` — observed indirectly via the transport facades; no direct calls here.
- (logout) — confirm whether a server `POST /api/auth/logout` exists or logout is purely client-side token clear — **open question Q4, §8.**

### Mux equivalents for each legacy status source (grepped)
| Legacy source | Mux equivalent | File:line |
|---|---|---|
| `queueChannel.state` / `audioChannel.state` | `transports.queue.state` / `transports.audio.state` (`get state(): ConnectionState`) **and** `connection_state_change` events filtered by `payload.transport` ("QueueTransport"/"AudioTransport") | `transport/QueueTransport.ts:121`, `transport/AudioTransport.ts`; `shared/types.ts:234-250` (`ConnectionStateChangePayload`); CSM emit `transport/ConnectionStateMachine.ts:250-262` |
| state vocab | **DIFFERENT** — legacy WSChannel `DISCONNECTED/CONNECTING/AUTHENTICATING/CONNECTED/BACKOFF/OPEN_CIRCUIT`; mux `ConnectionState` = `connecting\|connected\|reconnecting\|backoff\|offline\|failed` | `shared/types.ts:226-232`. **New stateMap required** (W2). |
| `getStoredTokens()` + email/roles | `AuthManager.getCurrentUserEmail()` (`auth/AuthManager.ts:219`); roles/admin via `decodeJwtClaims()` (`auth/jwt.ts:41`) | needs a thin `isAuthenticated()`/`getRoles()` helper — §4 gap |
| missed count + reset | `MissedStore.count()` / `reset()` (`stores/MissedStore.ts:54-64`), badge precedent `render/MissedBadgeRenderer.ts` | reuse as-is |
| `queueSessionId` / `audioSessionId` | boot's single `sessionId` (`boot.ts:144-147`, started on BOTH `transports.queue.start(sessionId)` + `transports.audio.start(sessionId, …)` `boot.ts:546-547`); `StorageService.getSessionId()` | **one id, not two** — §4 / §8 |
| `checkWebSocketHealth()` | **none** — no mux WS-health monitor exists | derive in W6 |
| `reinitializeConfig()` → `/api/init` | none (new fetch in renderer/store) | new |
| `logout()` | `StorageService.clearTokens()` (`shared/StorageService.ts:53,144`) — no logout flow wired | new |
| `copyToClipboard()` | none specific — `navigator.clipboard` (new small helper) | new |

### Mux targets (add / edit)
- `js/multiplexer/render/SystemStatusRenderer.ts` — **NEW**. Owns `#system-status-pane` subtree: header (title · ↻ refresh) + the status rows (WS pills · auth · missed · user · sessions · health · config). Subscribes to `connection_state_change` + the relevant store change events; repaints on change. Mirrors `FleetStatusRenderer` (`render/FleetStatusRenderer.ts:1-40`) "renderer owns its subtree" convention.
- `js/multiplexer/stores/SystemStatusStore.ts` — **NEW** (thin). Holds the latest per-transport `ConnectionState` (seeded from `transports.*.state`, updated on `connection_state_change`), the derived health verdict, and a `refresh()` that re-reads transport state + triggers auth/session reads. (Pure-model + formatters split out per the fleet `render/fleetModel.ts` precedent so the DOM-free logic is 100%-coverable in isolation.)
- `js/multiplexer/render/templates/systemStatusRows.ts` — **NEW**. DOM-free row/pill builders (`statusPill(label,class)`, `sessionRow(id,copyTestid)`, etc.), legacy class names cherry-picked verbatim (`.status-item`, `.status-warning`/`.status-good`/`.status-error`/`.status-info`, `.session-entry`, `.copy-btn`) so shared styles apply.
- `js/multiplexer/auth/AuthManager.ts` — **edit** (small): add a non-authoritative `getRoles(): string[]` / `isAdmin(): boolean` derived from `decodeJwtClaims` (or expose via a free function in `auth/jwt.ts`) — see §4 gap. Keep authority server-side; this is display-only.
- `html/multiplexer.html` — **edit**: add the `<section id="system-status-pane" data-testid="multiplexer-system-status-pane">` mount node alongside the other top-level panes (near `fleet-status-pane` L199 / `task-list-pane` L206). **Convergence file.**
- `js/multiplexer/boot.ts` — **edit**: the 8-line mount handshake (`boot.ts:238-252` template) + `bootCompletePayload.handlers` entry + `:mounted` console line; pass `transports` + `authManager` + `stores.missed` refs into the renderer. **Convergence file.**
- `js/multiplexer/render/templates/sectionToolbar.ts` — **edit**: add a 7th `SectionToggleSpec` (`sectionId:"system-status-pane"`, e.g. `icon:"🩺"`, `testid:"multiplexer-section-toolbar-system-status"`) to `SECTION_TOGGLES` (`sectionToolbar.ts:35-42`). **Convergence file.**
- `css/multiplexer/system-status.css` — **NEW** sheet, linked in `multiplexer.html` after the shared surface — **extends `css/shared/notifications-surface.css`, never forks** (mandate 3). Cherry-pick `.status-item`/`.status-*`/`.session-entry`/`.copy-btn`/`.refresh-link` rules from the legacy monolith verbatim.

## 4. Dependencies & prerequisites

- **`AuthManager` admin/roles gap.** `AuthManager` today exposes `getCurrentUserEmail()` + `getToken()` but **no roles/admin accessor** (grep: only `getCurrentUserEmail`). `auth/jwt.ts` has `decodeJwtClaims()` returning `JwtClaims` (the access token carries a `roles` claim per `jwt.ts:8-9`). W3 needs a tiny display-only `getRoles()`/`isAdmin()` (or a `jwtRoles(token)` free function mirroring `jwtEmail`). **Non-authoritative** — server enforces real authz; this only renders the "(admin)" badge. Reviewers: confirm placement (AuthManager method vs jwt.ts free fn) — minor.
- **One session id vs two.** Legacy displayed `#queue-session` + `#audio-session` as distinct ids; the mux starts BOTH transports with the **same** `sessionId` (`boot.ts:546-547`). Default plan: render a single "Session" row (the shared id) and drop the queue/audio split as an accepted simplification — but this is a **visible parity divergence**, so it is also raised in §8 for an explicit ruling. (If reviewers want the two-row look preserved, render the same id twice labeled Queue/Audio — trivial, but arguably misleading.)
- **No mux WS-health monitor.** Legacy `checkWebSocketHealth()` reflects a separate heartbeat/health subsystem. The mux has no equivalent. W6 default: **derive** a health verdict purely from the two `ConnectionState`s (e.g. both `connected` → "Healthy", any `reconnecting`/`backoff` → "Degraded", any `failed`/`offline` → "Unhealthy"). Reviewers: accept the derived health, or is a real heartbeat probe wanted (larger, likely out of scope)? — §8 Q3.
- **`MissedStore` already in the boot graph?** Confirm `MissedStore` is constructed in `boot.ts` and reachable to pass into this renderer (the `MissedBadgeRenderer` precedent implies yes). If the badge already renders the count elsewhere, W4 must not double-count — it reads the same store, shares the source of truth.
- **No INI keys** introduced. **No new endpoints.** **No new router** → the §DOCUMENTATION TOUCHPOINTS "new router"/"routers/*.py" rows do NOT fire. Doc updates limited to this rnd folder's parity-tracking docs (+ `src/docs/websocket-events.md` only if a `connection_state_change` consumer note is warranted — verify during impl).
- **Convergence-file coordination** (mandate 5): `html/multiplexer.html`, `boot.ts`, `sectionToolbar.ts`, and the shared CSS link are manager-serial-merged. Coordinate with the in-flight crews (mandate 6): Tiberius full-parity build (`704c71b2`), Rachel's `mux-section-toolbar-accordion-toggle` branch (commit-held — this plan adds a 7th `SECTION_TOGGLES` entry, a direct conflict surface → **must rebase on / coordinate with Rachel's branch**), focus-bar `4b33ceb7` (push held).

## 5. Work breakdown

Each task: **what · files · ACs (functional + structural) · Oracle tier(s)**.

**W1 — Pane scaffold + mount + toolbar registration**
- *What*: new `SystemStatusRenderer` owning `#system-status-pane`; header (title "System Status" + ↻ `#refresh-status-btn` equivalent); empty row container. Boot mount via the 8-line handshake; `SECTION_TOGGLES` 7th entry.
- *Files*: `render/SystemStatusRenderer.ts` (new), `html/multiplexer.html` (mount node), `boot.ts` (mount + handler entry + console line), `render/templates/sectionToolbar.ts` (toggle), `css/multiplexer/system-status.css` (new, linked).
- *ACs*: (functional) pane mounts, `:mounted` console line emitted in canonical order, toolbar toggle shows/hides the pane + persists via the section-hidden mechanism; (structural) `data-testid="multiplexer-system-status-pane"` present, header carries `data-testid="multiplexer-status-refresh-btn"`.
- *Oracle*: T1 DOM-contract (pane + header + refresh testids present); T0 CSS-hash (header/`.refresh-link` styling vs legacy `#section-status` header).

**W2 — WS connection pills (queue + audio), live + manual refresh**
- *What*: `SystemStatusStore` seeds `{queue,audio}` state from `transports.*.state`; subscribes `connection_state_change`, routes by `payload.transport`; renderer maps state→[label,class] via a NEW mux-vocab stateMap; ↻ refresh re-reads `transports.*.state`.
- *Files*: `stores/SystemStatusStore.ts` (new), `render/templates/systemStatusRows.ts` (pill builder), `SystemStatusRenderer.ts`.
- *ACs*: (functional) each of the 6 `ConnectionState`s renders the correct label+class; a `connection_state_change` event repaints the matching pill within one tick; refresh button re-reads state and spins/re-enables; "Not initialized" when a transport ref is absent; (structural) `#queue-ws-status` / `#audio-ws-status` equivalents carry the legacy testids (`notifications-ws-queue-status` / `…-audio-status`) and the `.status-good/.status-warning/.status-error` classes.
- *Oracle*: T1 (pill present per transport), T0/T2 (pill color/weight per status-class vs legacy), T3 geometry (two-pill row layout).

**W3 — Auth status + user display**
- *What*: read `AuthManager.getCurrentUserEmail()` + new `isAdmin()`; render "Authenticated"/"Authenticated (admin)"/"Not authenticated"/"Token expired"; user email row.
- *Files*: `auth/AuthManager.ts` (or `auth/jwt.ts`) admin accessor, `SystemStatusRenderer.ts`, `systemStatusRows.ts`.
- *ACs*: (functional) admin badge appears iff roles include `admin`; "Not authenticated" when no email; (structural) `#auth-status` + `#user-display` testids preserved.
- *Oracle*: T1 (auth/user rows present), T0 (status-class color).

**W4 — Missed count + Reset**
- *What*: render `MissedStore.count()`; Reset button calls `MissedStore.reset()`; row hidden when count 0 (legacy `display:none` parity).
- *Files*: `SystemStatusRenderer.ts`, `systemStatusRows.ts`; reuse `stores/MissedStore.ts`.
- *ACs*: (functional) count renders; Reset triggers `reset()` and the row hides on 0; no double-source vs `MissedBadgeRenderer`; (structural) `#missed-status` + `#missed-reset-button` testids preserved.
- *Oracle*: T1 (row toggles on count), T0 (button styling vs legacy gray Reset).

**W5 — Session id(s) + copy**
- *What*: render the mux session id(s) (default: single "Session" row; see §4/§8) with a 📋 `.copy-btn` → `navigator.clipboard.writeText` + transient ✓ feedback; skip copy when value empty/`'-'`.
- *Files*: `SystemStatusRenderer.ts`, `systemStatusRows.ts`, small clipboard helper.
- *ACs*: (functional) copy writes the id, shows ✓ for ~1s, no-ops on empty; (structural) `.session-entry` + `.copy-btn` classes; testids on the copy buttons. **Decision in §8 may add the second (audio) row.**
- *Oracle*: T1 (session row(s) + copy present), T0/T3 (`<code>` + 📋 inline layout).

**W6 — WS health indicator**
- *What*: `SystemStatusStore` derives a health verdict from the two `ConnectionState`s (Healthy/Degraded/Unhealthy + class); renderer shows `#ws-health-status` equivalent; recomputes on each `connection_state_change`.
- *Files*: `SystemStatusStore.ts` (derive fn — DOM-free, 100%-coverable), `SystemStatusRenderer.ts`.
- *ACs*: (functional) verdict matches the truth table for all state combinations; (structural) `#ws-health-status` id/`.status-info` class. **Gated on §8 Q3 (derived vs real heartbeat).**
- *Oracle*: T1 (health row present), T0 (status-class).

**W7 — Admin actions (config-reload + logout)** — *gated on §8 Q1/Q2*
- *What*: `↻ Reload` → `GET /api/init`, spin button, write result to `#config-status` (success/fail class); Logout → `StorageService.clearTokens()` + redirect to login (confirm the canonical mux logout flow).
- *Files*: `SystemStatusRenderer.ts`, `systemStatusRows.ts`; reuse `StorageService.clearTokens()`; possibly a tiny `api/` client call for `/api/init`.
- *ACs*: (functional) config-reload reflects 2xx/err in `#config-status`; logout clears tokens and lands on login; **admin-gate**: if reviewers rule admin actions don't belong in prod mux, W7 is dropped and the pane ships W1–W6 only; (structural) `#reinit-config-btn`/`#config-status`/`#logout-button` testids preserved iff retained.
- *Oracle*: T1 (buttons present iff retained), T0 (blue Reload / red Logout button styling vs legacy).

## 6. Test strategy & venue routing

Inherits the venue rubric from index mandate 4. This plan is **TS/CSS-only** at the unit layer; the only state mutation is `GET /api/init` (idempotent config reload) + the missed-dismiss POST (already covered by `MissedStore` tests) + token clear — those land in the :8000 E2E/integration layer, never via curl.

- **Unit (`:7999`, AI-discretionary)** — new `src/tests/unit/multiplexer/render/system_status_renderer.test.ts` + `src/tests/unit/multiplexer/stores/system_status_store.test.ts` + `src/tests/unit/multiplexer/render/templates/system_status_rows.test.ts`. Cover: W2 stateMap for all 6 `ConnectionState`s + "Not initialized" + `connection_state_change` routing by `payload.transport` + refresh-button spin/re-enable; W3 admin/non-admin/unauth/expired auth branches; W4 count>0 vs 0 row toggle + reset() call + no double-source; W5 copy success / empty-skip / ✓-feedback / (optional second row); W6 health truth-table across state combinations; W7 `/api/init` 2xx vs err `#config-status` branches + logout token-clear (mock `fetch`, `navigator.clipboard`, `StorageService`, `AuthManager`, `transports`). **100% L/B/F** via `c8 --100` — every branch tested or `c8 ignore` + same-line reason (mandate 1).
- **WebSocket smoke (`:7999`)** — extend `run-websocket-smoke-tests.sh`: drive a real queue/audio connect→drop→reconnect and assert the pills + health verdict track the live `connection_state_change` stream end-to-end (this is the one behavior unit mocks can't fully prove).
- **E2E UI + visual (`:8000`, scheduled via `POST /api/test-suite/submit`)** — Playwright: open the System Status pane, assert pills/auth/user/sessions/health render; click ↻ refresh; click a 📋 copy and assert clipboard; click Reset (missed); click Reload and assert `#config-status`. Visual-regression snapshots for the pane + each status-class pill (rebaseline — §7). Self-authorized on a verified-idle `:8000` per index mandate 4 / CLAUDE.local.md.
- **Integration (`:8000`, FINAL gate)** — real `GET /api/init` (config reload) + `POST /api/notifications/undelivered/dismiss` against API+DB+auth; add to `run-integration-tests.sh` only if a config-reload / missed-dismiss workflow isn't already covered. Logout flow exercised here (token clear + re-auth redirect).

100%-coverage statement: **lines AND branches AND functions = 100%** on all touched TS via `c8 --100`; no "≥95%".

## 7. Oracle & visual parity

Tiers exercised: **T0** (CSS-hash on the cherry-picked legacy classes — `.status-item`, `.status-warning`/`.status-good`/`.status-error`/`.status-info`, `.session-entry`, `.copy-btn`, `.refresh-link`, the blue Reload / red Logout / gray Reset inline button styles), **T1** (DOM-contract: each status row + control present with its legacy testid), **T2** (computed-style on the pills + buttons — color/weight per status-class), **T3** (geometry: the stacked status-row layout + the two-pill row + the `<code>`+📋 session row), **T4** pixel backstop only on the full pane (densest stacked layout).

**New golden captures needed** (legacy `:8000` capture cost): the legacy `#section-status` expanded accordion — full section with all rows in each meaningful state (connected vs disconnected pills, authenticated vs not, missed-row visible vs hidden, config-status populated). Rebaseline mux snapshots for `system-status-pane` after each W lands. Methodology per `2026.06.19-…/01-layout-parity-methodology.md`. **Caveat**: because the mux state vocab differs (6 `ConnectionState`s vs legacy's 6 WSChannel states, NOT 1:1) and the single-session-id simplification, the T1/T3 contract is "semantic parity," not byte-identical DOM — the Oracle gates the *visual* equivalence of each rendered state, with the vocab/label mapping documented as an accepted, reviewed divergence.

## 8. Risks & open questions (for the reviewers)

1. **Does System Status belong in the prod mux UI at all? (THE headline question.)** Ruling (g) lists it for 13/13 parity, but the audit prose flags it as *"maybe an intentional dev/diagnostic drop"* (doc 04 master verdict + §#11). Most of its content (WS pills, session ids, health, config-reload) is **developer/diagnostic** — arguably devtools/console territory in the mux philosophy (cf. the #13 Debug-Info "likely intentional drop"). **Reviewers must explicitly ratify: full port (W1–W7) · user-facing-subset only (e.g. auth/user/missed, drop the diagnostics) · or drop entirely.** This plan is written for the full port but is structured so W6/W7 (health + admin) can be sliced off cleanly.
2. **Do config-reload + logout belong in the mux UI?** `GET /api/init` is an **admin** action; logout is a session action. (a) Is config-reload wanted in the user-facing mux at all, or is it an ops-only affordance? (b) Where does logout canonically live in the mux today — is there already a logout control elsewhere (avoid duplicating)? If a mux logout already exists, W7-logout becomes a "link to it," not a re-implementation. **Needs the canonical mux logout location confirmed.**
3. **WS health: derived verdict vs real heartbeat?** The mux has no health monitor. Default W6 derives health from the two `ConnectionState`s (cheap, no new subsystem). Accept the derived health, or is a real heartbeat/latency probe wanted (larger, likely a separate effort)? If derived is fine, confirm the truth table (both connected→Healthy; any reconnecting/backoff→Degraded; any failed/offline→Unhealthy).
4. **One session id vs two.** The mux uses a single shared `sessionId` for both queue + audio transports; legacy showed two distinct ids. Default: render one "Session" row (accepted simplification). Reviewers: keep one row (recommended — reflects reality), or preserve the legacy two-row look (would show the same id twice, arguably misleading)? Also confirm whether a server logout endpoint exists or logout is purely client-side token-clear (affects W7 + the integration test).
5. **Overlap / should-merge question (mandated by the brief).** Does any of this overlap the existing **fleet-status** or **reading-pane chrome**? Findings: (a) `fleet-status-pane` is a genuinely different concept (multi-host fleet table, `FleetStatusRenderer` — no local WS/auth/session content) → **no merge**; (b) the **SessionStrip** (`SessionStripRenderer`) owns CC-session *persona* icons, NOT the WS/audio session ids → **no overlap**; (c) **reading-pane chrome** (`#reading-pane-toolbar`) hosts layout-mode + section-toolbar, not status → **no overlap**. **However**: the auth/user + missed pieces *do* conceptually overlap the missed-badge (`MissedBadgeRenderer`) and any header user-chip the mux may grow. Reviewers should rule whether System Status is a standalone pane (this plan's default) or whether its *user-facing* rows (auth/user/missed) should instead fold into a future global header chrome, leaving only the diagnostics (pills/sessions/health) in a collapsed dev pane. This is the cleanest place to split "keep" vs "drop" if §8 Q1 lands on a subset.
6. **State-vocab divergence is unavoidable.** Legacy WSChannel states ≠ mux `ConnectionState`. The new stateMap is a designed mapping, not a port — flag for review so the label choices (e.g. `backoff`/`reconnecting` → "Reconnecting…", `offline` → "Offline", `failed` → "Disconnected"/"Circuit open"?) are ratified, not assumed.
7. **Section-toolbar branch collision.** Adding a 7th `SECTION_TOGGLES` entry conflicts directly with Rachel's commit-held `mux-section-toolbar-accordion-toggle` branch (mandate 6). Must rebase on / coordinate with that branch before merging the toggle change.

## 9. Lane decomposition & estimated size

Suggested parallel lanes (worktree-isolated; convergence files manager-serial-merged):

- **Lane A — store + model (DOM-free)**: `SystemStatusStore.ts` + the health-derive fn + the stateMap module. No convergence files. Fully unit-testable in isolation. *Small (~120-160 LOC + tests).*
- **Lane B — renderer + templates + CSS**: `SystemStatusRenderer.ts`, `templates/systemStatusRows.ts`, `css/multiplexer/system-status.css`. Depends on Lane A's store interface (define the interface first, then both lanes proceed). *Medium (~200-260 LOC + tests).*
- **Lane C — auth accessor**: the `isAdmin()`/`getRoles()` addition in `AuthManager`/`jwt.ts` + its unit tests. Tiny, independent. *Small (~20 LOC + tests).*
- **Convergence merges (manager-serial)**: `html/multiplexer.html` (mount node), `boot.ts` (mount handshake + handler entry), `render/templates/sectionToolbar.ts` (7th toggle — **coordinate with Rachel's branch**), the shared CSS `<link>`. Done last, after Lanes A/B/C land.

**Rough total**: ~350-450 LOC of new TS + ~80-120 LOC CSS + ~3 unit test files. **High** relative to the other absent-accordion plans (audit estimate "~200+ LOC" was for the renderer alone; the store/auth/CSS/tests push it higher), but **lower risk** than #2 Submit-Jobs since there's no new dispatcher — it's a read-mostly view over existing facades. **Sequencing**: lands after CC-session (`01-`) + the 3 partials (`02`/`03`/`04`) per ruling (g); within the absent set, low inter-plan coupling (no hard dependency on plans 05-10), so it can run in parallel with the other absent-accordion lanes once §8 Q1 ratifies scope.
