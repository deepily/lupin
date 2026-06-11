#!/usr/bin/env python3
"""
Item A receipts (2026-06-11 outreach-receipts design §2) — the ONE-owner journal
line builder: `ts_local` ("2026-06-11-at-17-28-46-(EDT)") rides every arbiter
structured-log line alongside the machine-sortable ISO `ts`; tz is the INI-fed
`tz_name`; an invalid tz NEVER crashes the watcher (UTC fallback + one loud
`journal_tz_invalid`).

Venue: :7999-eligible / local — pure, no IO (emit_fn injected).
Design: src/rnd/v0.1.8/2026.06.11-arbiter-outreach-delivery-receipts-and-local-timestamps.md §2.
"""
import datetime
import json
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_journal import (
    DEFAULT_TZ_NAME, DELIVERED_OUTCOMES, TS_LOCAL_FORMAT,
    format_ts_local, make_log_fn, quick_smoke_test, resolve_tz,
)


JUNE = datetime.datetime( 2026, 6, 11, 21, 28, 46, tzinfo=datetime.timezone.utc )
JAN  = datetime.datetime( 2026, 1, 11, 21, 28, 46, tzinfo=datetime.timezone.utc )


def _build( **kw ):
    lines = [ ]
    log   = make_log_fn( emit_fn=lines.append, now_fn=kw.pop( "now_fn", lambda: JUNE ), **kw )
    return log, lines


# ── resolve_tz: valid / default / invalid ────────────────────────────────────

def test_resolve_tz_valid_name():
    tz, err = resolve_tz( "America/New_York" )
    assert err is None and format_ts_local( JUNE, tz ).endswith( "-(EDT)" )


def test_resolve_tz_none_uses_default():
    tz, err = resolve_tz( None )
    assert err is None
    assert DEFAULT_TZ_NAME == "America/New_York"
    assert format_ts_local( JUNE, tz ).endswith( "-(EDT)" )


def test_resolve_tz_invalid_falls_back_to_utc_with_error():
    tz, err = resolve_tz( "Not/AZone" )
    assert err is not None and "Not/AZone" in err
    assert format_ts_local( JUNE, tz ).endswith( "-(UTC)" )


# ── format_ts_local: Rick's exact format + DST awareness ────────────────────

def test_format_is_ricks_exact_shape():
    tz, _ = resolve_tz( "America/New_York" )
    assert format_ts_local( JUNE, tz ) == "2026-06-11-at-17-28-46-(EDT)"


def test_format_dst_flip_winter_is_est():
    tz, _ = resolve_tz( "America/New_York" )
    assert format_ts_local( JAN, tz ) == "2026-01-11-at-16-28-46-(EST)"


# ── make_log_fn: the canonical line shape ────────────────────────────────────

def test_line_carries_both_ts_fields_same_instant():
    log, lines = _build( loop="fleet_arbiter", tz_name="America/New_York" )
    log( "arbiter_outreach", kind="stall", case=11 )
    line = json.loads( lines[ -1 ] )
    assert line[ "ts" ]       == "2026-06-11T21:28:46+00:00"            # ISO stays machine-sortable
    assert line[ "ts_local" ] == "2026-06-11-at-17-28-46-(EDT)"          # same instant, human shape
    assert line[ "service" ]  == "lupin-arbiter-app"
    assert line[ "loop" ]     == "fleet_arbiter"                         # the TRUE emitting loop (§3.8)
    assert line[ "event" ]    == "arbiter_outreach"
    assert line[ "kind" ] == "stall" and line[ "case" ] == 11


def test_loop_field_omitted_when_none_and_service_overridable():
    log, lines = _build( service="heartbeat-arbiter" )
    log( "tick" )
    line = json.loads( lines[ -1 ] )
    assert line[ "service" ] == "heartbeat-arbiter" and "loop" not in line


def test_non_serializable_fields_are_stringified():
    log, lines = _build()
    log( "tick", when=JUNE )                                             # datetime → default=str
    assert "2026-06-11" in json.loads( lines[ -1 ] )[ "when" ]


def test_invalid_tz_logs_once_at_build_then_renders_utc():
    log, lines = _build( tz_name="Not/AZone" )
    first = json.loads( lines[ 0 ] )                                     # emitted AT build time
    assert first[ "event" ] == "journal_tz_invalid" and first[ "fallback" ] == "UTC"
    log( "tick" )
    assert json.loads( lines[ -1 ] )[ "ts_local" ].endswith( "-(UTC)" )
    assert len( lines ) == 2                                             # invalid-tz logged ONCE, not per line


# ── module exports + smoke ───────────────────────────────────────────────────

def test_delivered_outcomes_vocabulary():
    """One-owner outcome vocabulary (§3.1): exactly the /api/notify body states
    that mean the notification reached a connected surface."""
    assert DELIVERED_OUTCOMES == frozenset( { "queued", "delivered_via_listener" } )


def test_ts_local_format_constant_is_ricks_spec():
    assert TS_LOCAL_FORMAT == "%Y-%m-%d-at-%H-%M-%S-(%Z)"


def test_module_quick_smoke_test_passes():
    assert quick_smoke_test() is True


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
