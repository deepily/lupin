#!/usr/bin/env python3
"""
Unit tests for the Heartbeat Hook pending-user-gate row logic (outward twin).

Target: 100% line + branch + function coverage of
    src/lupin_cli/claude_code/hooks/lib/heartbeat_user_gates.py

The module is PURE — every test injects parsed gate rows + an injected `now`
(no clock, no IO). Exhaustive transform matrix per 6929f4ac §9.
"""
import datetime as _dt

from lupin_cli.claude_code.hooks.lib import heartbeat_user_gates as ug


_T0  = _dt.datetime( 2026, 6, 22, 12, 0, 0, tzinfo=_dt.timezone.utc )
_NOW = _T0.timestamp()


def _ago( seconds ):
    """ISO-8601 string for `seconds` before the fixed _NOW reference."""
    return ( _T0 - _dt.timedelta( seconds=seconds ) ).isoformat()


# ── make_gate ─────────────────────────────────────────────────────────────────

def test_make_gate_full_field_set_and_order():
    g = ug.make_gate( "g1", "Proceed?", "ask_yes_no",
                      ask_payload_ref="payload://1", first_asked_ts=_ago( 0 ),
                      reask_interval_s=300, answered=False )
    assert tuple( g.keys() ) == ug.GATE_FIELDS
    assert g[ "id" ] == "g1" and g[ "question" ] == "Proceed?"
    assert g[ "ask_kind" ] == "ask_yes_no" and g[ "ask_payload_ref" ] == "payload://1"
    assert g[ "reask_interval_s" ] == 300 and g[ "answered" ] is False


def test_make_gate_last_asked_defaults_to_first():
    g = ug.make_gate( "g1", "q", "ask_yes_no", first_asked_ts=_ago( 10 ) )
    assert g[ "last_asked_ts" ] == g[ "first_asked_ts" ] == _ago( 10 )


def test_make_gate_explicit_last_asked_kept():
    g = ug.make_gate( "g1", "q", "ask_yes_no", first_asked_ts=_ago( 100 ), last_asked_ts=_ago( 5 ) )
    assert g[ "last_asked_ts" ] == _ago( 5 )


def test_make_gate_defaults_interval_and_unasked():
    g = ug.make_gate( "g1", "q", "converse" )
    assert g[ "reask_interval_s" ] == ug.DEFAULT_REASK_INTERVAL_S
    assert g[ "first_asked_ts" ] is None and g[ "last_asked_ts" ] is None
    assert g[ "ask_payload_ref" ] is None


# ── open_gates ────────────────────────────────────────────────────────────────

def test_open_gates_filters_answered():
    gates = [ ug.make_gate( "a", "q", "ask_yes_no" ),
              ug.make_gate( "b", "q", "ask_yes_no", answered=True ) ]
    assert [ g[ "id" ] for g in ug.open_gates( gates ) ] == [ "a" ]


def test_open_gates_skips_non_dicts():
    assert ug.open_gates( [ "x", None, 42, ug.make_gate( "a", "q", "ask_yes_no" ) ] ) \
        == [ ug.make_gate( "a", "q", "ask_yes_no" ) ]


def test_open_gates_none_is_empty():
    assert ug.open_gates( None ) == [ ]
    assert ug.open_gates( [ ] )  == [ ]


def test_open_gates_missing_answered_is_open():
    # A row without an `answered` key is treated OPEN (bias-to-owed).
    assert [ g[ "id" ] for g in ug.open_gates( [ { "id": "a" } ] ) ] == [ "a" ]


# ── due_gates ─────────────────────────────────────────────────────────────────

def test_due_gates_stale_and_never_asked_are_due():
    fresh = ug.make_gate( "f", "q", "ask_yes_no", last_asked_ts=_ago( 60 ) )
    stale = ug.make_gate( "s", "q", "ask_yes_no", last_asked_ts=_ago( 660 ) )
    never = ug.make_gate( "n", "q", "ask_yes_no", last_asked_ts=None )
    assert [ g[ "id" ] for g in ug.due_gates( [ fresh, stale, never ], _NOW ) ] == [ "s", "n" ]


