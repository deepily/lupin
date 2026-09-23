"""
Unit tests for `src/tests/e2e_ui/selector_altitude.py` — row `04735b66`.

THE HOLE THIS MODULE CLOSES: a selector that resolves but names the WRONG LEVEL of the page.
It is shipped, it resolves, it screenshots cleanly — so `selector_guard` and `live_dom_check`
both pass it — and then it reports a size the probe invented. On 2026-09-22 that produced a
4px width "regression" across five pairs and masked the colour stage entirely, because every
comparison aborted on size first.

THE LIVE POSITIVE CONTROL IS NOT HERE, AND SAYING SO IS THE POINT. These cases pin the
decision logic against a fake page. The proof that the check FIRES on the real defect is the
two-arm control against :7999 — `test_the_known_wrong_level_pair_is_still_the_documented_one`
below pins the pair those arms use, so a rename on the product side reddens a fast test rather
than silently retiring the control.
"""
import pathlib, sys

import pytest

sys.path.insert( 0, str( pathlib.Path( __file__ ).resolve().parents[ 1 ] / "e2e_ui" ) )

import selector_altitude as sa


class FakePage:
    """
    A page that returns a canned probe map.

    It records the args it was called with, so a test can assert the module asked the REAL
    question — a fake that ignores its input answers the same however the code behaves, and
    every assertion written over it inherits that.
    """
    def __init__( self, probes ):
        self.probes    = probes
        self.last_args = None

    def evaluate( self, script, args ):
        self.last_args = ( script, args )
        return { sel: self.probes[ sel ] for sel in args[ "selectors" ] }


WRAPPER    = { "resolved": True, "hasWrapper": True,  "isWrapper": True,
               "wrapperId": "section-fleet-status", "wrapperCls": "collapsible-section",
               "ownCls": "collapsible-section" }
DESCENDANT = { "resolved": True, "hasWrapper": True,  "isWrapper": False,
               "wrapperId": "section-fleet-status", "wrapperCls": "collapsible-section",
               "ownCls": "section-content" }
UNWRAPPED  = { "resolved": True, "hasWrapper": False, "isWrapper": False,
               "wrapperId": None, "wrapperCls": None, "ownCls": "page-header" }
UNRESOLVED = { "resolved": False }


# --------------------------------------------------------------------------------------
# classify_altitude — pure, four states, each distinguishable
# --------------------------------------------------------------------------------------
def test_an_element_that_is_its_own_wrapper_is_at_the_intended_altitude():
    state, detail = sa.classify_altitude( WRAPPER )
    assert state == sa.Altitude.WRAPPER
    assert sa.WRAPPER_CLASS in detail


def test_an_element_inside_a_wrapper_is_the_defect_and_the_detail_names_the_fix():
    """The failure has to hand back the wrapper. Naming only the fault leaves the reader to
    re-derive the thing the check already had in hand."""
    state, detail = sa.classify_altitude( DESCENDANT )
    assert state == sa.Altitude.DESCENDANT
    assert "#section-fleet-status" in detail
    assert "measure that instead" in detail


def test_an_element_outside_every_section_is_its_own_state_not_a_pass():
    """'Correct altitude' and 'no altitude to be wrong about' are different facts. Folding
    them is the same two-states-one-representation defect this row exists for."""
    state, detail = sa.classify_altitude( UNWRAPPED )
    assert state == sa.Altitude.UNWRAPPED
    assert state != sa.Altitude.WRAPPER
    assert "outside any section" in detail


def test_an_unresolved_selector_is_deferred_to_the_other_guard():
    state, detail = sa.classify_altitude( UNRESOLVED )
    assert state == sa.Altitude.UNRESOLVED
    assert "live_dom_check" in detail


def test_the_four_states_are_distinct():
    seen = { sa.classify_altitude( p )[ 0 ]
             for p in ( WRAPPER, DESCENDANT, UNWRAPPED, UNRESOLVED ) }
    assert seen == set( sa.Altitude.ALL )


# --------------------------------------------------------------------------------------
# altitudes
# --------------------------------------------------------------------------------------
def test_altitudes_classifies_every_selector_it_was_given():
    page = FakePage( { "#a": WRAPPER, "#b": DESCENDANT } )
    v    = sa.altitudes( page, [ "#a", "#b" ] )
    assert v[ "#a" ][ 0 ] == sa.Altitude.WRAPPER
    assert v[ "#b" ][ 0 ] == sa.Altitude.DESCENDANT


