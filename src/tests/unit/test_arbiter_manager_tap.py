#!/usr/bin/env python3
"""
Unit tests for v2.2 lane B2 — the arbiter's active manager-tap (per-group
DM-push, throttle tap-on-change + min-interval, D5 routing, advisory-only).
Drives ArbiterConsumerJob._tap_managers directly with hand-built fleet views.
"""
import datetime
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob


NOW = datetime.datetime( 2026, 6, 6, 22, 0, 0, tzinfo=datetime.timezone.utc )


class _Gateway:
    def __init__( self ):
        self.sent = [ ]   # (recipient, body)
        self.posts = [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, recipient, body, metadata=None ): self.sent.append( ( recipient, body ) )
    def post( self, topic, body ): self.posts.append( ( topic, body ) )


def _job( gw, resolve_map, *, min_interval=300, notify=None ):
    """ArbiterConsumerJob wired with an injected resolve_manager_fn (mapping)."""
    def _resolve( sid, declared_manager=None ):
        if sid in resolve_map:
            return { "manager_session_id": "m", "manager_persona": resolve_map[ sid ], "source": "lineage" }
        return { "manager_session_id": None, "manager_persona": None, "source": "unresolved" }
    return ArbiterConsumerJob(
        commons                  = gw,
        poll_seconds             = 5,
        manager_recipient        = "DeclaredMgr",
        tap_min_interval_seconds = min_interval,
        resolve_manager_fn       = _resolve,
        notify_fn                = notify or ( lambda *a, **k: None ),
    )


def _stuck( sid, persona ):
    return { "session_id": sid, "persona": persona, "state": "stuck", "stuck": True, "holding_on": "none" }

def _working( sid, persona ):
    return { "session_id": sid, "persona": persona, "state": "working", "stuck": False, "holding_on": "none" }

_NO_GRAPH = { "edges": { }, "cycles": [ ] }


# ── _attention_workers ─────────────────────────────────────────────────────────

class TestAttentionWorkers:
    def test_stuck_and_holders_in_working_excluded( self ):
        gw  = _Gateway()
        job = _job( gw, { } )
        fleet = {
            "s1": _stuck( "s1", "Stuckie" ),
            "s2": _working( "s2", "Holder" ),       # blocked holder (persona in edges)
            "s3": _working( "s3", "Busy" ),         # neither → excluded
        }
        graph = { "edges": { "Holder": "Peer" }, "cycles": [ ] }
        out = job._attention_workers( fleet, graph )
        personas = { v[ "persona" ] for v in out }
        assert personas == { "Stuckie", "Holder" }

    def test_non_dict_view_skipped( self ):
        job = _job( _Gateway(), { } )
        out = job._attention_workers( { "bad": "x", "ok": _stuck( "ok", "K" ) }, _NO_GRAPH )
        assert [ v[ "persona" ] for v in out ] == [ "K" ]


# ── tap firing / throttle ──────────────────────────────────────────────────────

