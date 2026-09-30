"""
live_dom_check.py — the EMPIRICAL half of the selector guard.

WHY THIS EXISTS (Mr. Radio 🦉's ruling, 2026-09-22)
---------------------------------------------------
`selector_guard.preflight()` is a STATIC parse of the TypeScript and the served HTML. It
proves a selector is named by the product's source. It cannot prove the running page has it.
A selector live in source but dropped from `static/dist/multiplexer/boot.js` — a stale bundle,
a missed rebuild, a source/served divergence — preflights green and still matches nothing.

So the static check is necessary and not sufficient, and this is the sufficient half: after
navigation, assert that every preflighted selector ACTUALLY RESOLVED in the live DOM. That
assertion is empirical. It cannot be fooled by a stale bundle, because it asks the bundle that
is running rather than the source that was meant to produce it.

THE DIVISION OF LABOUR, which is the point:
    preflight()        — "does the product name this?"     static, before the browser
    assert_live_dom()  — "did the running page produce it?" empirical, after navigation

A failure in the first is a PROBE BUG (I typed a name nothing ships).
A failure in the second is BUILD DRIFT (source says it ships, the served page disagrees).
Those want different people and different fixes, so they are different exceptions.

PROVING IT DISCRIMINATES
------------------------
A guard that has only ever been watched passing has not been shown able to fail. `--self-test`
runs two arms against the same live page:
    arm A — assert over untouched selectors            -> must PASS
    arm B — one element REMOVED from the DOM first     -> must FIRE, naming that selector
Arm B is the precise analogue of a bundle-dropped selector, applied at the only layer that
decides the question: what the running page actually contains.

Requires:
    - LUPIN_ROOT set; a server answering at BASE; test credentials in the environment
Ensures:
    - assert_live_dom() raises LiveDomDrift naming EVERY unresolved selector, never just one
"""
import json, os, pathlib, sys

BASE = os.environ.get( "LUPIN_PROBE_BASE", "http://localhost:7999" )
MUX  = "/app/multiplexer"


class LiveDomDrift( Exception ):
    """Raised when a selector the source names did not resolve in the running page."""


def assert_live_dom( page, selectors, settle_ms=0 ):
    """
    Assert every selector resolved in the LIVE DOM.

    Requires:
        - page has already navigated to the surface under test
        - selectors preflighted clean (none of them DEAD)
    Ensures:
        - returns { selector: count } when all resolved
    Raises:
        - LiveDomDrift naming every selector whose live count is 0
    """
    if settle_ms: page.wait_for_timeout( settle_ms )

    counts  = { sel: page.locator( sel ).count() for sel in selectors }
    missing = { s: c for s, c in counts.items() if c == 0 }

    # An empty selector list would make this pass vacuously — a loop over nothing satisfies
    # every assertion inside it.
    if not selectors:
        raise LiveDomDrift( "assert_live_dom called with ZERO selectors — a loop over nothing "
                            "passes every assertion in it. Refusing to report a vacuous pass." )
    if missing:
        lines = "\n".join( f"    {s}" for s in sorted( missing ) )
        raise LiveDomDrift(
            f"BUILD DRIFT — {len( missing )} of {len( selectors )} selectors are named by the\n"
            f"source but did NOT resolve in the running page. The static preflight passed, so\n"
            f"this is not a typo: the served bundle and the source disagree. Rebuild, or the\n"
            f"element is mounted on a path this navigation did not take.\n{lines}" )
    return counts


def _login_tokens( requests ):
    email = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    pw    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not pw:
        raise ValueError( "Set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and "
                          "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    return requests.post( f"{BASE}/auth/login", json={ "email": email, "password": pw },
                          timeout=10 ).json()[ "tokens" ]


def self_test():                      # pragma: no cover - reached only from the __main__ guard below; it launches a real Chromium and logs into a live server, so no pytest process calls it
    """
    Two arms on one live page. Arm B simulates a bundle-dropped selector by removing the
    element, which is what 'dropped from the bundle' means where it counts.
    """
    import requests
    from playwright.sync_api import sync_playwright
    sys.path.insert( 0, str( pathlib.Path( __file__ ).parent ) )
    from selector_guard import preflight

    # Three shipped panes; the victim is the one arm B removes.
    victim    = '[data-testid="multiplexer-fleet-status-pane"]'
    selectors = [ victim,
                  '[data-testid="multiplexer-task-list-pane"]',
                  '[data-testid="multiplexer-epic-board-pane"]' ]

    preflight( selectors )           # static half must be clean, or the arms mean nothing
    print( f"preflight clean for {len( selectors )} selectors\n" )

    tok = _login_tokens( requests )
    with sync_playwright() as pw:
        b   = pw.chromium.launch()
        ctx = b.new_context( viewport={ "width": 1600, "height": 1200 } )
        ctx.add_init_script(
            f"window.localStorage.setItem('lupin_access_token', {json.dumps( tok['access_token'] )});"
            f"window.localStorage.setItem('lupin_refresh_token', {json.dumps( tok['refresh_token'] )});" )
        p = ctx.new_page()
        p.goto( f"{BASE}{MUX}", wait_until="networkidle", timeout=30000 )
        p.wait_for_timeout( 3500 )

        # ---- ARM A: untouched page, the assertion must PASS ----
        try:
            counts = assert_live_dom( p, selectors )
            arm_a  = True
            print( f"  ARM A  PASS  all {len( selectors )} resolved: "
                   + ", ".join( f"{s.split( chr(34) )[1]}={c}" for s, c in counts.items() ) )
        except LiveDomDrift as e:
            arm_a = False
            print( f"  ARM A  FAIL  the control arm fired — the rig is broken, not the product:\n{e}" )

        # ---- ARM B: remove the victim, the assertion must FIRE ----
        removed = p.evaluate( """( sel ) => {
            const els = Array.from( document.querySelectorAll( sel ) );
            els.forEach( e => e.remove() );
            return els.length;
        }""", victim )
        print( f"\n  removed {removed} element(s) matching {victim} — simulating a bundle drop" )
        try:
            assert_live_dom( p, selectors )
            arm_b = False
            print( "  ARM B  FAIL  the assertion did NOT fire on a removed element — it cannot "
                   "discriminate, and every pass it has ever produced is worthless" )
        except LiveDomDrift as e:
            arm_b = victim in str( e )
            print( f"  ARM B  {'PASS' if arm_b else 'FAIL'}  the assertion fired"
                   f"{' and named the victim' if arm_b else ' but did NOT name the victim'}:" )
            print( "         " + str( e ).splitlines()[ 0 ] )
            print( "         " + str( e ).splitlines()[ -1 ].strip() )

        ctx.close(); b.close()

    print()
    if arm_a and arm_b:
        print( "self-test PASSED: the live-DOM assertion passes on an intact page and FIRES on a "
               "dropped element, naming it. It discriminates." )
        return 0
    print( "self-test FAILED — do not trust this assertion." )
    return 1


if __name__ == "__main__":
    raise SystemExit( self_test() )
