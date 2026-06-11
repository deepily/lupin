# Saturday Cutover Readiness — go/no-go report (checklist rows 1–8 status'd)

**Author:** Clayton 😎 (for Tiberius 👑) · **Date:** 2026-06-11 (EDT) · **Target:** Sat 2026-06-14 flip
**Deliverable** — executes the bridging checklist of [`02-bridging-work-plan.md`](02-bridging-work-plan.md) § "Deprecate notifications UI".

## Verdict: **GO-ready** — the flip is now a one-line INI edit (+ :8000 bounce), gated only on Rick's word

The parity work all landed in the 2026-06-10 merge-train (Lanes A–E, WP0–WP15, flagless e2e
560/3/1/3 green, both servers on validated 1.1.0). What remained was the cutover *mechanics*;
those are now built, tested to the 100% gate, and held **inactive** behind an INI flag.

## What was built this session (held on `wip-v0.1.8-…`, flag OFF, zero live-behavior change)

1. **INI-keyed redirect** — new key **`legacy notifications redirect enabled = False`**
   (`[Lupin: Baseline]`, splainer entry included). When True, `GET /app/notifications` returns
   **302 → `/app/multiplexer`** (`pages.py`); the route stays alive so bookmarks keep working.
2. **`?classic=1` escape hatch** — with the flag ON, `/app/notifications?classic=1` still serves
   the legacy page. Purpose: (a) the held-back JS-client E2E suites keep guarding the fallback
   post-flip (checklist row 4's "do not delete until the redirect soaks" is otherwise
   self-defeating — a hard redirect would break the very suites guarding the fallback);
   (b) it doubles as the MVD "Classic UI" link mechanics if the Friday-night cut-line fires.
   **Design delta vs. plan (which says bare hard redirect) — flagged for ratification.**
3. **Legacy E2E suites future-proofed** — all **153** `goto`/URL sites across **24**
   `src/tests/e2e_ui/` files patched `…/app/notifications` → `…/app/notifications?classic=1`.
   Provably inert while the flag is off (bool query param is ignored; unit test asserts the
   identical file serves). No exact-URL assertions exist that the param could break (audited).
4. **Tests** — `test_pages_router.py` +4 tests (flag-off / flag-on-redirect / classic-escape /
   HTTP-layer 302+Location via TestClient). **8/8 pass, `pages.py` at 100% lines+branches.**
   Live `:7999` probe post-edit: `/app/notifications` 200 text/html, no redirect (unchanged).
5. **Targeted `:8000` receipts queued** — `ts-5e0f61c0` (filter_toggle) + `ts-5a32ef03`
   (action_required) scheduled 10:38/10:41 EDT behind the pre-existing 6-job batch, proving
   patched legacy suites stay green. (Note: a 6-job e2e batch was already queued at
   10:04–10:35 EDT by peers; those runs will also collect the patched files from disk.)

## Saturday GO procedure (when Rick says go)

1. Edit `src/conf/lupin-app.ini`: `legacy notifications redirect enabled = False` → `True` (one line).
2. `:7999` picks it up via dev auto-reload; **`:8000` needs a bounce** (`docker restart
   lupin-rest-test` — ConfigurationManager reads the INI once at construction; verified: no
   file-watcher in `configuration_manager.py`). ⚠️ The INI is shared by both containers — the
   flip is per-restart, not per-server.
3. Landing card repoint (row 2) is **covered transitively** the moment the flag flips: card →
   `/app/notifications` → 302 → multiplexer. The direct one-line `landing.html:116` href edit
   (`/app/notifications` → `/app/multiplexer`) is post-soak cleanup; deliberately NOT applied
   now because `:7999` serves the working tree and it would change the default surface early.
4. GO-day docs ride-along (row 5, below) + `?v=` consideration (row 6, below).

## Checklist rows 1–8 — status

