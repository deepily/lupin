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
        # include_offline=True so the offline, stuck s2 row is retained for the sort/column check.
        snap = fr.build_snapshot( view, { "s1": NOW.timestamp() - 4, "s2": None }, NOW, include_offline=True )
        assert snap[ "session_count" ] == 2
        assert [ r[ "session_id" ] for r in snap[ "sessions" ] ] == [ "s1", "s2" ]  # sorted
        r1 = snap[ "sessions" ][ 0 ]
        assert r1[ "state" ] == "working"          # state column
        assert "verdict" in r1[ "liveness" ]        # liveness column (orthogonal)
        assert snap[ "sessions" ][ 1 ][ "stuck" ] is True
        assert snap[ "generated_at" ] == NOW.isoformat()

    def test_non_dict_view_skipped( self ):
        # include_offline=True so the (signal-less → offline) "ok" row survives the prune,
        # keeping the focus on non-dict skipping.
        snap = fr.build_snapshot( { "bad": "not-a-dict", "ok": { "session_id": "ok" } }, { }, NOW, include_offline=True )
        assert snap[ "session_count" ] == 1 and snap[ "sessions" ][ 0 ][ "session_id" ] == "ok"

    def test_empty_fleet( self ):
        snap = fr.build_snapshot( { }, { }, NOW )
        assert snap[ "session_count" ] == 0 and snap[ "sessions" ] == [ ]

    def test_none_inputs( self ):
        snap = fr.build_snapshot( None, None, NOW )
        assert snap[ "session_count" ] == 0

    def test_default_no_seams_role_worker_manager_none( self ):
        # Neither seam injected → back-compatible flat snapshot, but the two new
        # keys are ALWAYS present (the frontend row shape depends on them).
        view = { "s1": { "session_id": "s1", "persona": "Ann", "state": "working",
                         "holding_on": "none", "stuck": False, "last_event_ts": NOW } }  # LIVE → survives prune
        row = fr.build_snapshot( view, { }, NOW )[ "sessions" ][ 0 ]
        assert row[ "role" ] == "worker" and row[ "manager" ] is None


# ── _sid_matches (prefix-tolerant) ─────────────────────────────────────────────

class TestSidMatches:
    def test_exact( self ):            assert fr._sid_matches( "abc", "abc" ) is True
    def test_short_prefix_of_full( self ):
        assert fr._sid_matches( "d9e65cd8", "d9e65cd8-bb24-4656" ) is True
    def test_full_prefix_of_short( self ):
        assert fr._sid_matches( "d9e65cd8-bb24-4656", "d9e65cd8" ) is True
    def test_no_match( self ):         assert fr._sid_matches( "abc", "xyz" ) is False
    def test_falsy_a( self ):          assert fr._sid_matches( "", "x" ) is False
    def test_falsy_b( self ):          assert fr._sid_matches( "x", None ) is False


# ── build_snapshot hierarchy enrichment (Fleet-Status P1 §4) ────────────────────