def test_due_gates_boundary_equal_is_due():
    edge = ug.make_gate( "e", "q", "ask_yes_no", last_asked_ts=_ago( ug.DEFAULT_REASK_INTERVAL_S ) )
    assert [ g[ "id" ] for g in ug.due_gates( [ edge ], _NOW ) ] == [ "e" ]


def test_due_gates_excludes_answered():
    answered_stale = ug.make_gate( "s", "q", "ask_yes_no", last_asked_ts=_ago( 9999 ), answered=True )
    assert ug.due_gates( [ answered_stale ], _NOW ) == [ ]


def test_due_gates_custom_interval():
    g = ug.make_gate( "g", "q", "ask_yes_no", last_asked_ts=_ago( 300 ), reask_interval_s=240 )
    assert [ x[ "id" ] for x in ug.due_gates( [ g ], _NOW ) ] == [ "g" ]
    g2 = ug.make_gate( "g2", "q", "ask_yes_no", last_asked_ts=_ago( 300 ), reask_interval_s=600 )
    assert ug.due_gates( [ g2 ], _NOW ) == [ ]


def test_due_gates_bad_interval_falls_back_to_default():
    # Non-int / bool interval ⇒ default cadence; asked 11 min ago ⇒ due.
    bad_str  = { "id": "a", "answered": False, "last_asked_ts": _ago( 660 ), "reask_interval_s": "nope" }
    bad_bool = { "id": "b", "answered": False, "last_asked_ts": _ago( 660 ), "reask_interval_s": True }
    assert [ g[ "id" ] for g in ug.due_gates( [ bad_str, bad_bool ], _NOW ) ] == [ "a", "b" ]


def test_due_gates_none_is_empty():
    assert ug.due_gates( None, _NOW ) == [ ]


# ── aged_open_gates (arbiter resurface fixed-threshold filter) ────────────────

def test_aged_open_gates_fixed_threshold():
    fresh = ug.make_gate( "f", "q", "ask_yes_no", last_asked_ts=_ago( 60 ) )      # 1 min
    stale = ug.make_gate( "s", "q", "ask_yes_no", last_asked_ts=_ago( 2000 ) )    # ~33 min
    never = ug.make_gate( "n", "q", "ask_yes_no", last_asked_ts=None )
    # ceiling 1800s (30 min): stale + never aged; fresh not
    out = [ g[ "id" ] for g in ug.aged_open_gates( [ fresh, stale, never ], _NOW, 1800 ) ]
    assert out == [ "s", "n" ]


def test_aged_open_gates_boundary_equal_is_aged():
    edge = ug.make_gate( "e", "q", "ask_yes_no", last_asked_ts=_ago( 1800 ) )
    assert [ g[ "id" ] for g in ug.aged_open_gates( [ edge ], _NOW, 1800 ) ] == [ "e" ]


def test_aged_open_gates_excludes_answered():
    answered = ug.make_gate( "a", "q", "ask_yes_no", last_asked_ts=_ago( 9999 ), answered=True )
    assert ug.aged_open_gates( [ answered ], _NOW, 1800 ) == [ ]


def test_aged_open_gates_none_is_empty():
    assert ug.aged_open_gates( None, _NOW, 1800 ) == [ ]


# ── upsert_gate ───────────────────────────────────────────────────────────────

def test_upsert_replaces_existing_by_id_in_place():
    existing = ug.make_gate( "g1", "old", "ask_yes_no" )
    other    = ug.make_gate( "g2", "keep", "ask_yes_no" )
    out      = ug.upsert_gate( [ existing, other ], ug.make_gate( "g1", "new", "ask_yes_no" ) )
    assert [ g[ "id" ] for g in out ] == [ "g1", "g2" ]      # order preserved
    assert out[ 0 ][ "question" ] == "new"                    # replaced in place


def test_upsert_appends_new():
    out = ug.upsert_gate( [ ug.make_gate( "g1", "q", "ask_yes_no" ) ], ug.make_gate( "gX", "n", "converse" ) )
    assert [ g[ "id" ] for g in out ] == [ "g1", "gX" ]


def test_upsert_into_none_or_empty():
    out = ug.upsert_gate( None, ug.make_gate( "g1", "q", "ask_yes_no" ) )
    assert [ g[ "id" ] for g in out ] == [ "g1" ]


