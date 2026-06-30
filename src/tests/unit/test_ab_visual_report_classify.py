#!/usr/bin/env python3
"""
Unit tests for the A/B visual-report classification logic (pure functions).

The browser-driving capture in ab_visual_report.py is exercised end-to-end on
:7999 (the report run itself is its execution proof); these tests cover the
PURE classification branches with synthetic node maps — no server, no browser:

  _card_of / _message_prefix        — key parsing
  _corner_gate                      — per-message gate divergence + affected sets
  _diff                             — structural / style→B5 / corner-gate→B5 /
                                       container-cascade→B5 / genuine-drift /
                                       width-context classification

Venue: :7999 (pure logic). Run:
    PYTHONPATH=src pytest src/tests/unit/test_ab_visual_report_classify.py -v
"""

from __future__ import annotations

from tests.parity_oracle.ab_visual_report import (
    _card_of,
    _corner_gate,
    _diff,
    _message_prefix,
    _summary_counts,
)

SID = "claude.code@lupin.deepily.ai#parity01"


# ---------------------------------------------------------------------------
# Helpers to build synthetic node maps in the CONTRACT_STYLE_GEOM shape.
# ---------------------------------------------------------------------------

def _node( styles: dict | None = None, geom: dict | None = None ) -> dict:
    base_styles = { p: "x" for p in ( "display", "color" ) }
    if styles:
        base_styles.update( styles )
    return {
        "styles": base_styles,
        "geom"  : geom or { "dx": 0.0, "dy": 0.0, "w": 100.0, "h": 20.0 },
    }


def _cap( nodes: dict, corner: dict | None = None ) -> dict:
    return { "nodes": nodes, "corner": corner or {} }


# ---------------------------------------------------------------------------
# key parsing
# ---------------------------------------------------------------------------

def test_card_of():
    assert _card_of( f"card:{SID}" ) == f"card:{SID}"
    assert _card_of( f"card:{SID}>header" ) == f"card:{SID}"
    assert _card_of( f"card:{SID}>msg[2]>text" ) == f"card:{SID}"
    assert _card_of( "not-a-card" ) is None


def test_message_prefix():
    assert _message_prefix( f"card:{SID}>msg[0]" ) == f"card:{SID}>msg[0]"
    assert _message_prefix( f"card:{SID}>msg[3]>text" ) == f"card:{SID}>msg[3]"
    assert _message_prefix( f"card:{SID}>header" ) is None
    assert _message_prefix( f"card:{SID}" ) is None


# ---------------------------------------------------------------------------
# corner-gate divergence
# ---------------------------------------------------------------------------

def test_corner_gate_detects_mux_visible_buttons():
    legacy = { f"card:{SID}>msg[0]": { "button_count": 2, "visible": 0, "reserved_px": 0.0 } }
    mux    = { f"card:{SID}>msg[0]": { "button_count": 2, "visible": 2, "reserved_px": 41.3 } }
    rows, msgs, cards = _corner_gate( legacy, mux )
    assert len( rows ) == 1
    assert rows[ 0 ][ "mux_visible" ] == 2 and rows[ 0 ][ "legacy_visible" ] == 0
    assert msgs == { f"card:{SID}>msg[0]" }
    assert cards == { f"card:{SID}" }


def test_corner_gate_identical_is_no_divergence():
    same = { f"card:{SID}>msg[0]": { "button_count": 2, "visible": 0, "reserved_px": 0.0 } }
    rows, msgs, cards = _corner_gate( same, dict( same ) )
    assert rows == [] and msgs == set() and cards == set()


def test_corner_gate_legacy_more_visible_is_reported_but_not_affected():
    # Reverse polarity (legacy shows more) → reported for review, but NOT a B5
    # gate gap (affected sets stay empty — only mux-un-gated drives B5 closure).
    legacy = { f"card:{SID}>msg[0]": { "button_count": 2, "visible": 2, "reserved_px": 41.3 } }
    mux    = { f"card:{SID}>msg[0]": { "button_count": 2, "visible": 0, "reserved_px": 0.0 } }
    rows, msgs, cards = _corner_gate( legacy, mux )
    assert len( rows ) == 1 and msgs == set() and cards == set()


# ---------------------------------------------------------------------------
# _diff classification
# ---------------------------------------------------------------------------

def test_diff_structural_node_present_one_side():
    legacy = _cap( { f"card:{SID}": _node(), f"card:{SID}>msg[0]": _node() } )
    mux    = _cap( { f"card:{SID}": _node() } )
    d = _diff( legacy, mux )
    assert d[ "structural" ] == [ { "key": f"card:{SID}>msg[0]", "side": "legacy-only" } ]
    assert d[ "node_counts" ] == { "legacy": 2, "mux": 1, "common": 1 }


def test_diff_style_delta_is_b5_candidate():
    legacy = _cap( { f"card:{SID}>msg[0]>text": _node( styles={ "color": "rgb(0,0,0)" } ) } )
    mux    = _cap( { f"card:{SID}>msg[0]>text": _node( styles={ "color": "rgb(9,9,9)" } ) } )
    d = _diff( legacy, mux )
    assert len( d[ "style_deltas" ] ) == 1
    assert d[ "style_deltas" ][ 0 ][ "prop" ] == "color"


def test_diff_geom_with_style_delta_classified_style_b5():
    legacy = _cap( { f"card:{SID}>msg[0]>text": _node(
        styles={ "color": "a" }, geom={ "dx": 0, "dy": 0, "w": 100, "h": 20 } ) } )
    mux    = _cap( { f"card:{SID}>msg[0]>text": _node(
        styles={ "color": "b" }, geom={ "dx": 0, "dy": 0, "w": 160, "h": 20 } ) } )
    d = _diff( legacy, mux )
    geom = [ g for g in d[ "geom_drift" ] if g[ "key" ].endswith( ">text" ) ]
    assert geom and geom[ 0 ][ "cause" ] == "style"
    assert geom[ 0 ][ "classification" ] == "B5-CANDIDATE"


