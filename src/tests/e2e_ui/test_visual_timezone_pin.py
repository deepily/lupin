"""
Timezone-pin guard for the visual regression suite (row f0e00f01).

🔴 STATUS 2026-09-17 — THE TWO BREAKS DESCRIBED BELOW ARE FIXED (row 0e5bfa0e,
commit 4f445965, María 🌸). The server payload now emits `app_timezone` with an
underscore, and the multiplexer takes the zone through
`NotificationsListRenderer.setAppTimezone`, called from boot's own
/api/config/client fetch — a setter and not a constructor option, because boot is
synchronous and that fetch is not, so the zone always arrives after the renderer
exists. Both render paths therefore DO have an effective zone now.

⇒ The pin below is still UTC and now differs from what the product renders
(America/New_York). Moving it and rebaselining is Mr. Radio's call and was
deliberately not done with that commit. Everything from here down is preserved as
the 2026-09-15 measurement that justified the pin; read it as history, not as a
description of HEAD.

WHAT DECIDED THE TIMEZONE A LUPIN TIMESTAMP RENDERED IN — measured 2026-09-15 by
reading the program, not a corpus of its outputs:

  1. MULTIPLEXER (TypeScript) path. `formatHM` / `formatDateKey` in
     `multiplexer/render/time.ts` take an OPTIONAL `appTimezone`; when it is
     undefined or empty they fall to `date.getHours()` / `date.getFullYear()`,
     i.e. the BROWSER's local zone. `NotificationsListRenderer` reads that value
     from its constructor options only, and `multiplexer/boot.ts`'s
     `createNotificationsListRenderer({...})` call does NOT pass `appTimezone`.
     There is therefore NO wire at all from config to this path: it is
     browser-local by construction.

  2. LEGACY `notifications.js` path. A wire exists but does not carry. The server
     returns the key spelled with a SPACE — `system.py`'s `get_client_config`
     emits `"app timezone"` — while the client reads `config.app_timezone` with an
     UNDERSCORE, so `this.appTimezone` is `undefined` on every successful fetch.
     Verified live against :7999 on 2026-09-15: `GET /api/config/client` returned
     exactly one timezone-ish key, `'app timezone' = 'America/New_York'`, and
     `config.app_timezone` was absent. The `getDateString` / `getLocalTimeDisplay`
     family then pass `timeZone: undefined` into `Intl.DateTimeFormat`, which per
     spec falls back to the runtime's default zone — browser-local again.

⇒ Both render paths follow the BROWSER's zone, so the fix has to be made where
the browser is created. Setting `app timezone` in `[Lupin: Development]` and
`[Lupin: Testing]` would change NOTHING on either path — the key is already
served (the server's own `default=` supplies "America/New_York" whether or not a
section sets it) and still never reaches a formatter. That is why the pin lives
in `conftest.py`'s `browser_context_args` and not in the INI.

The two wiring defects above are REAL and are NOT fixed here — fixing either one
changes production rendering for every user and is a separate ruling. They are
named here so the next reader does not "fix" the pin by repairing the INI.

VENUE DELTA that made this bite — measured 2026-09-15 19:31-19:39 EDT: the host
dev box runs EDT while `docker/lupin/Dockerfile` sets `ENV TZ=UTC`, so
`lupin-rest-test` and `lupin-rest-dev` both run UTC. A host Chromium context with
no pin resolved to `America/New_York` and rendered a fixed epoch as `20:00`; the
same epoch in a UTC context rendered `00:00`.

WHAT THIS FILE GUARDS:

  `test_context_args_pin_the_baseline_timezone` is the DELETION DETECTOR. It asks
  the fixture for the dict Playwright actually consumes and fails if the pin is
  missing or is not the baseline zone. It reddens on EVERY venue, including a UTC
  container, which is the point: an effective-behaviour check alone would pass in
  the container with the pin deleted and catch nothing.

  `test_pinned_context_resolves_to_the_baseline_timezone` is the EFFECTIVENESS
  check. It builds a real context from those same args and asks the browser what
  zone it resolved, so a pin that is present but inert (renamed arg, unsupported
  value) still fails.

Requires:
    - the `browser_context_args` session fixture from this package's conftest
    - a Playwright `browser` (the effectiveness test only); no server needed
Ensures:
    - deleting `timezone_id` from `browser_context_args` reddens a named test in
      any venue, EDT host or UTC container
"""