def test_altitudes_asks_the_page_the_real_question():
    """Pin that the module runs the SHIPPED probe script and forwards the wrapper class — a
    control over a different probe than the one that ships proves nothing about the one that
    ships."""
    page = FakePage( { "#a": WRAPPER } )
    sa.altitudes( page, [ "#a" ] )
    script, args = page.last_args
    assert script == sa.ALTITUDE_PROBE_JS
    assert args == { "selectors": [ "#a" ], "wrapperClass": sa.WRAPPER_CLASS }


def test_altitudes_forwards_a_custom_wrapper_class():
    page = FakePage( { "#a": WRAPPER } )
    sa.altitudes( page, [ "#a" ], wrapper_class="panel" )
    assert page.last_args[ 1 ][ "wrapperClass" ] == "panel"


def test_altitudes_refuses_an_empty_selector_list():
    """A loop over nothing satisfies every assertion in it."""
    with pytest.raises( sa.WrongAltitude, match="ZERO selectors" ):
        sa.altitudes( FakePage( {} ), [] )


# --------------------------------------------------------------------------------------
# assert_section_altitude
# --------------------------------------------------------------------------------------
def test_assert_passes_and_returns_verdicts_when_every_selector_is_a_wrapper():
    page = FakePage( { "#a": WRAPPER, "#b": WRAPPER } )
    v    = sa.assert_section_altitude( page, [ "#a", "#b" ] )
    assert all( st == sa.Altitude.WRAPPER for st, _d in v.values() )


def test_assert_does_not_fire_on_an_unwrapped_or_unresolved_element():
    """Only DESCENDANT is this check's business. Firing on the others would make it a worse
    duplicate of live_dom_check."""
    page = FakePage( { "#a": UNWRAPPED, "#b": UNRESOLVED } )
    v    = sa.assert_section_altitude( page, [ "#a", "#b" ] )
    assert v[ "#a" ][ 0 ] == sa.Altitude.UNWRAPPED


def test_assert_fires_on_a_descendant_and_names_the_wrapper_to_use():
    page = FakePage( { "#fleet-status-section": DESCENDANT } )
    with pytest.raises( sa.WrongAltitude ) as e:
        sa.assert_section_altitude( page, [ "#fleet-status-section" ] )
    msg = str( e.value )
    assert "WRONG LEVEL" in msg
    assert "#fleet-status-section" in msg
    assert "#section-fleet-status" in msg


def test_assert_names_every_offender_not_merely_the_first():
    """This defect arrives in batches — one mis-levelled pairing list produced five at once."""
    page = FakePage( { "#a": DESCENDANT, "#b": DESCENDANT, "#c": WRAPPER } )
    with pytest.raises( sa.WrongAltitude ) as e:
        sa.assert_section_altitude( page, [ "#a", "#b", "#c" ] )
    msg = str( e.value )
    assert "#a" in msg and "#b" in msg
    assert "2 of 3 selectors" in msg


def test_assert_forwards_a_custom_wrapper_class():
    page = FakePage( { "#a": WRAPPER } )
    sa.assert_section_altitude( page, [ "#a" ], wrapper_class="panel" )
    assert page.last_args[ 1 ][ "wrapperClass" ] == "panel"


# --------------------------------------------------------------------------------------
# the live control's coordinates, pinned so a rename cannot retire it silently
# --------------------------------------------------------------------------------------
def test_the_known_wrong_level_pair_is_still_the_documented_one():
    """
    The two-arm live control drives `#fleet-status-section` (inner) against
    `#section-fleet-status` (wrapper) on the legacy page. If the product renames either, the
    control would keep passing by simply not resolving — so pin the pair against the shipped
    HTML here, where it is cheap to notice.
    """
    root = pathlib.Path( __file__ ).resolve().parents[ 3 ]
    html = ( root / "src/lupin_app/static/html/notifications.html" ).read_text()
    assert 'id="fleet-status-section"' in html, "the wrong-level half of the control is gone"
    assert 'id="section-fleet-status"' in html, "the corrected half of the control is gone"
    assert 'class="collapsible-section" id="section-fleet-status"' in html, \
        "the wrapper no longer carries the class the altitude predicate keys on"