class TestTapThrottle:
    def test_change_fires_tap( self ):
        gw  = _Gateway()
        job = _job( gw, { "s1": "Tiberius" } )
        fired = job._tap_managers( { "s1": _stuck( "s1", "Stuckie" ) }, _NO_GRAPH, [ ], NOW )
        assert fired == 1
        assert gw.sent[ 0 ][ 0 ] == "Tiberius"

    def test_no_change_suppresses( self ):
        gw  = _Gateway()
        job = _job( gw, { "s1": "Tiberius" } )
        fleet = { "s1": _stuck( "s1", "Stuckie" ) }
        job._tap_managers( fleet, _NO_GRAPH, [ ], NOW )                  # fires
        later = NOW + datetime.timedelta( seconds=10_000 )              # well past interval
        fired = job._tap_managers( fleet, _NO_GRAPH, [ ], later )        # identical crew → no change
        assert fired == 0 and len( gw.sent ) == 1

    def test_min_interval_rate_limits_a_change( self ):
        gw  = _Gateway()
        job = _job( gw, { "s1": "Tiberius", "s2": "Tiberius" }, min_interval=300 )
        job._tap_managers( { "s1": _stuck( "s1", "A" ) }, _NO_GRAPH, [ ], NOW )   # fires (first)
        # crew CHANGES (add s2) but only 60s later → within min-interval → suppressed
        changed = { "s1": _stuck( "s1", "A" ), "s2": _stuck( "s2", "B" ) }
        fired_soon = job._tap_managers( changed, _NO_GRAPH, [ ], NOW + datetime.timedelta( seconds=60 ) )
        assert fired_soon == 0
        # same change after the interval → fires
        fired_later = job._tap_managers( changed, _NO_GRAPH, [ ], NOW + datetime.timedelta( seconds=400 ) )
        assert fired_later == 1

    def test_per_group_routing_two_managers_two_dms( self ):
        gw  = _Gateway()
        job = _job( gw, { "s1": "MgrA", "s2": "MgrB" } )
        fleet = { "s1": _stuck( "s1", "A" ), "s2": _stuck( "s2", "B" ) }
        fired = job._tap_managers( fleet, _NO_GRAPH, [ ], NOW )
        assert fired == 2
        assert { r for r, _ in gw.sent } == { "MgrA", "MgrB" }

    def test_tap_includes_blocked_non_stuck_members( self ):
        gw  = _Gateway()
        job = _job( gw, { "s1": "MgrA" } )
        fleet = { "s1": _working( "s1", "Holder" ) }          # not stuck, but a blocked holder
        graph = { "edges": { "Holder": "Peer" }, "cycles": [ ] }
        fired = job._tap_managers( fleet, graph, [ ], NOW )
        assert fired == 1
        assert "Blocked: Holder" in gw.sent[ 0 ][ 1 ]

    def test_no_attention_no_tap( self ):
        gw  = _Gateway()
        job = _job( gw, { "s1": "Tiberius" } )
        fired = job._tap_managers( { "s1": _working( "s1", "Busy" ) }, _NO_GRAPH, [ ], NOW )
        assert fired == 0 and gw.sent == [ ]

    def test_unresolved_manager_escalates_no_dm( self ):
        gw, escalations = _Gateway(), [ ]
        job = _job( gw, { }, notify=lambda msg, *a, **k: escalations.append( msg ) )   # s1 not in map → unresolved
        fired = job._tap_managers( { "s1": _stuck( "s1", "Orphan" ) }, _NO_GRAPH, [ ], NOW )
        assert fired == 0 and gw.sent == [ ]
        assert len( escalations ) == 1 and "escalating to Rick" in escalations[ 0 ]


# ── advisory-only (never-auto-assign redline, Tiberius) ────────────────────────

class TestAdvisoryFraming:
    def test_tap_body_is_advisory_not_actuation( self ):
        gw  = _Gateway()
        job = _job( gw, { "s1": "Tiberius" } )
        job._tap_managers( { "s1": _stuck( "s1", "Stuckie" ) },
                           { "edges": { }, "cycles": [ [ "A", "B" ] ] }, [ "free1" ], NOW )
        body = gw.sent[ 0 ][ 1 ].lower()
        assert "advisory" in body and "recommend" in body and "do not assign" in body
        # zero actuation verbs in the recommendation body
        for verb in ( "assigned", "spawned", "reassigned", "dismissed", "i assigned", "i spawned" ):
            assert verb not in body
        assert "free" in body and "deadlock" in body   # carries the actionable counts


# ── B4/D4 manager-ack tracking (liveness-proxy → manager-down → escalate+HOLD) ──

def _iso( dt ):
    return dt.isoformat()


