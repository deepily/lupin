# Filter Settings (Admin) — Build Plan

**Date**: 2026-06-26 (this session, for Rick)
**Status**: 🟡 **DRAFT for cascaded review** (run on Rick's dev `:7999`, not the laptop).
**Author**: build-plans corpus, plan 08 of 11 (accordion #8).
**Source audit refs**: doc `04-remaining-accordions-audit.md` §"#8 Filter Settings (Admin)" (verdict ❌ TRULY ABSENT — no mux UI/store filter mode; grep → 0) and §"#9 Job Queues → jobs-pane" (the coupled missing `queues-filter-badge`).
**Decision-of-record refs**: doc 04 §"Resolved" ruling (g) — port ALL 7 absent accordions → total 13/13 parity; TODO Decisions Log 2026-06-26.

> Shared template + cross-cutting mandates live in [`00-plans-index.md`](00-plans-index.md). This plan inherits all 7 cross-cutting mandates (100% L/B/F · Layout-Parity Oracle T0–T4 · single-source CSS · venue routing · lane isolation · in-flight-crew coordination · doc touchpoints) **by reference** — they are NOT restated here.

---

## 1. Goal & parity target

Port the legacy "Filter Settings (Admin)" accordion into the multiplexer: an **admin-gated** 3-button view-mode switch (👤 My Jobs Only / 🚫 Not My Jobs / 👥 All Users' Jobs) that drives a single shared **filter mode** (`own` / `others` / `all`), persists the choice, updates a "Currently viewing: …" display, and surfaces the mode as a header **filter badge** on the jobs-pane (👤 Mine / 🚫 Not Mine / 👥 All Users). The mode then feeds the user-scope parameter (`user_filter` / `exclude_own_jobs`) on the mux's job-fetch paths. "Done" = an admin can switch view-mode in the mux exactly as in legacy `#filter-settings-section`, the jobs-pane badge tracks it, regular (non-admin) users never see the switch or the badge (mode locked to `own`), at 100% L/B/F.

## 2. Scope

**IN**
- W1 — **Filter-mode state**: a single source-of-truth `own|others|all` value with persistence + a change event. Recommended home: **extend `stores/ViewStateStore.ts`** (filter mode is a view preference; the store already owns the StorageService-backed view-preference maps). Alternative: a dedicated `FilterModeStore` — **open question Q1**.
- W2 — **Admin signal in the mux**: extend `auth/jwt.ts` to expose the `roles` claim + an `isAdmin` derivation (legacy `roles.includes('admin')`). Client-decoded admin is a **non-authoritative UX hint only** — the server remains the real gate (§4). Flag: the mux JWT decoder reads `email` **only** today (`jwt.ts:15-70`); `roles` is unread.
- W3 — **3-button switch UI** (admin-gated): the `own/others/all` button group + active-state toggling + the "Currently viewing: <strong>" display text, mounted where reviewers choose (§4 / Q2: dedicated `filter-settings-pane` section vs folded into the jobs-pane header).
- W4 — **Jobs-pane filter badge** wiring: the `queues-filter-badge` reflects the mode (icon + label). **This is the plan-04 seam** — plan 04 W6 *renders* the badge element; plan 08 *owns the store + event that lights it up* (§4).
- W5 — **`exclude_own_jobs` / `user_filter` plumbing** on the mux fetch paths that actually exist (history hydrate + any notifications senders/bulk fetch the mux carries), gated on `isAdmin && mode !== 'own'`, mirroring legacy call sites.

**OUT** (explicit)
- The jobs-pane **badge DOM element + its render** — owned by **plan 04 W6** (`04-job-queues-mutation-gaps.md` §2/§5-W6). Plan 08 supplies the store accessor + `store_filter_mode_changed` event it subscribes to. **Hard cross-plan seam — see §4.**
- **Live-queue-bucket re-filtering** — the legacy `/api/get-queue/{q}?user_filter=*|!self` re-fetch (`notifications.js:6131`,`:6459`) has **no equivalent in the mux**: the mux populates live buckets from the **WS push** (`job_state_transition`/`job_removed`, `JobStore.ts:224-229`, user-centric routing), not a poll. Applying `others`/`all` to *live* buckets needs a **server-side WS-scope decision** (or a new fetch-refresh path) — **deferred, flagged as the central open question Q3.** Plan 08 lands the mode + history/notification plumbing; live-bucket filtering is a follow-on once Q3 is ruled.
- The **notifications-pane** filter badge (legacy `#notifications-filter-badge`, the second indicator location) — secondary; wire only if the notifications-pane port surfaces a header slot. Primary indicator is the jobs-pane badge.
- **Server-side** filter logic — `queues.py` already enforces admin scoping (`is_admin()` checks at `:550/:608/:634/:1340/:1429`; `/api/get-queue` `user_filter` param at `:396`). No backend work.

The ratified ruling this executes: doc 04 §"Resolved" (g) — total 13/13 parity, no "obsolete" drops.

## 3. Source anchors

### Legacy reference behavior (read-only — mirror semantics, do NOT port verbatim)
- **HTML** `static/html/notifications.html`:
  - `#filter-settings-section` **L882-908** — `style="display:none"` (admin-gated, unhidden by JS); header `⚙️ Queue Filter Settings`; the 3 buttons `#filter-own-jobs` (L893, `.filter-button active`), `#filter-others-jobs` (L896), `#filter-all-jobs` (L899); `#filter-mode-display` (L904, "Your jobs only"). Testids `notifications-filter-own-btn` / `-others-btn` / `-all-btn`.
  - Toolbar entry **L55**: `.toolbar-btn[data-section="filter-settings-section"]` (⚙️, "Filter Settings (Admin)").
  - `#queues-filter-badge` **L913-915** — `.filter-mode-badge`, `style="display:none"`, testid `queues-filter-badge`, default text "👤 Mine" (the jobs-pane header badge — plan 04's render target).
- **JS** `static/js/notifications.js`:
  - Wiring **L1706-1735** — click listeners on the 3 buttons → `setFilterMode('own'|'others'|'all')`; badge click → `showAndScrollToFilterPanel()` (`stopPropagation` so it doesn't toggle the section).
  - `setFilterMode(mode)` **L6197-6261** — the core: `isAdmin` guard (L6216, non-admins warned + early-return); `this.queueFilterMode = mode`; `modeConfig` map (`own`→{👤,Mine,"Your jobs only"}, `others`→{🚫,Not Mine,"Other users' jobs"}, `all`→{👥,All Users,"All users' jobs"}, L6224-6228); toggles `.active` on the 3 buttons (L6233-6236); sets `#filter-mode-display` text (L6237); syncs **both** badges `#notifications-filter-badge` (L6240-6244) + `#queues-filter-badge` (L6247-6251) with `data-mode`; persists `localStorage[QUEUE_FILTER_PREF_KEY]` (L6254); then `refreshAllQueues()` + `clearSenderGroups()` + `loadConversationHistory()` (L6258-6260).
  - `showAndScrollToFilterPanel()` **L6263-6283**, `initializeFilterUI()` **L6285-6326** — admin → show panel + badges, load saved pref (validate against `['own','others','all']`, default `own`); non-admin → hide all, force `queueFilterMode='own'`.
  - **Admin source** **L668-669**: `this.userRoles = payload.roles || []; this.isAdmin = this.userRoles.includes('admin')` (also L1466-1467).
  - **`user_filter` call sites (LIVE buckets, OUT — see §2)**: `updateQueueLists` **L6131-6134** (`?user_filter=*` for `all`, `?user_filter=!self` for `others`), `:6459` (`*` for `all`).
  - **`exclude_own_jobs` call sites (notifications fetch, W5)**: senders-visible **L14284-14285**, bulk-delete **L15257-15258** — both `if (isAdmin && queueFilterMode === 'others') append('exclude_own_jobs','true')`.
  - Owner badge on cards in non-own modes **L7390** (`isAdmin && queueFilterMode !== 'own' && job.user_email`) — note for a later jobs-pane card enhancement; not in this plan's core.

### Server endpoints (all already mounted — `cosa/rest/routers/queues.py`)
- `GET /api/get-queue/{queue_name}` **L389-455** — `user_filter` Query param: `None`=self, `*`=all, `!self`/user_id=others; admin-gated server-side (`is_admin`, L412-455, `is_admin_view` at L550/608/634). *(Live-bucket path — OUT per §2/Q3; the mux does not call this today.)*
- `GET /api/job-history` **L1308-1362** — **auto-scopes** `user_id = None if is_admin else current_user["uid"]` (L1340). **No `user_filter`/`exclude_own_jobs` param today** → an admin always gets ALL users' history; a non-admin always gets own. So mode `own`/`others`/`all` cannot be expressed on history without a **new server param** — **open question Q4** (legacy had the same limitation: `loadJobHistory` sent no user filter).
- Notifications `senders-visible` + `bulk` — accept `exclude_own_jobs` (legacy W5 call sites). Confirm the mux's notifications port calls these before wiring.
- `jwt_service.create_access_token` `src/cosa/rest/jwt_service.py:39-72` — emits `roles` claim (`["user"]` default; `["user","admin"]` for admins, L72/219). This is the claim W2 reads.

### Mux targets (add / edit)
- `js/multiplexer/stores/ViewStateStore.ts` — **edit** (W1). Add `getFilterMode(): 'own'|'others'|'all'`, `setFilterMode(mode)` (persist via StorageService envelope, new `FILTER_MODE_KEY`/schema), and emit a **new** `store_filter_mode_changed` event (the store's current emission policy is silent-except-bulk — filter mode is the *second* legitimate emit; document it next to the existing policy comment L17-23). Default `own`.
- `js/multiplexer/shared/types.ts` — **edit** (W1/W4). Add `StoreFilterModeChangedPayload` + the `store_filter_mode_changed` event name to the EventBus union (a **convergence file** — manager-serial-merged, mandate 5).
- `js/multiplexer/auth/jwt.ts` — **edit** (W2). Extend `JwtClaims` with `roles?: string[]`; add `jwtRoles(token)` + `jwtIsAdmin(token)` (mirrors `jwtEmail` L66-70). Keep the existing "non-authoritative client hint" framing (L11-12).
- **New** `js/multiplexer/render/FilterSettingsRenderer.ts` — the 3-button switch + display text; admin-gated mount; writes `ViewStateStore.setFilterMode`. (W3.)
- `js/multiplexer/render/templates/` — **add** `filterSettings.ts` template (button group + `#filter-mode-display`, legacy class/testid parity: `.filter-button`, `notifications-filter-own/others/all-btn`).
- `html/multiplexer.html` — **edit** (W3/Q2). Either a new `<section id="filter-settings-pane">` (parity with the legacy dedicated section) **or** a slot inside `jobs-pane-header`. If a section: add a `SECTION_DEFS` entry (below).
- `js/multiplexer/render/templates/sectionToolbar.ts` — **edit** only if Q2 picks the dedicated-section approach: add a `{ sectionId:"filter-settings-pane", icon:"⚙️", title:"Filter Settings (Admin)", testid:… }` entry (`SECTION_DEFS` L36-41) **gated to admins** (new concern — the toolbar list is static today; needs an admin filter at render time).
- `js/multiplexer/render/JobsPaneRenderer.ts` — **read-coupling only** (W4): subscribes to `store_filter_mode_changed` to update the badge plan 04 renders. Plan 08 does **not** add the badge element (that's plan 04 W6).
- `js/multiplexer/api/ApiClient.ts` (or the notifications fetch path) — **edit** (W5): thread `exclude_own_jobs=true` when `isAdmin && mode==='others'` onto the senders/bulk fetches the mux carries.
- `css/multiplexer/` — **edit**: add `.filter-button`(+`.active`), `#filter-mode-display`/`.filter-controls`, and `.filter-mode-badge`/`.queues-filter-badge` rules. **Extend the single shared surface (`css/shared/notifications-surface.css` per mandate 3), never fork.** Cherry-pick legacy class names verbatim.

## 4. Dependencies & prerequisites

- **Plan 04 (Job Queues) — the badge seam, landed WITHOUT a circular block.** Plan 04 W6 renders `.queues-filter-badge` in the jobs-pane header as a *hidden default-Mine* element with a documented seam (`04-…md` §2/§4/§5-W6/Q1). Plan 08 owns the **store value + `store_filter_mode_changed` event** that drives it. **De-circularization rule**: the two plans meet at a **named contract** — (a) `ViewStateStore.getFilterMode()` accessor and (b) the `store_filter_mode_changed` event payload `{ mode, icon, label }`. Either plan may land first:
  - If **plan 04 lands first** (recommended per its own Q1): its W6 ships the hidden badge reading `getFilterMode()` defensively (store returns `own` until plan 08 wires switching); plan 08 then lights it up by enabling the switch + emitting the event. No code in plan 04 changes.
  - If **plan 08 lands first**: the store + switch + event exist; plan 04 W6 simply subscribes. The badge element doesn't exist yet, so plan 08's W4 subscriber must **null-guard** the badge node (no-op if absent) — guaranteeing plan 08 is independently shippable + 100%-coverable.
  - Net: **neither blocks the other**; the contract is the store accessor + event name, both defined here in §3. Document the contract in both plans (already cross-referenced).
- **Admin gating is client-UX-only; server is authoritative.** W2's `jwtIsAdmin` decodes the unverified JWT body purely to show/hide the switch + badge and to decide whether to *send* `user_filter`/`exclude_own_jobs`. The server independently enforces (`queues.py` `is_admin()` at every scope-widening site). A tampered client claim cannot widen scope server-side. **State this in the plan + a same-line code comment** (jwt.ts already warns its decode is non-authoritative, L11-12).
- **History fetch cannot express own/others/all today (Q4).** `/api/job-history` auto-scopes by admin with no param (`queues.py:1340`). So in the mux, switching `own↔others↔all` has **no effect on the history bucket** unless a server param is added — exactly the legacy limitation (legacy `loadJobHistory` sent no user filter). W5 therefore plumbs `exclude_own_jobs` only onto the **notifications** paths that already accept it; the history-scope widening is deferred to Q4's ruling.
- **Live buckets are WS-push, not fetched (Q3 — central).** See §2 OUT. This is the single biggest divergence from legacy and the main thing reviewers must rule on before `others`/`all` is *fully* faithful for live jobs.
- **StorageService envelope** — reuse the existing schema-versioned envelope pattern (`ViewStateStore` L29-34, `setJSON`/`getJSON`); add one `FILTER_MODE_KEY` envelope. Corrupt/absent → default `own` (same defensive coercion as the existing maps L156-168).
- **No INI keys. No new endpoints. No new router** → the §DOCUMENTATION TOUCHPOINTS "new router"/"routers/*.py" rows do NOT fire. Doc updates limited to this rnd folder's #8 tracker.

## 5. Work breakdown

Each task: **what · files · ACs (functional + structural) · Oracle tier(s)**.

### W1 — Filter-mode store + event
- **What**: Extend `ViewStateStore` with `getFilterMode()/setFilterMode(mode)` persisted via a new StorageService envelope; emit `store_filter_mode_changed{ mode, icon, label }` on change (the second legitimate, documented emit). Add the event + payload to `shared/types.ts`.
- **Files**: `ViewStateStore.ts`, `shared/types.ts` (convergence), unit specs.
- **ACs (functional)**: `setFilterMode('all')` persists + emits once; reload replays the persisted mode; an invalid persisted value → coerced to `own`; default (no persisted value) → `own`. The `modeConfig` (icon/label/displayText) matches legacy L6224-6228 exactly.
- **ACs (structural)**: one new `FILTER_MODE_KEY` envelope (schema v1); emit payload carries `mode` + the legacy icon/label; emission-policy comment updated to name filter-mode as the second emit.
- **Oracle**: n/a (pure logic) — gated by unit coverage only.

### W2 — Admin signal in the mux JWT
- **What**: Extend `JwtClaims` with `roles?: string[]`; add `jwtRoles(token)` + `jwtIsAdmin(token)` (`roles.includes('admin')`, legacy parity). Non-authoritative; UX-only.
- **Files**: `auth/jwt.ts`, unit spec.
- **ACs (functional)**: token with `roles:["user","admin"]` → `jwtIsAdmin` true; `roles:["user"]` or missing `roles` → false; malformed token → false (mirrors `jwtEmail` null-paths).
- **ACs (structural)**: same-line comment reaffirming server is the real gate; no new network call (decode-only).
- **Oracle**: n/a (logic) — unit only.

### W3 — Admin-gated 3-button switch UI
- **What**: `FilterSettingsRenderer` + `filterSettings.ts` template: the 3 buttons (own/others/all) with `.active` reflecting `getFilterMode()`, the "Currently viewing: <strong id=filter-mode-display>" text, click → `setFilterMode`. Mount admin-gated (hidden/absent for non-admins). Placement per Q2.
- **Files**: `FilterSettingsRenderer.ts` (new), `templates/filterSettings.ts` (new), `multiplexer.html`, `sectionToolbar.ts` (iff dedicated-section), `boot.ts` (mount), CSS.
- **ACs (functional)**: admin sees 3 buttons + display text; clicking a button toggles `.active` to that button only + updates display text + drives the store; non-admin → renderer mounts nothing (or `display:none`) and mode is forced `own`. Default active = `own`.
- **ACs (structural)**: testids `notifications-filter-own/others/all-btn` + classes `.filter-button` preserved (legacy parity); exactly one `.active` at a time; `#filter-mode-display` present.
- **Oracle**: **T0** CSS-hash on `.filter-button`/`.active`/`.filter-controls`; **T1** DOM-contract (3 buttons + display, present iff admin); **T2** computed-style (active-button styling); **T3** geometry (button-row layout) vs the legacy `#filter-settings-section` capture.

### W4 — Jobs-pane filter badge wiring (plan-04 seam)
- **What**: Subscribe (in `JobsPaneRenderer` or a thin badge-sync) to `store_filter_mode_changed`; update the `.queues-filter-badge` plan 04 renders (text=`icon label`, `data-mode`, visibility=admin-&-mounted). **Null-guard** the badge node so plan 08 is shippable before plan 04 lands.
- **Files**: `JobsPaneRenderer.ts` (subscribe), CSS (`.filter-mode-badge`/`.queues-filter-badge`).
- **ACs (functional)**: when admin switches mode, the badge text/`data-mode` update (👤 Mine / 🚫 Not Mine / 👥 All Users); badge hidden for non-admins / mode `own` per legacy default; badge absent (plan 04 not yet landed) → subscriber no-ops without error.
- **ACs (structural)**: no badge **element** authored here (plan 04 owns it); subscriber tolerates a missing node (`if (!badge) return;`).
- **Oracle**: **T1** (badge text/`data-mode` per mode), **T0** (`.filter-mode-badge` styling) — coordinated with plan 04 W6's T2/T3.

### W5 — `exclude_own_jobs` plumbing (notifications paths)
- **What**: On the mux's notifications senders-visible + bulk-delete fetches, append `exclude_own_jobs=true` when `isAdmin && getFilterMode()==='others'` (legacy L14284/L15257). History scope-widening deferred (Q4); live buckets deferred (Q3).
- **Files**: `api/ApiClient.ts` or the notifications fetch site, unit spec.
- **ACs (functional)**: `others` + admin → param appended; `own`/`all` or non-admin → omitted; matches legacy guard exactly.
- **ACs (structural)**: param only on the paths that legacy gated it on; no `user_filter` on history (none exists server-side).
- **Oracle**: n/a (network logic) — unit only.

## 6. Test strategy & venue routing

Inherits venue rubric from index mandate 4. This plan is **TS/CSS-only**; no server mutation in the unit layer (stubbed StorageService / EventBus / fetch).

- **Unit (`:7999`, AI-discretionary)** — new/extended specs: `view_state_store.test.ts` (W1: persist/replay/coerce/emit-once), `jwt.test.ts` (W2: admin/non-admin/malformed), `filter_settings_renderer.test.ts` (W3: admin gate, active-toggle, display text, store write), `jobs_pane_renderer.test.ts` (W4: badge sync + missing-node null-guard), notifications-fetch spec (W5: param-on-others-admin only). Mock `confirm`/`fetch`/storage. **100% L/B/F** (`c8 --100`); every branch tested or `c8 ignore` + same-line reason (mandate 1).
- **WebSocket smoke (`:7999`)** — none required (no new WS event consumed; `store_filter_mode_changed` is an in-process EventBus signal, not a WS frame). Note explicitly so reviewers don't expect a WS scenario.
- **E2E UI + visual (`:8000`, scheduled via `POST /api/test-suite/submit`)** — Playwright as **admin** and as **regular** user (two fixtures): admin sees + operates the switch, badge tracks, regular user sees neither. Visual-regression snapshots for the switch + badge (rebaseline — §7). Self-authorized on a verified-idle `:8000` per index mandate 4 / CLAUDE.local.md.
- **Integration (`:8000`, FINAL gate)** — only if W5 surfaces a real `exclude_own_jobs` fetch against the live notifications endpoint (mutates nothing on senders-visible; bulk-delete does mutate → :8000 only). Add to `run-integration-tests.sh` if not covered.

100%-coverage statement: **lines AND branches AND functions = 100%** on all touched TS via `c8 --100`; no "≥95%".

## 7. Oracle & visual parity

Tiers exercised: **T0** (CSS-hash on cherry-picked legacy classes — `.filter-button`/`.active`, `.filter-controls`, `#filter-mode-display`, `.filter-mode-badge`/`.queues-filter-badge`), **T1** (DOM-contract: 3 buttons + display present iff admin; badge text/`data-mode` per mode), **T2** (computed-style on the active button + badge), **T3** (geometry: the 3-button row + display block, and the jobs-pane header with the badge), **T4** pixel backstop only on the switch panel (densest new layout). Methodology per `2026.06.19-…/01-layout-parity-methodology.md`.

**New golden captures needed** (legacy `:8000` capture cost): the legacy `#filter-settings-section` panel (3 buttons + "Currently viewing") in admin mode, and the `#queues-filter-badge` in each of the three states. Rebaseline mux snapshots for the switch + jobs-pane header after W3/W4 land. **Coordinate the jobs-pane-header capture with plan 04** (shared header region — avoid double-rebaselining).

## 8. Risks & open questions (for reviewers)

- **Q1 (store home)**: extend `ViewStateStore` (recommended — filter mode is a view preference; reuses its StorageService envelope + emit machinery) **or** a dedicated `FilterModeStore`? Trade-off: ViewStateStore's deliberate silent-except-bulk emission policy gets a second exception; a dedicated store keeps that policy pure. Recommend extending ViewStateStore.
- **Q2 (switch placement)**: a dedicated `filter-settings-pane` **section** + an admin-gated `sectionToolbar` entry (closest legacy parity — legacy had its own collapsible section + ⚙️ toolbar button) **or** fold the 3-button row into the `jobs-pane-header` (fewer moving parts, but diverges from the legacy "separate section" structure)? The dedicated section also forces a **new concern**: admin-gating the static `SECTION_DEFS` list. Recommend the dedicated section for parity; flag the toolbar-gating work.
- **Q3 (live-bucket filtering — CENTRAL)**: the mux live buckets are WS-push (user-centric routing), not polled. Legacy `others`/`all` re-fetched `/api/get-queue?user_filter=…`. To make `others`/`all` faithful for *live* jobs the mux needs either (a) a server-side WS-scope widening for admins, or (b) a fetch-refresh fallback path that calls `/api/get-queue/{q}?user_filter=…` and merges into `JobStore`. **Reviewers must rule** before live-bucket filtering can land. This plan scopes mode + history/notification plumbing + badge; live-bucket filtering is a tracked follow-on.
- **Q4 (history scope)**: `/api/job-history` has no own/others/all param (auto-scopes by admin). Matching the legacy limitation, history is unaffected by mode today. Add a server `user_filter`/`exclude_own_jobs` param to `/api/job-history` (small backend change, would graduate this out of "no backend work"), or accept the legacy limitation? Recommend documenting the limitation now; defer the server param.
- **Risk — non-authoritative admin claim**: the client decodes an unverified JWT body to gate UI + decide whether to *send* widening params. Acceptable because the server independently enforces (`queues.py is_admin()`); a forged client claim cannot widen server-side scope. Must be stated in code + plan.
- **Risk — badge double-ownership with plan 04**: plan 04 renders the badge element, plan 08 drives its content. Mitigated by the §4 named contract (store accessor + event) + W4's null-guard so order-of-landing is free.

## 9. Lane decomposition & estimate

This is a **small, mostly-self-contained** plan. The work splits cleanly into a **store/auth foundation lane** and a **UI lane**, with one convergence file:

1. **Foundation lane** — W1 (`ViewStateStore` + `shared/types.ts`) + W2 (`jwt.ts`). Unblocks everything; `shared/types.ts` is a **convergence file** (EventBus union) → **manager-serial-merged** (mandate 5).
2. **UI lane** — W3 (renderer + template + html + CSS) + W4 (badge subscribe) + W5 (fetch param). Depends on the foundation lane's store accessor + event.

W4 is the **only** cross-plan touchpoint (plan 04). Land per the §4 de-circularization rule — neither plan blocks the other (named contract + null-guard).

**Rough size**: ~120-180 LOC TS (store extension + jwt + renderer + template + subscribers) + ~40-70 LOC CSS + ~200-300 LOC tests for 100% L/B/F. Net **low-to-medium** — the audit's "low–moderate" estimate holds; the heaviest *thinking* is Q2/Q3, not the code.

**In-flight-crew coordination** (mandate 6): the only overlap is **plan 04** (jobs-pane header / `shared/types.ts` EventBus union). No direct conflict with Tiberius full-parity (`704c71b2`), Rachel's section-toolbar branch (`mux-section-toolbar-accordion-toggle` — but **note**: Q2's dedicated-section approach edits `sectionToolbar.ts`, which Rachel's branch owns — coordinate if Q2 picks that path), or plan 01's `4b33ceb7`. Flag the `sectionToolbar.ts` overlap as the one merge-coordination item if Q2 → dedicated section.

**Doc touchpoints** (mandate 7): update this rnd folder's #8 discrepancy tracker on completion. No INI, no websocket-events, no notification-api, no rest-api-reference changes (no new/changed endpoint — unless Q4's server param is taken, which would add a `/api/job-history` row).
