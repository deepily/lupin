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
from lupin_mcp.persona_normalization import canonical_persona_key


NOW = datetime.datetime( 2026, 6, 6, 22, 0, 0, tzinfo=datetime.timezone.utc )


def _bridge_key( persona ):
    """The canonical key the per-poll bridge_mtimes map is keyed by (bug bf8c5cbb)."""
    return canonical_persona_key( persona ) or persona


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


def _stuck( sid, persona, alive=True ):
    return { "session_id": sid, "persona": persona, "state": "stuck", "stuck": True,
             "holding_on": "none", "alive": alive }

def _working( sid, persona, alive=True ):
    return { "session_id": sid, "persona": persona, "state": "working", "stuck": False,
             "holding_on": "none", "alive": alive }

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

    def test_reaped_offline_stuck_pruned( self ):
        # lane 4: a stuck-but-non-alive view (reaped/offline phantom) is EXCLUDED
        # from the attention roster — the manager-tap token-burn fix.
        job   = _job( _Gateway(), { } )
        fleet = {
            "live": _stuck( "live", "Stuckie" ),
            "dead": _stuck( "dead", "Rio", alive=False ),   # reaped/offline → pruned
        }
        out = job._attention_workers( fleet, _NO_GRAPH )
        assert { v[ "persona" ] for v in out } == { "Stuckie" }

    def test_offline_holder_pruned( self ):
        # a non-alive holder (stale `holding_on: peer:X` on a dead session) whose
        # persona is in the blocker edges is STILL excluded — alive gates first.
        job   = _job( _Gateway(), { } )
        fleet = {
            "live": _working( "live", "Holder" ),
            "dead": _working( "dead", "Ghost", alive=False ),
        }
        graph = { "edges": { "Holder": "Peer", "Ghost": "Peer" }, "cycles": [ ] }
        out   = job._attention_workers( fleet, graph )
        assert { v[ "persona" ] for v in out } == { "Holder" }

    # ── bug bbce7e2f: live-peer waits are a legit dependency, not a stall ────────

    def test_holder_awaiting_live_peer_excluded( self ):
        # REPRODUCTION (bug bbce7e2f): a non-stuck holder awaiting a peer that is
        # ITSELF alive (Rio actively building) is a legit in-flight dependency —
        # EXCLUDED from the attention roster (no spurious "blocked" → no -r2 echo).
        job   = _job( _Gateway(), { } )
        fleet = {
            "h":   _working( "h", "MrRadio" ),       # awaiting peer:Rio
            "rio": _working( "rio", "Rio" ),         # the awaited peer — ALIVE, building
        }
        graph = { "edges": { "MrRadio": "Rio" }, "cycles": [ ] }
        out   = job._attention_workers( fleet, graph )
        assert out == [ ]                            # live-peer wait → nobody needs attention

    def test_holder_awaiting_dead_peer_kept( self ):
        # the awaited peer is in the fleet but NON-alive (reaped) → genuine block
        # on a dead blocker → the holder is KEPT (fail-safe: never hide a block).
        job   = _job( _Gateway(), { } )
        fleet = {
            "h":     _working( "h", "Waiter" ),                  # awaiting peer:Ghost
            "ghost": _working( "ghost", "Ghost", alive=False ), # awaited peer — DEAD
        }
        graph = { "edges": { "Waiter": "Ghost" }, "cycles": [ ] }
        out   = job._attention_workers( fleet, graph )
        assert { v[ "persona" ] for v in out } == { "Waiter" }

    def test_holder_awaiting_absent_peer_kept( self ):
        # the awaited peer is not in the fleet at all (unknown) → treated as NOT
        # alive → the holder is KEPT (fail-safe).
        job   = _job( _Gateway(), { } )
        fleet = { "h": _working( "h", "Waiter" ) }              # awaiting an absent peer
        graph = { "edges": { "Waiter": "Nobody" }, "cycles": [ ] }
        out   = job._attention_workers( fleet, graph )
        assert { v[ "persona" ] for v in out } == { "Waiter" }

    def test_deadlock_cycle_member_kept_even_with_live_peer( self ):
        # a mutual deadlock (A↔B, both alive) is a REAL stall — both members are
        # KEPT even though each awaits a LIVE peer (the cycle guard wins). The
        # store-backed :1018 escalation owns the cycle byte-identically; this
        # only ensures the manager-tap roster still surfaces it.
        job   = _job( _Gateway(), { } )
        fleet = {
            "a": _working( "a", "Ann" ),
            "b": _working( "b", "Bob" ),
        }
        graph = { "edges": { "Ann": "Bob", "Bob": "Ann" }, "cycles": [ [ "Ann", "Bob" ] ] }
        out   = job._attention_workers( fleet, graph )
        assert { v[ "persona" ] for v in out } == { "Ann", "Bob" }

    def test_stuck_holder_awaiting_live_peer_still_kept( self ):
        # a STUCK session that also happens to await a live peer is KEPT — stuck
        # always needs attention regardless of the peer's liveness.
        job   = _job( _Gateway(), { } )
        fleet = {
            "s":   _stuck( "s", "Stuckie" ),         # stuck AND awaiting peer:Rio
            "rio": _working( "rio", "Rio" ),
        }
        graph = { "edges": { "Stuckie": "Rio" }, "cycles": [ ] }
        out   = job._attention_workers( fleet, graph )
        assert { v[ "persona" ] for v in out } == { "Stuckie" }

    # ── bug bf8c5cbb: bridge-mtime veto extended to the blocked-roster ──────────
    # The awaited peer reads view alive=False (comms-silent / heads-down) but its
    # session-bridge mtime is FRESH → it IS alive → the wait is a legit in-flight
    # dependency → EXCLUDE (the 26dd3afb bridge-veto applied to _attention_workers).
    # Threads the per-poll bridge_mtimes map (fail-safe: None ⇒ current behavior).

    def test_holder_awaiting_bridge_fresh_but_comms_silent_peer_excluded( self ):
        """THE REPRO (Rachel case): holder awaits a peer whose view.alive is False
        (comms-silent) but whose bridge mtime is fresh → excluded, not rostered."""
        job   = _job( _Gateway(), { } )
        fleet = {
            "h":    _working( "h", "Rachel" ),                    # awaiting peer:Busy (Rachel NOT in bridge map)
            "busy": _working( "busy", "Busy", alive=False ),      # comms-silent view…
            "bad":  "not-a-dict",                                 # augmentation loop skips non-dicts
        }
        graph = { "edges": { "Rachel": "Busy" }, "cycles": [ ] }
        bridge_mtimes = { _bridge_key( "Busy" ): NOW.timestamp() - 60 }   # …but bridge fresh (60s)
        out   = job._attention_workers( fleet, graph, now=NOW, bridge_mtimes=bridge_mtimes )
        assert out == [ ]                                         # bridge-fresh peer → excluded

    def test_holder_awaiting_stale_bridge_peer_kept( self ):
        """A stale-bridge peer (mtime older than the threshold) does NOT count alive
        → the holder is KEPT (genuine block; the veto is freshness-gated)."""
        job   = _job( _Gateway(), { } )
        fleet = {
            "h":    _working( "h", "Rachel" ),
            "busy": _working( "busy", "Busy", alive=False ),
        }
        graph = { "edges": { "Rachel": "Busy" }, "cycles": [ ] }
        bridge_mtimes = { _bridge_key( "Busy" ): NOW.timestamp() - 99999 }   # stale bridge
        out   = job._attention_workers( fleet, graph, now=NOW, bridge_mtimes=bridge_mtimes )
        assert { v[ "persona" ] for v in out } == { "Rachel" }

    def test_bridge_mtimes_none_inert_dead_peer_kept( self ):
        """Fail-safe: bridge_mtimes None (seam unwired / read failed) ⇒ no augmentation
        ⇒ today's behavior — a comms-silent (non-alive) awaited peer keeps the holder."""
        job   = _job( _Gateway(), { } )
        fleet = {
            "h":    _working( "h", "Rachel" ),
            "busy": _working( "busy", "Busy", alive=False ),
        }
        graph = { "edges": { "Rachel": "Busy" }, "cycles": [ ] }
        out   = job._attention_workers( fleet, graph, now=NOW, bridge_mtimes=None )
        assert { v[ "persona" ] for v in out } == { "Rachel" }

    def test_holder_awaiting_future_bridge_peer_kept( self ):
        """097778b8: a FUTURE bridge mtime (clock skew/corruption ⇒ negative age)
        must NOT count the peer alive — without the 0<=age lower bound a negative
        age slips under the threshold and falsely excludes the holder. Fail toward
        rostering: the holder is KEPT."""
        job   = _job( _Gateway(), { } )
        fleet = {
            "h":    _working( "h", "Rachel" ),
            "busy": _working( "busy", "Busy", alive=False ),
        }
        graph = { "edges": { "Rachel": "Busy" }, "cycles": [ ] }
        bridge_mtimes = { _bridge_key( "Busy" ): NOW.timestamp() + 60 }   # future mtime → age -60
        out   = job._attention_workers( fleet, graph, now=NOW, bridge_mtimes=bridge_mtimes )
        assert { v[ "persona" ] for v in out } == { "Rachel" }            # negative age ⇒ not alive ⇒ kept


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

    def test_live_peer_waiters_produce_no_tap( self ):
        # END-TO-END repro (bug bbce7e2f): MrRadio and Cheech both awaiting a LIVE
        # Rio (actively building) must NOT generate a "N blocked / cajole" tap —
        # the spurious advisory that was re-sent as a stale-ts -r2 never fires.
        gw  = _Gateway()
        job = _job( gw, { "s1": "MgrA", "s2": "MgrA" } )
        fleet = {
            "s1":  _working( "s1", "MrRadio" ),     # awaiting peer:Rio
            "s2":  _working( "s2", "Cheech" ),      # awaiting peer:Rio
            "rio": _working( "rio", "Rio" ),        # ALIVE, building
        }
        graph = { "edges": { "MrRadio": "Rio", "Cheech": "Rio" }, "cycles": [ ] }
        fired = job._tap_managers( fleet, graph, [ "rio" ], NOW )
        assert fired == 0 and gw.sent == [ ]

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
        # zero CLAIMED-actuation verbs in the recommendation body. The MANAGE-not-BUILD
        # revision (2026-06-29) RECOMMENDS the manager "spawn/assign" and names
        # "unassigned work" — both advisory, allowed — so the redline is pinned on the
        # first-person completed-action claim (what the arbiter must NEVER say it did),
        # not the bare verb stem (which legitimately appears inside "unassigned").
        for verb in ( "i assigned", "i spawned", "i reassigned", "i dismissed", "i reaped" ):
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

    def test_manager_liveness_activity_picks_freshest_and_handles_edges( self ):
        """Direct unit of the 5-signal helper (bug e8f40042): the freshest of the
        full union (bridge + event + commons + idle_prompt + dm) across the
        manager's session rows wins, converted back to an absolute datetime;
        canonical_persona_key matching (mixed-case spelling), count_dm gating,
        non-dict views, persona mismatches, missing session_id, and rows with NO
        signal at all are all handled. The OLD _manager_bridge_activity saw only
        bridge — this helper is the single-source-of-truth replacement."""
        job  = _job( _Gateway(), { } )
        now  = NOW + datetime.timedelta( seconds=700 )
        # bridge mtime on one row (oldest signal); a FRESHER event/dm on others.
        mtimes = { "s-bridge": ( now - datetime.timedelta( seconds=400 ) ).timestamp(),
                   "s-event" : None, "s-dm": None, "s-bare": None, "s-other": None }
        job._bridge_mtime_fn = lambda sid: mtimes.get( sid )
        fleet_view = {
            "s-bridge" : { "session_id": "s-bridge", "persona": "Tiberius" },                         # bridge_age 400
            "s-event"  : { "session_id": "s-event",  "persona": "tiberius",                           # canon-match (mixed case)
                           "last_event_ts": now - datetime.timedelta( seconds=200 ) },                # event_age 200
            "s-dm"     : { "session_id": "s-dm",     "persona": "Tiberius",
                           "dm_ts": now - datetime.timedelta( seconds=30 ) },                         # dm_age 30 (freshest)
            "s-stale"  : { "session_id": "s-stale",  "persona": "Tiberius",                           # OLDER than running best
                           "last_event_ts": now - datetime.timedelta( seconds=500 ) },                # → does NOT update best
            "s-bare"   : { "session_id": "s-bare",   "persona": "Tiberius" },                         # NO signal → skipped
            "s-other"  : { "session_id": "s-other",  "persona": "SomeoneElse",                        # persona mismatch → skipped
                           "dm_ts": now - datetime.timedelta( seconds=1 ) },
            "not-dict" : "x",                                                                          # non-dict → skipped
        }
        # count_dm=True → dm (age 30) is freshest across the matched rows.
        best = job._manager_liveness_activity( "Tiberius", fleet_view, now, count_dm=True )
        assert best == now - datetime.timedelta( seconds=30 )
        # count_dm=False → dm excluded; freshest of the remaining union is event (age 200).
        best_no_dm = job._manager_liveness_activity( "Tiberius", fleet_view, now, count_dm=False )
        assert best_no_dm == now - datetime.timedelta( seconds=200 )
        # no persona match / None fleet_view → None.
        assert job._manager_liveness_activity( "Nobody",   fleet_view, now, count_dm=True ) is None
        assert job._manager_liveness_activity( "Tiberius", None,       now, count_dm=True ) is None

    # ── bug e8f40042: tap-ACK must consume the FULL 5-signal union, not {commons,bridge} ──

    def test_dm_only_manager_not_false_downed( self ):
        """
        REPRODUCTION (bug e8f40042): a coordination-only manager whose ONLY sign
        of life is a sent DM (dm_age fresh) — silent on commons AND with a stale
        bridge (no Read/Edit/Bash to bump it) — was false-DOWNed every window by
        the OLD {commons, bridge}-only ACK. With the 5-signal union it ACKs.
        This is exactly María's divergence check.
        """
        gw, escal = _Gateway(), [ ]
        job = _job( gw, { }, notify=lambda m, *a, **k: escal.append( m ) )
        job._last_tap_at[ "Tiberius" ] = NOW
        late  = NOW + datetime.timedelta( seconds=700 )                  # past the 600s window
        stale = ( NOW - datetime.timedelta( seconds=50 ) ).timestamp()   # bridge OLDER than the tap
        job._bridge_mtime_fn = lambda sid: stale
        # dm_ts fresh AT/AFTER the tap; commons (who) empty; no event/idle signal.
        fleet_view = { "s1": { "session_id": "s1", "persona": "Tiberius",
                               "dm_ts": NOW + datetime.timedelta( seconds=650 ) } }
        down = job._check_manager_acks( late, [ ], fleet_view, count_dm=True )
        assert down == 0 and escal == [ ]
        assert "Tiberius" not in job._manager_down_escalated

    def test_dm_only_manager_downs_when_dm_toggle_off( self ):
        """NEGATIVE CONTROL: the SAME DM-only manager — fresh dm, stale bridge,
        no commons/event — DOES down when count_dm=False (the runtime toggle
        `arbiter count dm as liveness` off), proving the DM signal is what saved
        it above and that count_dm is honored end-to-end."""
        gw, escal = _Gateway(), [ ]
        job = _job( gw, { }, notify=lambda m, *a, **k: escal.append( m ) )
        job._last_tap_at[ "Tiberius" ] = NOW
        late  = NOW + datetime.timedelta( seconds=700 )
        stale = ( NOW - datetime.timedelta( seconds=50 ) ).timestamp()
        job._bridge_mtime_fn = lambda sid: stale
        fleet_view = { "s1": { "session_id": "s1", "persona": "Tiberius",
                               "dm_ts": NOW + datetime.timedelta( seconds=650 ) } }
        down = job._check_manager_acks( late, [ ], fleet_view, count_dm=False )
        assert down == 1 and len( escal ) == 1 and "MANAGER-DOWN" in escal[ 0 ]

    def test_fresh_stop_event_acks_commons_and_bridge_silent_manager( self ):
        """The event_age fold (bug e8f40042): a manager whose only fresh signal is
        a STOP event (last_event_ts) — stale bridge, empty commons, no dm — ACKs.
        The OLD {commons, bridge}-only path false-DOWNed it."""
        gw, escal = _Gateway(), [ ]
        job = _job( gw, { }, notify=lambda m, *a, **k: escal.append( m ) )
        job._last_tap_at[ "Tiberius" ] = NOW
        late  = NOW + datetime.timedelta( seconds=700 )
        stale = ( NOW - datetime.timedelta( seconds=50 ) ).timestamp()
        job._bridge_mtime_fn = lambda sid: stale
        fleet_view = { "s1": { "session_id": "s1", "persona": "Tiberius",
                               "last_event_ts": NOW + datetime.timedelta( seconds=640 ) } }
        down = job._check_manager_acks( late, [ ], fleet_view, count_dm=True )
        assert down == 0 and escal == [ ]


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