import os

from visual_baseline_env import VISUAL_BASELINE_TIMEZONE


# A zone deliberately DIFFERENT from the baseline zone, forced as the AMBIENT `TZ` of the
# control browser the effectiveness test launches. Chromium reads `TZ` from its process
# environment, so an UNPINNED context inside that browser reports this zone while a pinned
# one reports the baseline. That is what lets the effectiveness test discriminate in a UTC
# container, where the ambient zone and the baseline zone would otherwise be the same value
# and the probe would be blind. Any IANA zone that is not the baseline works; Asia/Tokyo is
# chosen for being unambiguously neither UTC nor the host's Eastern.
CONTROL_AMBIENT_TIMEZONE = "Asia/Tokyo"

# The baseline zone written as an INDEPENDENT LITERAL, deliberately not re-derived from
# `VISUAL_BASELINE_TIMEZONE`. Without it this guard is a tautology: `conftest.py` sets
# `"timezone_id": VISUAL_BASELINE_TIMEZONE`, so comparing the fixture's value against that
# same constant traces BOTH sides back to one origin and agrees no matter what the origin
# says. Measured 2026-09-15: editing the constant from "UTC" to "America/New_York" — a change
# that invalidates every timestamp-bearing snapshot in the repo — left both tests passing.
# Pinning one side to a literal is what makes a zone CHANGE reddenable, not just a deletion.
#
# So changing the baseline zone now takes three deliberate edits: the constant, this literal,
# and a `--update-snapshots` rebaseline in the same commit. That is the intended cost.
EXPECTED_BASELINE_TIMEZONE = "UTC"

assert CONTROL_AMBIENT_TIMEZONE != EXPECTED_BASELINE_TIMEZONE  # a blind control is no control

# What the browser itself says its zone resolved to — the render path's own view, not ours.
_RESOLVED_TIMEZONE_JS = "() => Intl.DateTimeFormat().resolvedOptions().timeZone"


def test_context_args_pin_the_baseline_timezone( browser_context_args ):
    """
    The context args Playwright consumes must carry the baseline timezone pin.

    DELETION DETECTOR — venue-independent. This reads the very dict handed to
    `browser.new_context()`, so it is asking the gate rather than restating its
    rule; it cannot drift from what the fixture actually returns.
    """
    assert VISUAL_BASELINE_TIMEZONE == EXPECTED_BASELINE_TIMEZONE, (
        f"The baseline zone constant moved: visual_baseline_env.VISUAL_BASELINE_TIMEZONE is "
        f"'{VISUAL_BASELINE_TIMEZONE}' but this guard's independent literal says "
        f"'{EXPECTED_BASELINE_TIMEZONE}'. Changing the zone invalidates EVERY timestamp-bearing "
        f"snapshot, so it is deliberately not a one-line edit. If the change is intended, update "
        f"EXPECTED_BASELINE_TIMEZONE here and rebaseline with --update-snapshots in the SAME "
        f"commit; if it is not, revert the constant."
    )
    assert "timezone_id" in browser_context_args, (
        "Visual-baseline timezone pin is MISSING from browser_context_args. Lupin's "
        "timestamp formatters follow the BROWSER's local zone (multiplexer boot.ts "
        "never passes appTimezone; the legacy client reads config.app_timezone while "
        "the server emits 'app timezone'), so an unpinned context renders every HH:MM "
        "in whatever zone the machine running Chromium sits in — EDT on the host, UTC "
        "in the container. Restore \"timezone_id\": VISUAL_BASELINE_TIMEZONE in "
        "src/tests/e2e_ui/conftest.py."
    )
    assert browser_context_args[ "timezone_id" ] == EXPECTED_BASELINE_TIMEZONE, (
        f"Visual-baseline timezone pin is '{browser_context_args[ 'timezone_id' ]}', expected "
        f"'{EXPECTED_BASELINE_TIMEZONE}'. The git-tracked baselines are container-canonical "
        f"(docker/lupin/Dockerfile sets ENV TZ=UTC and the :8000 merge gate captures "
        f"in-container); changing the zone invalidates every timestamp-bearing snapshot and "
        f"needs a --update-snapshots rebaseline in the same commit."
    )