class TestManagerAckTracking:

    def test_fresh_activity_since_tap_is_acked( self ):
        gw, escal = _Gateway(), [ ]
        job = _job( gw, { }, notify=lambda m, *a, **k: escal.append( m ) )
        job._last_tap_at[ "Tiberius" ] = NOW
        job._manager_down_escalated.add( "Tiberius" )                 # pretend previously flagged
        who = [ { "persona_name": "Tiberius", "last_post_ts": _iso( NOW + datetime.timedelta( seconds=30 ) ) } ]
        down = job._check_manager_acks( NOW + datetime.timedelta( seconds=700 ), who )
        assert down == 0 and escal == [ ]
        assert "Tiberius" not in job._manager_down_escalated          # acked → flag cleared

    def test_no_activity_within_window_no_escalation( self ):
        gw, escal = _Gateway(), [ ]
        job = _job( gw, { }, notify=lambda m, *a, **k: escal.append( m ) )
        job._last_tap_at[ "Tiberius" ] = NOW
        who = [ { "persona_name": "Tiberius", "last_post_ts": _iso( NOW - datetime.timedelta( seconds=50 ) ) } ]
        down = job._check_manager_acks( NOW + datetime.timedelta( seconds=100 ), who )   # within 600s window
        assert down == 0 and escal == [ ]

    def test_manager_down_past_window_escalates_once( self ):
        gw, escal = _Gateway(), [ ]
        job = _job( gw, { }, notify=lambda m, *a, **k: escal.append( m ) )
        job._last_tap_at[ "Tiberius" ] = NOW
        who = [ ]                                                     # no activity at all since tap
        late = NOW + datetime.timedelta( seconds=700 )               # past 600s window
        down1 = job._check_manager_acks( late, who )
        assert down1 == 1 and len( escal ) == 1 and "MANAGER-DOWN" in escal[ 0 ] and "HOLD" in escal[ 0 ]
        # escalate-once: a second poll while still down does NOT re-escalate
        down2 = job._check_manager_acks( late + datetime.timedelta( seconds=60 ), who )
        assert down2 == 0 and len( escal ) == 1
        # HOLD: the manager-down path takes NO actuation (no DM/post from this method)
        assert gw.sent == [ ] and gw.posts == [ ]

    def test_reack_after_down_clears_flag( self ):
        gw, escal = _Gateway(), [ ]
        job = _job( gw, { }, notify=lambda m, *a, **k: escal.append( m ) )
        job._last_tap_at[ "Tiberius" ] = NOW
        late = NOW + datetime.timedelta( seconds=700 )
        job._check_manager_acks( late, [ ] )                          # → down, flagged
        assert "Tiberius" in job._manager_down_escalated
        who = [ { "persona_name": "Tiberius", "last_post_ts": _iso( NOW + datetime.timedelta( seconds=10 ) ) } ]
        job._check_manager_acks( late, who )                          # activity since tap → re-acked
        assert "Tiberius" not in job._manager_down_escalated

    def test_manager_last_activity_picks_most_recent_and_handles_edges( self ):
        job = _job( _Gateway(), { } )
        who = [
            { "persona_name": "Tiberius", "last_post_ts": _iso( NOW ) },
            { "persona_name": "Tiberius", "last_post_ts": _iso( NOW + datetime.timedelta( seconds=99 ) ) },
            { "persona_name": "Other",    "last_post_ts": _iso( NOW + datetime.timedelta( seconds=999 ) ) },
            "not-a-dict",
            { "persona_name": "Tiberius", "last_post_ts": "garbage-ts" },     # bad ts → ignored
            { "persona_name": "Tiberius" },                                   # no ts → ignored
        ]
        best = job._manager_last_activity( "Tiberius", who )
        assert best == NOW + datetime.timedelta( seconds=99 )
        assert job._manager_last_activity( "Nobody", who ) is None
        assert job._manager_last_activity( "Tiberius", None ) is None

    # ── bug 9694fb11: bridge-mtime is an implicit tap-ACK (active-but-silent mgr) ──

    def test_fresh_bridge_mtime_acks_commons_silent_manager( self ):
        """
        REPRODUCTION (bug 9694fb11): an actively-working manager whose bridge
        mtime is fresh (every PreToolUse bumps it) but who has posted NOTHING to
        commons must NOT trip MANAGER-DOWN — even when the 600s window has fully
        elapsed since the tap. Before the fix this false-escalated to Rick.
        """
        gw, escal = _Gateway(), [ ]
        job = _job( gw, { }, notify=lambda m, *a, **k: escal.append( m ) )
        job._last_tap_at[ "Tiberius" ] = NOW
        late = NOW + datetime.timedelta( seconds=700 )                 # past the 600s window
        # bridge bumped at +650s (still working) → fresh AT/AFTER the tap
        fresh = ( NOW + datetime.timedelta( seconds=650 ) ).timestamp()
        job._bridge_mtime_fn = lambda sid: fresh
        fleet_view = { "s1": { "session_id": "s1", "persona": "Tiberius" } }
        down = job._check_manager_acks( late, [ ], fleet_view )        # who=[] → ZERO commons activity
        assert down == 0 and escal == [ ]
        assert "Tiberius" not in job._manager_down_escalated

    def test_stale_bridge_mtime_no_commons_still_downs( self ):
        """Regression guard: a bridge mtime OLDER than the tap is not a valid
        ACK — with no commons activity either, MANAGER-DOWN still fires."""
        gw, escal = _Gateway(), [ ]
        job = _job( gw, { }, notify=lambda m, *a, **k: escal.append( m ) )
        job._last_tap_at[ "Tiberius" ] = NOW
        late  = NOW + datetime.timedelta( seconds=700 )
        stale = ( NOW - datetime.timedelta( seconds=50 ) ).timestamp()  # before the tap
        job._bridge_mtime_fn = lambda sid: stale
        fleet_view = { "s1": { "session_id": "s1", "persona": "Tiberius" } }
        down = job._check_manager_acks( late, [ ], fleet_view )
        assert down == 1 and len( escal ) == 1 and "MANAGER-DOWN" in escal[ 0 ]

    def test_no_bridge_no_commons_still_downs( self ):
        """Regression guard: no resolvable bridge (mtime None) AND no commons
        activity → MANAGER-DOWN still fires (the genuine down case)."""
        gw, escal = _Gateway(), [ ]
        job = _job( gw, { }, notify=lambda m, *a, **k: escal.append( m ) )
        job._last_tap_at[ "Tiberius" ] = NOW
        late = NOW + datetime.timedelta( seconds=700 )
        job._bridge_mtime_fn = lambda sid: None                        # no bridge resolves
        fleet_view = { "s1": { "session_id": "s1", "persona": "Tiberius" } }
        down = job._check_manager_acks( late, [ ], fleet_view )
        assert down == 1 and "MANAGER-DOWN" in escal[ 0 ]

    def test_manager_bridge_activity_picks_freshest_and_handles_edges( self ):
        """Direct unit of the helper: freshest mtime across the manager's
        sessions wins; non-dict views, persona mismatches, missing session_id,
        unresolved bridges (None), and un-convertible mtimes are all skipped."""
        job  = _job( _Gateway(), { } )
        base = NOW.timestamp()
        mtimes = {
            "s-new"    : base + 99,
            "s-old"    : base + 10,     # older than s-new → does NOT update best
            "s-newest" : base + 150,    # newest → updates best
            "s-none"   : None,          # no bridge resolves → skipped
            "s-bad"    : "garbage",     # fromtimestamp raises (TypeError) → skipped
        }
        job._bridge_mtime_fn = lambda sid: mtimes.get( sid )
        fleet_view = {
            "s-new"    : { "session_id": "s-new",    "persona": "Tiberius" },
            "s-old"    : { "session_id": "s-old",    "persona": "Tiberius" },
            "s-newest" : { "session_id": "s-newest", "persona": "Tiberius" },
            "s-none"   : { "session_id": "s-none",   "persona": "Tiberius" },
            "s-bad"    : { "session_id": "s-bad",    "persona": "Tiberius" },
            "s-other"  : { "session_id": "s-other",  "persona": "SomeoneElse" },  # persona mismatch
            "s-nosid"  : { "persona": "Tiberius" },                               # no session_id → None
            "not-dict" : "x",                                                     # non-dict view → skipped
        }
        best = job._manager_bridge_activity( "Tiberius", fleet_view )
        assert best == datetime.datetime.fromtimestamp( base + 150, tz=datetime.timezone.utc )
        assert job._manager_bridge_activity( "Nobody",   fleet_view ) is None    # no persona match
        assert job._manager_bridge_activity( "Tiberius", None )       is None    # None fleet_view


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