class TestBuildSnapshotEnrichment:
    def _view( self ):
        # Fresh last_event_ts → LIVE, so the §5.2 default prune keeps these rows and
        # the hierarchy (role/manager) assertions below stay non-vacuous.
        return {
            "mgr0001": { "session_id": "mgr0001", "persona": "Tiberius", "state": "working",
                         "holding_on": "none", "stuck": False, "last_event_ts": NOW },
            "wkr0001": { "session_id": "wkr0001", "persona": "Rio", "state": "working",
                         "holding_on": "none", "stuck": False, "last_event_ts": NOW },
        }

    def test_role_manager_via_prefix_match( self ):
        # manager set carries the FULL slugified uuid; the row sid is the short form.
        snap = fr.build_snapshot(
            self._view(), { }, NOW,
            list_managers_fn = lambda: { "mgr0001-bb24-4656-8076-29f646b60a98" },
        )
        by_sid = { r[ "session_id" ]: r for r in snap[ "sessions" ] }
        assert by_sid[ "mgr0001" ][ "role" ] == "manager"
        assert by_sid[ "wkr0001" ][ "role" ] == "worker"

    def test_manager_persona_only_when_lineage( self ):
        def resolver( sid ):
            if sid == "wkr0001":
                return { "manager_persona": "Tiberius", "source": "lineage" }
            return { "manager_persona": "Bo", "source": "declared" }   # NOT lineage → ignored
        snap = fr.build_snapshot( self._view(), { }, NOW, resolve_manager_fn = resolver )
        by_sid = { r[ "session_id" ]: r for r in snap[ "sessions" ] }
        assert by_sid[ "wkr0001" ][ "manager" ] == "Tiberius"   # lineage surfaces
        assert by_sid[ "mgr0001" ][ "manager" ] is None         # declared → None (never guess)

    def test_manager_none_when_unresolved( self ):
        snap = fr.build_snapshot(
            self._view(), { }, NOW,
            resolve_manager_fn = lambda sid: { "manager_persona": None, "source": "unresolved" },
        )
        assert all( r[ "manager" ] is None for r in snap[ "sessions" ] )

    def test_manager_none_when_resolver_returns_non_dict( self ):
        snap = fr.build_snapshot(
            self._view(), { }, NOW,
            resolve_manager_fn = lambda sid: None,   # defensive: non-dict result
        )
        assert all( r[ "manager" ] is None for r in snap[ "sessions" ] )

    def test_resolver_throws_degrades_to_none( self ):
        def boom( sid ): raise RuntimeError( "brittle hop" )
        snap = fr.build_snapshot( self._view(), { }, NOW, resolve_manager_fn = boom )
        assert all( r[ "manager" ] is None for r in snap[ "sessions" ] )   # never raises

    def test_list_managers_throws_degrades_to_all_workers( self ):
        def boom(): raise RuntimeError( "no session dir" )
        snap = fr.build_snapshot( self._view(), { }, NOW, list_managers_fn = boom )
        assert all( r[ "role" ] == "worker" for r in snap[ "sessions" ] )   # never raises

    def test_list_managers_returns_none_treated_as_empty( self ):
        snap = fr.build_snapshot( self._view(), { }, NOW, list_managers_fn = lambda: None )
        assert all( r[ "role" ] == "worker" for r in snap[ "sessions" ] )

    def test_both_seams_full_hierarchy( self ):
        snap = fr.build_snapshot(
            self._view(), { }, NOW,
            list_managers_fn   = lambda: { "mgr0001" },
            resolve_manager_fn = lambda sid: (
                { "manager_persona": "Tiberius", "source": "lineage" } if sid == "wkr0001"
                else { "manager_persona": None, "source": "unresolved" }
            ),
        )
        by_sid = { r[ "session_id" ]: r for r in snap[ "sessions" ] }
        assert by_sid[ "mgr0001" ][ "role" ] == "manager" and by_sid[ "mgr0001" ][ "manager" ] is None
        assert by_sid[ "wkr0001" ][ "role" ] == "worker"  and by_sid[ "wkr0001" ][ "manager" ] == "Tiberius"


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
        # include_offline=True keeps s1 present-but-offline so this exercises a verdict
        # BUCKET transition (LIVE→offline), not the §5.2 prune (which would drop the row).
        snap_off  = fr.build_snapshot( self._view(), { "s1": None }, NOW, include_offline=True )  # → offline
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
        snap  = fr.build_snapshot( view, { "s1": None }, NOW, include_offline=True )  # offline row retained for render
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
        table = fr.render_fleet_table( fr.build_snapshot( view, { "s9": None }, NOW, include_offline=True ) )
        assert "s9" in table

    def test_tick_with_change_shows_duration( self ):
        tick = fr.render_tick( NOW, NOW - datetime.timedelta( minutes=12 ), 5 )
        assert "no changes for 12m" in tick and "(since 22:29)" in tick and "5 session(s)" in tick

    def test_tick_never_changed( self ):
        assert "no changes yet" in fr.render_tick( NOW, None, 0 )


# ── D6 / §5.2 published-snapshot offline prune ────────────────────────────────

class TestPublishedOfflinePrune:
    def _view( self, *, last_event_ts=None, commons_ts=None ):
        v = { "s1": { "session_id": "s1", "persona": "Ann", "state": "idle",
                      "holding_on": "none", "stuck": False, "last_event_ts": last_event_ts } }
        if commons_ts is not None:
            v[ "s1" ][ "commons_ts" ] = commons_ts
        return v

    def test_default_omits_offline_session( self ):
        # No bridge + no recent signal → verdict "offline" → pruned from the published snapshot.
        snap = fr.build_snapshot( self._view(), { "s1": None }, NOW )
        assert snap[ "session_count" ] == 0
        assert snap[ "sessions" ] == [ ]

    def test_include_offline_true_retains_offline_session( self ):
        snap = fr.build_snapshot( self._view(), { "s1": None }, NOW, include_offline=True )
        assert snap[ "session_count" ] == 1
        assert snap[ "sessions" ][ 0 ][ "liveness" ][ "verdict" ] == "offline"

    def test_live_session_survives_default_prune( self ):
        # Fresh bridge → LIVE → kept even with the default (include_offline=False).
        snap = fr.build_snapshot( self._view(), { "s1": NOW.timestamp() - 4 }, NOW )
        assert snap[ "session_count" ] == 1
        assert snap[ "sessions" ][ 0 ][ "liveness" ][ "verdict" ] == "LIVE"

    def test_count_reflects_post_prune_rows_in_a_mixed_fleet( self ):
        view = {
            "live": { "session_id": "live", "persona": "L", "state": "working",
                      "holding_on": "none", "stuck": False, "last_event_ts": None,
                      "commons_ts": NOW - datetime.timedelta( seconds=5 ) },   # LIVE by commons
            "dead": { "session_id": "dead", "persona": "D", "state": "idle",
                      "holding_on": "none", "stuck": False, "last_event_ts": None },  # offline
        }
        snap = fr.build_snapshot( view, { }, NOW )
        assert { r[ "session_id" ] for r in snap[ "sessions" ] } == { "live" }
        assert snap[ "session_count" ] == 1


def test_quick_smoke_test():
    assert fr.quick_smoke_test() is True


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
