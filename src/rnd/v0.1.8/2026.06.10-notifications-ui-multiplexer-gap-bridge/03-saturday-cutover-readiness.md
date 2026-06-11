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
| 4 | E2E migration (~12 JS suites gain `test_multiplexer_*` counterparts) | ✅ **6 of 7 BUILT 2026-06-11 evening** (Rick's tonight ruling) | New suites (22 tests, all `:7999` pre-flight green first-run, element-anchored): `test_multiplexer_auth_bounce` (WP0, 3) · `test_multiplexer_session_strip` (WP2, 5) · `test_multiplexer_reap_badge_drop` (WP7, 4) · `test_multiplexer_spinup_symmetry` (WP8, 3) · `test_multiplexer_manager_badge` (WP9, 4) · `test_multiplexer_commons_activity_toggle` (WP3/11, 3). Held commits `3aaf740b`/`0e11cfbe`/`74ad168b`. Consolidated `:8000` run `ts-2c5e5deb` (all 15 `test_multiplexer_*` suites): **64 passed, 0 failed, 0 errors, 1 skipped** (the skip is pre-existing: `test_multiplexer_prediction_vote.py::test_vote_controls_dom_render_and_gate`, Lane E's surface, in-flight Stage-3 vote work). **WP6 carve-out: see finding below — Tiberius ruled PORT-before-Saturday (Rick override window open).** |
| 5 | Docs (notification-api, rest-api-reference Pages, websocket-events, CLAUDE.md touchpoints → multiplexer canonical) | 🔴 **NOT DONE — GO-day ride-along** | Deliberately deferred: the content asserts post-cutover state ("canonical", "deprecated") that is false until the flip. Files enumerated; ~30 min of edits Saturday. |
| 6 | Build/cache-bust (`npm run build`, verify hash, bump `?v=`) | ✅ **Current** / 🟡 note | `dist/multiplexer/manifest.json` hash `4c444ae676b8` built 2026-06-10T17:35Z; dist clean in git; no mux source changes since. Note: `multiplexer.html:237` loads **unhashed** `boot.js` with **no `?v=` param** — HTML is no-cache and static files carry ETag revalidation, so risk is low, but row 6's "bump ?v=" has nothing to bump; consider adding one at flip or switching the script tag to the hashed filename. |
| 7 | Coverage gate (100% L/B/F after every WP) | ✅ **Holding** | Mux c8 100% at merge-train (1108/1108); this session's `pages.py` at 100% L+B. |
| 8 | Decommission (delete notifications.js/.html/.css + dist history) | ⛔ **RETIRED by Rick's D2 ruling (2026-06-11)** | **Cutover ≠ deletion.** The entire JS client, its E2E test suites, and the `?classic=1` escape hatch are preserved **LONG-TERM as a research corpus** (JS-vs-TS code-quality comparison study, methodology TBD). The JS client is retired from default duty only. Row 4's "until the redirect soaks" deletion framing is superseded — the suites are permanent corpus artifacts. |

## Decision items for Rick — RULED 2026-06-11 evening (live walkthrough via Tiberius)

1. **The GO itself** — still open; flip Saturday per procedure above (Rick's standing gate).
2. **`?classic=1` escape hatch — RATIFIED + elevated (D2 ruling).** Not merely kept for the soak:
   the hatch, the **entire JS client**, and its test suites are preserved **long-term as a
   research corpus** for a JS-vs-TS code-quality comparison study (methodology TBD).
   **Cutover ≠ deletion** — the JS client is retired from default duty only.
3. **The 7 missing `test_multiplexer_*` counterparts — build TONIGHT (2026-06-11), before
   Saturday** (Rick rejected the fast-follow option). Owner: Clayton 😎. Quality bar: assertions
   anchored on the element-level surface each test actually exercises (computed state/handler
   effects — not bare DOM presence, the false-pass lesson). Held commits, fresh-critical review
   per batch, `:8000` runs queued behind pending work.

## FINDING (2026-06-11 evening): WP6 insert-at-caret is a FEATURE gap, not a test gap

Discovered while building the WP6 counterpart: **the insert-at-caret feature was never ported to
the multiplexer.** No `insertTranscriptionText`/caret/`selectionStart` logic exists anywhere in
the mux TS tree, and no WP6 commit exists in history. (This also corrects this report's earlier
"all 7 have 100% c8 unit coverage" claim — true for the other six, **not** for WP6.)

What the multiplexer does instead: `SenderCardRecorderRenderer` paints the transcription into a
**fresh textarea** on `ready_to_send` (`textarea.value = entry.transcription ?? ""`). For the
plain record→review→send flow that is arguably fine — there is no pre-existing user text to
preserve. The regression risk is **Re-record after editing**: the user edits the transcription,
clicks Re-record, and the new transcription **overwrites their edits** — exactly the legacy
overwrite bug (2026-06-01, Rick) that F5's insert-at-caret was created to fix.

**Decision needed (Tiberius/Rick):** (a) accept replace-on-re-record as intended mux design and
write the E2E against that contract, or (b) port the caret-splice into the mux textarea path as
a feature task (+ unit + E2E). No counterpart suite was faked against the wrong contract.

## Residual risk

- **Flag-ON path has no live E2E** — it cannot be E2E-tested without flipping the shared INI
  (both servers read the same file), which is the gated action itself. Mitigation: the
  HTTP-layer unit test exercises the real router + 302 + Location through TestClient; flip-day
  verification is a 30-second probe (`/app/notifications` → 302; `?classic=1` → 200).
- ~~**`:8000` receipts pending**~~ **RESOLVED 2026-06-11 PM:** `ts-5e0f61c0` (10:38 EDT) and
  `ts-5a32ef03` (10:41 EDT) both **ALL PASSED — 11/11, 0 failed/errors/skipped** (reports:
  `test-suite/2026.06.11-at-10:38-EDT-e2e-results.md`, `…10:41…`). The runs collected the
  patched working-tree test files, so the `?classic=1` navigation patch is E2E-proven inert.
- **WP12 color parity confirmed** (Tiberius relay 06-11): the multiplexer fleet panel already
  mirrors the final legacy color scheme (Lane E follow-on `8e9488a9` — exact palette + classes
  in `fleet-status.css`). Not a gap.