def test_pinned_context_resolves_to_the_baseline_timezone(
    browser_type, browser_type_launch_args, browser_context_args
):
    """
    A real context built from the fixture args must RESOLVE to the baseline timezone,
    in ANY venue — including a UTC container.

    EFFECTIVENESS check. It catches a pin that is present but inert (renamed arg,
    unsupported value), which the args assertion above cannot see.

    WHY IT LAUNCHES ITS OWN BROWSER. Chromium takes its default zone from the ambient
    `TZ` of its process. Run against the session browser, this check is BLIND wherever
    the ambient zone already equals the baseline zone — which is precisely the :8000
    merge gate, since `docker/lupin/Dockerfile` sets `ENV TZ=UTC`. Measured 2026-09-15:
    with the pin DELETED under `TZ=UTC`, this assertion PASSED while
    `test_context_args_pin_the_baseline_timezone` failed. A test that passes either way
    in the venue that matters is not a guard.

    So it launches a control browser with `TZ` forced to `CONTROL_AMBIENT_TIMEZONE`,
    where pinned and unpinned give visibly different answers. Deleting the pin now
    reddens BOTH tests in every venue, not just on an Eastern host.

    The first assertion is an INSTRUMENT CHECK: an unpinned context in that browser must
    report the control zone. Without it, a forced `TZ` that silently failed to take would
    leave the real assertion passing for the wrong reason.

    Uses `about:blank`, so it needs no server and stays cheap.
    """
    launch_args = {
        **browser_type_launch_args,
        "env" : { **os.environ, "TZ": CONTROL_AMBIENT_TIMEZONE },
    }
    browser = browser_type.launch( **launch_args )
    try:
        control_context = browser.new_context()
        try:
            control_page     = control_context.new_page()
            control_resolved = control_page.evaluate( _RESOLVED_TIMEZONE_JS )
        finally:
            control_context.close()

        assert control_resolved == CONTROL_AMBIENT_TIMEZONE, (
            f"Instrument check failed: an UNPINNED context in a browser launched with "
            f"TZ={CONTROL_AMBIENT_TIMEZONE} resolved '{control_resolved}', not the forced zone. "
            f"The ambient TZ did not take, so this test cannot tell a working pin from a missing "
            f"one and its verdict below means nothing. Fix the control before reading the result."
        )

        pinned_context = browser.new_context( **browser_context_args )
        try:
            pinned_page     = pinned_context.new_page()
            pinned_resolved = pinned_page.evaluate( _RESOLVED_TIMEZONE_JS )
        finally:
            pinned_context.close()
    finally:
        browser.close()

    assert pinned_resolved == EXPECTED_BASELINE_TIMEZONE, (
        f"Browser resolved timezone '{pinned_resolved}', expected '{EXPECTED_BASELINE_TIMEZONE}'. The "
        f"control context in this same browser correctly reported '{control_resolved}', so the "
        f"forced ambient zone took and the probe can see a difference — meaning the pin in "
        f"browser_context_args is missing or did not take effect. Check the arg name and that the "
        f"value is a valid IANA zone."
    )