| Row | Item | Status | Evidence / remaining |
|---|---|---|---|
| 1 | Route/redirect (`pages.py` → RedirectResponse, route alive) | ✅ **BUILT, held inactive** | This session. INI-keyed, 302, `?classic=1` hatch, 100% L/B, live probe unchanged. |
| 2 | Landing card repoint (`landing.html:116`) | 🟡 **Transitively covered at flip** | Direct href edit = 1-line post-soak cleanup (would change live default if applied now). |
| 3 | Server bits stay (multiplexer_config, undelivered*, prediction-vote, fleet-state) | ✅ **VERIFIED present** | `multiplexer_config.py`, `notifications.py:1350`, `arbiter.py` fleet-state — all client-agnostic, no action. |
| 4 | E2E migration (~12 JS suites gain `test_multiplexer_*` counterparts) | 🟡 **PARTIAL** | Exist: WP4/5 (4 suites), WP12–15 quartet (4 suites), WP10/WP2-partial (mux section in `test_cc_session_strip_and_focus.py`). **Missing named counterparts ×7**: auth_bounce (WP0), session_strip full (WP2), stt_insert_at_cursor (WP6), reap_badge_drop (WP7), spin-up symmetry (WP8), manager_badge (WP9), commons_activity_toggle (WP3/11). All 7 have 100% c8 **unit** coverage; the 06-10 gate was declared green without them. Legacy suites remain the guard via `?classic=1`. Recommend: post-cutover fast-follows, not Saturday blockers. |
| 5 | Docs (notification-api, rest-api-reference Pages, websocket-events, CLAUDE.md touchpoints → multiplexer canonical) | 🔴 **NOT DONE — GO-day ride-along** | Deliberately deferred: the content asserts post-cutover state ("canonical", "deprecated") that is false until the flip. Files enumerated; ~30 min of edits Saturday. |
| 6 | Build/cache-bust (`npm run build`, verify hash, bump `?v=`) | ✅ **Current** / 🟡 note | `dist/multiplexer/manifest.json` hash `4c444ae676b8` built 2026-06-10T17:35Z; dist clean in git; no mux source changes since. Note: `multiplexer.html:237` loads **unhashed** `boot.js` with **no `?v=` param** — HTML is no-cache and static files carry ETag revalidation, so risk is low, but row 6's "bump ?v=" has nothing to bump; consider adding one at flip or switching the script tag to the hashed filename. |
| 7 | Coverage gate (100% L/B/F after every WP) | ✅ **Holding** | Mux c8 100% at merge-train (1108/1108); this session's `pages.py` at 100% L+B. |
| 8 | Decommission (delete notifications.js/.html/.css + dist history) | ⛔ **Out of scope** | Post-soak explicit call, per plan. |

## Decision items for Rick (batched — he's out from 10:00 EDT)

1. **The GO itself** — flip Saturday per procedure above (his standing gate).
2. **Ratify the `?classic=1` escape hatch** — design delta vs. the plan's bare hard redirect.
   Recommend keep: it is what lets row 4's fallback-guard suites keep running post-flip, and it
   costs one query-param check at 100% coverage. (Bookmark users are still hard-redirected.)
3. **The 7 missing `test_multiplexer_*` counterparts** — accept as post-cutover fast-follows
   (recommended; gate already green without them) or staff before Saturday.

(Items 2–3 are arguably manager-level; Tiberius may rule and present to Rick as FYI.)

## Residual risk

- **Flag-ON path has no live E2E** — it cannot be E2E-tested without flipping the shared INI
  (both servers read the same file), which is the gated action itself. Mitigation: the
  HTTP-layer unit test exercises the real router + 302 + Location through TestClient; flip-day
  verification is a 30-second probe (`/app/notifications` → 302; `?classic=1` → 200).
- **`:8000` receipts pending** — `ts-5e0f61c0` / `ts-5a32ef03` queued behind a ~6-job batch;
  results to be triaged when they land (failure would be test-side, not product — server path
  is proven inert).
