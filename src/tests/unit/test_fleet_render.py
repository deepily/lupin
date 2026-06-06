#!/usr/bin/env python3
"""
Unit tests for fleet_render — the v2.1 direct-state fleet render + snapshot
(arbiter design `03` §10.2-§10.4). 100% line+branch+function coverage.
"""
import datetime
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter import fleet_render as fr


NOW = datetime.datetime( 2026, 6, 6, 22, 41, 0, tzinfo=datetime.timezone.utc )


# ── _fmt_age ──────────────────────────────────────────────────────────────────

class TestFmtAge:
    def test_none( self ):       assert fr._fmt_age( None ) == "—"
    def test_negative( self ):   assert fr._fmt_age( -5 ) == "0s"
    def test_seconds( self ):    assert fr._fmt_age( 4 ) == "4s"
    def test_minutes( self ):    assert fr._fmt_age( 359 ) == "5m"
    def test_hours( self ):      assert fr._fmt_age( 7200 ) == "2h"
    def test_days( self ):       assert fr._fmt_age( 90000 ) == "1d"


# ── _bridge_age / _event_age ──────────────────────────────────────────────────

class TestSignalAges:
    def test_bridge_age_none( self ):
        assert fr._bridge_age( None, NOW ) is None

    def test_bridge_age_valid( self ):
        assert fr._bridge_age( NOW.timestamp() - 10, NOW ) == pytest.approx( 10, abs=1 )

    def test_bridge_age_bad_value_swallowed( self ):
        assert fr._bridge_age( "not-a-number", NOW ) is None

    def test_event_age_none( self ):
        assert fr._event_age( None, NOW ) is None

    def test_event_age_valid( self ):
        ts = NOW - datetime.timedelta( seconds=30 )
        assert fr._event_age( ts, NOW ) == pytest.approx( 30, abs=1 )

    def test_event_age_bad_type_swallowed( self ):
        assert fr._event_age( "not-a-datetime", NOW ) is None


# ── _verdict ──────────────────────────────────────────────────────────────────

class TestVerdict:
    def test_offline_when_no_signal( self ):
        assert fr._verdict( None, 60, 600, 3600 ) == "offline"

    def test_live( self ):
        assert fr._verdict( 30, 60, 600, 3600 ) == "LIVE"

    def test_quiet_carries_age( self ):
        assert fr._verdict( 360, 60, 600, 3600 ) == "quiet 6m"

    def test_stale_carries_age( self ):
        assert fr._verdict( 1800, 60, 600, 3600 ) == "stale 30m"

    def test_offline_beyond_stale( self ):
        assert fr._verdict( 7200, 60, 600, 3600 ) == "offline"


# ── compute_liveness ──────────────────────────────────────────────────────────

class TestComputeLiveness:
    def test_bridge_primary_overrides_old_event( self ):
        """Fresh bridge ⇒ LIVE even with a 35m-old event ts (bridge is PRIMARY)."""
        view = { "last_event_ts": NOW - datetime.timedelta( minutes=35 ) }
        out  = fr.compute_liveness( view, NOW.timestamp() - 4, NOW )
        assert out[ "verdict" ] == "LIVE"
        assert out[ "bridge_age_s" ] == 4
        assert out[ "event_age_s" ] == 35 * 60
        assert out[ "freshest_age_s" ] == 4

    def test_event_only_when_no_bridge( self ):
        view = { "last_event_ts": NOW - datetime.timedelta( seconds=120 ) }
        out  = fr.compute_liveness( view, None, NOW )
        assert out[ "bridge_age_s" ] is None
        assert out[ "freshest_age_s" ] == 120

    def test_no_signal_offline( self ):
        out = fr.compute_liveness( { "last_event_ts": None }, None, NOW )
        assert out[ "verdict" ] == "offline" and out[ "freshest_age_s" ] is None

    def test_view_not_dict( self ):
        out = fr.compute_liveness( "not-a-dict", None, NOW )
        assert out[ "event_age_s" ] is None and out[ "verdict" ] == "offline"


# ── build_snapshot ────────────────────────────────────────────────────────────