def test_diff_geom_corner_gate_message_classified_b5():
    # message-text width delta with NO style delta, but the message is gate-affected.
    legacy = _cap(
        { f"card:{SID}>msg[0]>text": _node( geom={ "dx": 0, "dy": 0, "w": 787, "h": 20 } ) },
        corner={ f"card:{SID}>msg[0]": { "button_count": 2, "visible": 0, "reserved_px": 0.0 } },
    )
    mux = _cap(
        { f"card:{SID}>msg[0]>text": _node( geom={ "dx": 0, "dy": 0, "w": 730, "h": 20 } ) },
        corner={ f"card:{SID}>msg[0]": { "button_count": 2, "visible": 2, "reserved_px": 41.3 } },
    )
    d = _diff( legacy, mux )
    geom = [ g for g in d[ "geom_drift" ] if g[ "axis" ] == "w" ]
    assert geom and geom[ 0 ][ "cause" ] == "corner-gate"
    assert geom[ 0 ][ "classification" ] == "B5-CANDIDATE"
    assert d[ "corner_gate_affected_count" ] == 1


def test_diff_container_vertical_cascade_classified_b5():
    # card height delta (no style, no >msg prefix) but the card has a gate-affected
    # message → vertical container cascade → B5-CANDIDATE.
    legacy = _cap(
        {
            f"card:{SID}": _node( geom={ "dx": 0, "dy": 0, "w": 100, "h": 335 } ),
            f"card:{SID}>msg[0]>text": _node( geom={ "dx": 0, "dy": 0, "w": 787, "h": 20 } ),
        },
        corner={ f"card:{SID}>msg[0]": { "button_count": 2, "visible": 0, "reserved_px": 0.0 } },
    )
    mux = _cap(
        {
            f"card:{SID}": _node( geom={ "dx": 0, "dy": 0, "w": 100, "h": 337 } ),
            f"card:{SID}>msg[0]>text": _node( geom={ "dx": 0, "dy": 0, "w": 730, "h": 20 } ),
        },
        corner={ f"card:{SID}>msg[0]": { "button_count": 2, "visible": 2, "reserved_px": 41.3 } },
    )
    d = _diff( legacy, mux )
    card_h = [ g for g in d[ "geom_drift" ] if g[ "key" ] == f"card:{SID}" and g[ "axis" ] == "h" ]
    assert card_h and card_h[ 0 ][ "cause" ] == "corner-gate-cascade"
    assert card_h[ 0 ][ "classification" ] == "B5-CANDIDATE"


def test_diff_top_card_width_is_width_context():
    legacy = _cap( { f"card:{SID}": _node( geom={ "dx": 0, "dy": 0, "w": 100, "h": 20 } ) } )
    mux    = _cap( { f"card:{SID}": _node( geom={ "dx": 0, "dy": 0, "w": 140, "h": 20 } ) } )
    d = _diff( legacy, mux )
    assert len( d[ "width_ctx" ] ) == 1 and d[ "width_ctx" ][ 0 ][ "axis" ] == "w"
    assert all( g[ "axis" ] != "w" for g in d[ "geom_drift" ] if g[ "key" ] == f"card:{SID}" )


def test_diff_unexplained_geom_is_genuine_drift():
    # A vertical delta on a node whose card has NO gate-affected message and NO
    # style delta → genuine drift (needs eyes).
    legacy = _cap( { f"card:{SID}>header": _node( geom={ "dx": 0, "dy": 0, "w": 100, "h": 20 } ) } )
    mux    = _cap( { f"card:{SID}>header": _node( geom={ "dx": 0, "dy": 5, "w": 100, "h": 20 } ) } )
    d = _diff( legacy, mux )
    drift = [ g for g in d[ "geom_drift" ] if g[ "classification" ] == "GENUINE-DRIFT" ]
    assert drift and drift[ 0 ][ "cause" ] == "none"


def test_diff_within_tolerance_is_not_a_delta():
    legacy = _cap( { f"card:{SID}>header": _node( geom={ "dx": 0, "dy": 0.0, "w": 100, "h": 20 } ) } )
    mux    = _cap( { f"card:{SID}>header": _node( geom={ "dx": 0, "dy": 0.9, "w": 100, "h": 20 } ) } )
    d = _diff( legacy, mux )
    assert d[ "geom_drift" ] == []


def test_summary_counts_partitions_b5_vs_genuine():
    legacy = _cap(
        {
            f"card:{SID}>msg[0]>text": _node( geom={ "dx": 0, "dy": 0, "w": 787, "h": 20 } ),
            f"card:{SID}>header": _node( geom={ "dx": 0, "dy": 0, "w": 100, "h": 20 } ),
        },
        corner={ f"card:{SID}>msg[0]": { "button_count": 2, "visible": 0, "reserved_px": 0.0 } },
    )
    mux = _cap(
        {
            f"card:{SID}>msg[0]>text": _node( geom={ "dx": 0, "dy": 0, "w": 730, "h": 20 } ),
            f"card:{SID}>header": _node( geom={ "dx": 0, "dy": 6, "w": 100, "h": 20 } ),
        },
        corner={ f"card:{SID}>msg[0]": { "button_count": 2, "visible": 2, "reserved_px": 41.3 } },
    )
    s = _summary_counts( _diff( legacy, mux ) )
    assert s[ "geom_b5" ] == 1          # the corner-gate-caused text width delta
    assert s[ "genuine_drift" ] == 1    # the header dy drift
    assert s[ "corner_gate" ] == 1