def test_upsert_preserves_non_dict_and_idless_rows():
    out = ug.upsert_gate( [ "junk", { "no_id": 1 } ], ug.make_gate( "g1", "q", "ask_yes_no" ) )
    assert out[ 0 ] == "junk" and out[ 1 ] == { "no_id": 1 } and out[ 2 ][ "id" ] == "g1"


def test_upsert_does_not_mutate_input():
    src = [ ug.make_gate( "g1", "old", "ask_yes_no" ) ]
    ug.upsert_gate( src, ug.make_gate( "g1", "new", "ask_yes_no" ) )
    assert src[ 0 ][ "question" ] == "old"                    # input untouched


# ── mark_answered ─────────────────────────────────────────────────────────────

def test_mark_answered_sets_flag_and_clears_open():
    out = ug.mark_answered( [ ug.make_gate( "g1", "q", "ask_yes_no" ) ], "g1" )
    assert out[ 0 ][ "answered" ] is True and ug.open_gates( out ) == [ ]


def test_mark_answered_explicit_false():
    answered = ug.make_gate( "g1", "q", "ask_yes_no", answered=True )
    out      = ug.mark_answered( [ answered ], "g1", answered=False )
    assert out[ 0 ][ "answered" ] is False


def test_mark_answered_id_miss_is_noop():
    out = ug.mark_answered( [ ug.make_gate( "g1", "q", "ask_yes_no" ) ], "nope" )
    assert out[ 0 ][ "answered" ] is False and out[ 0 ][ "id" ] == "g1"


def test_mark_answered_preserves_non_dicts_and_none():
    assert ug.mark_answered( None, "g1" ) == [ ]
    out = ug.mark_answered( [ "junk" ], "g1" )
    assert out == [ "junk" ]


def test_mark_answered_does_not_mutate_input():
    src = [ ug.make_gate( "g1", "q", "ask_yes_no" ) ]
    ug.mark_answered( src, "g1" )
    assert src[ 0 ][ "answered" ] is False


# ── stamp_asked ───────────────────────────────────────────────────────────────

def test_stamp_asked_resets_clock():
    never  = ug.make_gate( "n", "q", "ask_yes_no", last_asked_ts=None )
    out    = ug.stamp_asked( [ never ], "n", _ago( 0 ) )
    assert out[ 0 ][ "last_asked_ts" ] == _ago( 0 )
    assert ug.due_gates( out, _NOW ) == [ ]                   # just asked ⇒ not due


def test_stamp_asked_seeds_first_asked_when_missing():
    never = ug.make_gate( "n", "q", "ask_yes_no" )            # first/last both None
    out   = ug.stamp_asked( [ never ], "n", _ago( 0 ) )
    assert out[ 0 ][ "first_asked_ts" ] == _ago( 0 )


def test_stamp_asked_keeps_existing_first_asked():
    g   = ug.make_gate( "g", "q", "ask_yes_no", first_asked_ts=_ago( 1000 ), last_asked_ts=_ago( 1000 ) )
    out = ug.stamp_asked( [ g ], "g", _ago( 0 ) )
    assert out[ 0 ][ "first_asked_ts" ] == _ago( 1000 ) and out[ 0 ][ "last_asked_ts" ] == _ago( 0 )


def test_stamp_asked_id_miss_is_noop():
    out = ug.stamp_asked( [ ug.make_gate( "g1", "q", "ask_yes_no", last_asked_ts=_ago( 5 ) ) ], "nope", _ago( 0 ) )
    assert out[ 0 ][ "last_asked_ts" ] == _ago( 5 )


def test_stamp_asked_preserves_non_dicts_and_none():
    assert ug.stamp_asked( None, "g", _ago( 0 ) ) == [ ]
    assert ug.stamp_asked( [ "junk" ], "g", _ago( 0 ) ) == [ "junk" ]


def test_stamp_asked_does_not_mutate_input():
    src = [ ug.make_gate( "g", "q", "ask_yes_no", last_asked_ts=_ago( 5 ) ) ]
    ug.stamp_asked( src, "g", _ago( 0 ) )
    assert src[ 0 ][ "last_asked_ts" ] == _ago( 5 )


# ── quick_smoke_test ──────────────────────────────────────────────────────────

def test_quick_smoke_test_passes():
    assert ug.quick_smoke_test() is True