class TestBuildSnapshot:
    def test_rows_sorted_and_two_columns( self ):
        view = {
            "s2": { "session_id": "s2", "persona": "Bo", "state": "stuck",
                    "holding_on": "peer:Ann", "stuck": True, "last_event_ts": None },
            "s1": { "session_id": "s1", "persona": "Ann", "state": "working",
                    "holding_on": "none", "stuck": False,
                    "last_event_ts": NOW - datetime.timedelta( minutes=35 ) },
        }
        snap = fr.build_snapshot( view, { "s1": NOW.timestamp() - 4, "s2": None }, NOW )
        assert snap[ "session_count" ] == 2
        assert [ r[ "session_id" ] for r in snap[ "sessions" ] ] == [ "s1", "s2" ]  # sorted
        r1 = snap[ "sessions" ][ 0 ]
        assert r1[ "state" ] == "working"          # state column
        assert "verdict" in r1[ "liveness" ]        # liveness column (orthogonal)
        assert snap[ "sessions" ][ 1 ][ "stuck" ] is True
        assert snap[ "generated_at" ] == NOW.isoformat()

    def test_non_dict_view_skipped( self ):
        snap = fr.build_snapshot( { "bad": "not-a-dict", "ok": { "session_id": "ok" } }, { }, NOW )
        assert snap[ "session_count" ] == 1 and snap[ "sessions" ][ 0 ][ "session_id" ] == "ok"

    def test_empty_fleet( self ):
        snap = fr.build_snapshot( { }, { }, NOW )
        assert snap[ "session_count" ] == 0 and snap[ "sessions" ] == [ ]

    def test_none_inputs( self ):
        snap = fr.build_snapshot( None, None, NOW )
        assert snap[ "session_count" ] == 0


# ── frame_signature ───────────────────────────────────────────────────────────

class TestFrameSignature:
    def _view( self ):
        return { "s1": { "session_id": "s1", "persona": "Ann", "state": "working",
                         "holding_on": "none", "stuck": False,
                         "last_event_ts": NOW - datetime.timedelta( minutes=35 ) } }

    def test_ticking_ages_not_a_change( self ):
        snap_a = fr.build_snapshot( self._view(), { "s1": NOW.timestamp() - 4 }, NOW )
        later  = NOW + datetime.timedelta( seconds=10 )
        snap_b = fr.build_snapshot( self._view(), { "s1": later.timestamp() - 9 }, later )
        assert fr.frame_signature( snap_a ) == fr.frame_signature( snap_b )

    def test_state_change_is_a_change( self ):
        snap_a = fr.build_snapshot( self._view(), { "s1": NOW.timestamp() - 4 }, NOW )
        v2 = self._view(); v2[ "s1" ][ "state" ] = "stuck"
        snap_b = fr.build_snapshot( v2, { "s1": NOW.timestamp() - 4 }, NOW )
        assert fr.frame_signature( snap_a ) != fr.frame_signature( snap_b )

    def test_verdict_bucket_transition_is_a_change( self ):
        snap_live = fr.build_snapshot( self._view(), { "s1": NOW.timestamp() - 4 }, NOW )
        snap_off  = fr.build_snapshot( self._view(), { "s1": None }, NOW )  # no bridge, old event → offline
        assert fr.frame_signature( snap_live ) != fr.frame_signature( snap_off )

    def test_none_snapshot( self ):
        assert fr.frame_signature( None ) == tuple()

    def test_non_str_verdict_handled( self ):
        # A row whose liveness.verdict is None must not crash bucket-splitting.
        snap = { "sessions": [ { "session_id": "x", "liveness": { "verdict": None } } ] }
        sig  = fr.frame_signature( snap )
        assert sig[ 0 ][ -1 ] is None


# ── render_fleet_table / render_tick ──────────────────────────────────────────

class TestRender:
    def test_table_has_columns_and_stuck( self ):
        view = { "s1": { "session_id": "s1", "persona": "Ann", "state": "stuck",
                         "holding_on": "peer:Bo", "stuck": True, "last_event_ts": None } }
        snap  = fr.build_snapshot( view, { "s1": None }, NOW )
        table = fr.render_fleet_table( snap )
        assert "Fleet arbiter" in table and "verdict" in table
        assert "Ann" in table and "STUCK" in table

    def test_table_empty( self ):
        assert "(no sessions)" in fr.render_fleet_table( fr.build_snapshot( { }, { }, NOW ) )

    def test_table_none( self ):
        assert "(no sessions)" in fr.render_fleet_table( None )

    def test_table_row_falls_back_to_sid_when_no_persona( self ):
        view = { "s9": { "session_id": "s9", "persona": None, "state": "idle",
                         "holding_on": "none", "stuck": False, "last_event_ts": None } }
        table = fr.render_fleet_table( fr.build_snapshot( view, { "s9": None }, NOW ) )
        assert "s9" in table

    def test_tick_with_change_shows_duration( self ):
        tick = fr.render_tick( NOW, NOW - datetime.timedelta( minutes=12 ), 5 )
        assert "no changes for 12m" in tick and "(since 22:29)" in tick and "5 session(s)" in tick

    def test_tick_never_changed( self ):
        assert "no changes yet" in fr.render_tick( NOW, None, 0 )


def test_quick_smoke_test():
    assert fr.quick_smoke_test() is True


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
