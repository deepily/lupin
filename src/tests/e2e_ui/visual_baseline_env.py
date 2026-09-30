"""
Render-environment constants the visual baselines were captured against.

Lives in its own module so the capture harness (`conftest.py`) and the guard
(`test_visual_timezone_pin.py`) read ONE value rather than two copies that can
drift. It cannot live in `conftest.py` itself: a test module's plain
`import conftest` resolves to the repo-wide `src/conftest.py`, not this
package's, so the constant would be unreachable from the guard.

Requires:
    - nothing; pure data, no imports
Ensures:
    - exports the IANA zone every e2e_ui browser context is pinned to
"""

# The IANA zone every e2e_ui browser context is pinned to (row f0e00f01).
#
# CONTAINER-CANONICAL: `docker/lupin/Dockerfile` sets `ENV TZ=UTC`, and the :8000
# merge gate runs `run-e2e-ui-tests.sh` as a `TestSuiteJob` subprocess INSIDE
# `lupin-rest-test`, so the git-tracked snapshots are UTC renders. Pinning to UTC
# leaves the gate byte-identical and brings HOST-side runs (the dev box is EDT)
# into line with it. This is the same Option-2 container-canonical resolution the
# font/FreeType fingerprint guard records in `test_render_env_fingerprint.py`.
#
# Changing this value invalidates every timestamp-bearing snapshot — rebaseline
# with `--update-snapshots` in the same commit if you ever do.
VISUAL_BASELINE_TIMEZONE = "America/New_York"

# ✅ MOVED 2026-09-18 — UTC → America/New_York (Mr. Radio, row 6e2b1f7e; Rick approved the
# rebaseline pass on f0e00f01 the same evening). Since 4f445965 both clients format through
# `appTimezone` = the INI's `app timezone`, so the product HAS an effective zone and this pin
# now matches it. The clock-bearing baselines were re-captured in the same pass: that churn
# IS the fix landing, not the suite breaking. The two status notes below are history.

# 🔴 STATUS 2026-09-17 — ROW 0e5bfa0e IS FIXED (commit 4f445965), SO THE REVISIT CONDITION AT
# THE BOTTOM OF THIS NOTE HAS TRIGGERED. `appTimezone` now threads through both clients: the
# payload emits `app_timezone` (underscore) and the multiplexer takes the zone through
# `NotificationsListRenderer.setAppTimezone`, called from boot's own /api/config/client fetch.
# So the product HAS an effective zone now — America/New_York — and this pin's UTC no longer
# matches it. Moving the pin and rebaselining is Mr. Radio's call and was deliberately NOT
# done with that commit. The paragraph below is kept verbatim because it is why the pin
# exists; it describes 2026-09-15, not HEAD.
#
# WHY THIS DID NOT MATCH `app timezone = America/New_York` IN lupin-app.ini, and why that
# was not a "stable but unrepresentative" baseline (reviewer's question via Tiffany, 2026-09-15):
# because that INI value reaches NO formatter, so the product has no effective zone at the
# render path to be unrepresentative OF. Measured 2026-09-15 — the multiplexer never threads
# `appTimezone` (boot.ts), and the legacy client reads `config.app_timezone` while the server
# emits `"app timezone"`, so both paths fall back to the BROWSER's zone. What the product
# actually renders today is whatever zone the viewer's machine keeps; UTC is simply what the
# container-captured PNGs in git contain. Pinning America/New_York instead would invalidate
# every timestamp baseline and STILL not match the product.
#
# ⇒ REVISIT THIS when bug row 0e5bfa0e is fixed. Once `appTimezone` genuinely threads through,
# the product WILL have an effective zone, and matching it here becomes the right call — with
# a rebaseline in the same commit.
