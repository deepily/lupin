"""
Unit tests for operator_gate_routing — the PURE D4 urgency-routing decision
(proactive-manager A2, fcb5dbc0). :7999-eligible (pure, no IO).

Covers partition_by_urgency / digest_due / route_operator_gates + the _urgency_of
and _parse_iso helpers to 100% line + branch — the arbiter's tier-push WIRING is a
separate (deferred) thin consumer; the decision logic lives (and is proven) here.
"""
import datetime

import pytest

from cosa.agents.heartbeat_arbiter import operator_gate_routing as r


_NOW = datetime.datetime( 2026, 6, 23, 12, 0, 0, tzinfo=datetime.timezone.utc )


def _ago( seconds ):
    return ( _NOW - datetime.timedelta( seconds=seconds ) ).isoformat()


# ── _urgency_of ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "gate, expected", [
    ( { "urgency": "urgent" }, "urgent" ),
    ( { "urgency": "normal" }, "normal" ),
    ( { "urgency": "low" },    "low" ),
    ( { "urgency": "bogus" },  "normal" ),   # unknown → default tier
    ( { },                     "normal" ),    # missing → default tier
    ( { "urgency": None },     "normal" ),    # non-str → default tier
    ( "junk",                  "normal" ),    # non-dict → default tier
] )
def test_urgency_of( gate, expected ):
    assert r._urgency_of( gate ) == expected


# ── _parse_iso ────────────────────────────────────────────────────────────────

def test_parse_iso_aware_passthrough():
    parsed = r._parse_iso( "2026-06-23T12:00:00+00:00" )
    assert parsed == _NOW


def test_parse_iso_z_suffix_normalized():
    assert r._parse_iso( "2026-06-23T12:00:00Z" ) == _NOW


def test_parse_iso_naive_assumed_utc():
    parsed = r._parse_iso( "2026-06-23T12:00:00" )
    assert parsed == _NOW and parsed.tzinfo is datetime.timezone.utc


def test_parse_iso_none_and_non_string():
    assert r._parse_iso( None ) is None
    assert r._parse_iso( 123 ) is None
    assert r._parse_iso( "" ) is None


def test_parse_iso_unparseable():
    assert r._parse_iso( "not-a-timestamp" ) is None


# ── partition_by_urgency ──────────────────────────────────────────────────────

def test_partition_routes_each_tier():
    gates = [
        { "id": "u1", "urgency": "urgent" },
        { "id": "n1", "urgency": "normal" },
        { "id": "l1", "urgency": "low" },
    ]
    parts = r.partition_by_urgency( gates )
    assert [ g[ "id" ] for g in parts[ "interrupt" ] ] == [ "u1" ]
    assert [ g[ "id" ] for g in parts[ "digest" ] ]    == [ "n1" ]
    assert [ g[ "id" ] for g in parts[ "queue" ] ]     == [ "l1" ]


def test_partition_unknown_and_missing_go_to_digest():
    gates = [ { "id": "x1" }, { "id": "x2", "urgency": "bogus" } ]
    parts = r.partition_by_urgency( gates )
    assert [ g[ "id" ] for g in parts[ "digest" ] ] == [ "x1", "x2" ]
    assert parts[ "interrupt" ] == [ ] and parts[ "queue" ] == [ ]


def test_partition_skips_non_dict_entries():
    parts = r.partition_by_urgency( [ "junk", None, { "id": "n", "urgency": "normal" } ] )
    assert [ g[ "id" ] for g in parts[ "digest" ] ] == [ "n" ]


def test_partition_none_input_is_empty_buckets():
    assert r.partition_by_urgency( None ) == { "interrupt": [ ], "digest": [ ], "queue": [ ] }


def test_partition_preserves_order_within_bucket():
    gates = [ { "id": "n1", "urgency": "normal" }, { "id": "n2", "urgency": "normal" } ]
    assert [ g[ "id" ] for g in r.partition_by_urgency( gates )[ "digest" ] ] == [ "n1", "n2" ]


# ── digest_due ────────────────────────────────────────────────────────────────

def test_digest_due_never_emitted_is_true():
    assert r.digest_due( None, _NOW ) is True


def test_digest_due_unparseable_is_true():
    assert r.digest_due( "not-a-ts", _NOW ) is True


def test_digest_due_fresh_is_false():
    assert r.digest_due( _ago( 60 ), _NOW ) is False


def test_digest_due_stale_is_true():
    assert r.digest_due( _ago( 1801 ), _NOW ) is True


def test_digest_due_boundary_equal_is_true():
    assert r.digest_due( _ago( r.DEFAULT_DIGEST_CADENCE_SECONDS ), _NOW ) is True


def test_digest_due_future_stamp_is_not_due():
    future = ( _NOW + datetime.timedelta( seconds=300 ) ).isoformat()
    assert r.digest_due( future, _NOW ) is False


def test_digest_due_custom_cadence():
    assert r.digest_due( _ago( 300 ), _NOW, cadence_seconds=240 ) is True
    assert r.digest_due( _ago( 300 ), _NOW, cadence_seconds=600 ) is False


def test_digest_due_bad_now_type_biases_to_emit():
    # A non-datetime `now` (clock plumbing bug) ⇒ subtraction raises ⇒ bias-to-emit
    # (return True), never crash the arbiter's poll.
    assert r.digest_due( _ago( 60 ), None ) is True


# ── route_operator_gates ──────────────────────────────────────────────────────

def _mixed_gates():
    return [
        { "id": "u1", "urgency": "urgent" },
        { "id": "n1", "urgency": "normal" },
        { "id": "l1", "urgency": "low" },
    ]


def test_route_when_digest_due_emits_normals():
    v = r.route_operator_gates( _mixed_gates(), None, _NOW )
    assert [ g[ "id" ] for g in v[ "interrupt" ] ] == [ "u1" ]
    assert [ g[ "id" ] for g in v[ "digest" ] ]    == [ "n1" ]
    assert v[ "digest_due" ] is True
    assert [ g[ "id" ] for g in v[ "queue" ] ]     == [ "l1" ]


def test_route_when_not_due_withholds_digest_but_keeps_interrupt():
    v = r.route_operator_gates( _mixed_gates(), _ago( 60 ), _NOW )
    assert [ g[ "id" ] for g in v[ "interrupt" ] ] == [ "u1" ]   # urgent always interrupts
    assert v[ "digest" ] == [ ]                                  # normals wait for the next due sweep
    assert v[ "digest_due" ] is False
    assert [ g[ "id" ] for g in v[ "queue" ] ]     == [ "l1" ]


def test_route_empty_gates():
    v = r.route_operator_gates( [ ], None, _NOW )
    assert v == { "interrupt": [ ], "digest": [ ], "digest_due": True, "queue": [ ] }


def test_quick_smoke_test_passes():
    assert r.quick_smoke_test() is True
