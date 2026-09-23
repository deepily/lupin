"""
The LIVE positive control for `selector_altitude` — row `04735b66`.

A guard that has only ever been watched passing has not been shown able to fail. These two
arms run against the real legacy page, on one navigation:

    ARM A — the KNOWN wrong-level selector must FIRE, and must NAME the wrapper to use
    ARM B — the CORRECTED selector must PASS

⚠️ BOTH ARMS, OR NEITHER MEANS ANYTHING. Arm B alone is consistent with a check that cannot
fail; arm A alone is consistent with a check that fires on everything. They are written as one
test over one page so the pair cannot be half-run or half-skipped.

THE PAIR, and it is a real pair on the shipped page rather than a constructed one:
    #fleet-status-section   class="section-content"      the INNER div  — the defect
    #section-fleet-status   class="collapsible-section"  the WRAPPER    — the fix

That is the exact selector `pixel_compare.py` hand-typed on 2026-09-22, and re-pairing to the
wrapper took Δw to ZERO on all seven pairs — the 4px width "regression" across five of them
was the altitude error, not the product. Unlike `live_dom_check`'s arm B, nothing here is
constructed: the wrong-level element is shipped, and a probe really did aim at it.
"""
import pytest

from .selector_altitude import Altitude, WrongAltitude, altitudes, assert_section_altitude

WRONG_LEVEL = "#fleet-status-section"     # class="section-content"      — the inner
CORRECTED   = "#section-fleet-status"     # class="collapsible-section"  — the wrapper


def test_the_altitude_check_fires_on_the_wrong_level_and_passes_on_the_fix( notifications_page ):
    """
    Requires:
        - notifications_page is an authenticated page on the legacy client, WS connected

    Ensures:
        - the check reports DESCENDANT for the inner div and WRAPPER for the section
        - assert_section_altitude raises on the first and returns on the second
        - the raised message NAMES the wrapper, so the failure carries its own fix
    """
    page = notifications_page
    page.wait_for_timeout( 1000 )

    verdicts = altitudes( page, [ WRONG_LEVEL, CORRECTED ] )
    assert verdicts[ WRONG_LEVEL ][ 0 ] == Altitude.DESCENDANT, (
        f"{WRONG_LEVEL} is the section-content INNER div; if this now reads "
        f"{verdicts[ WRONG_LEVEL ][ 0 ]}, either the product changed or the check stopped "
        "discriminating — and both need a human before this control is trusted again" )
    assert verdicts[ CORRECTED ][ 0 ] == Altitude.WRAPPER

    # ---- ARM A: the known wrong-level selector must FIRE and name the wrapper ----
    with pytest.raises( WrongAltitude ) as raised:
        assert_section_altitude( page, [ WRONG_LEVEL ] )
    message = str( raised.value )
    assert "WRONG LEVEL" in message
    assert CORRECTED.lstrip( "#" ) in message, (
        "the failure did not name the wrapper to use; naming only the fault leaves the reader "
        "to re-derive the thing the check already had in hand" )

    # ---- ARM B: the corrected selector must PASS ----
    passed = assert_section_altitude( page, [ CORRECTED ] )
    assert passed[ CORRECTED ][ 0 ] == Altitude.WRAPPER
