#!/usr/bin/env python3
"""
Unit tests for L1 (2026-06-17) — arbiter detector gaps: store-aware suppression
of the two false-escalating detectors (D4 MANAGER-DOWN tap-ACK + D3 WHOLE-FLEET-
STALL). Design: src/rnd/v0.1.8/2026.06.17-arbiter-detector-gaps-L1/01-build-plan.md.

Covers the full changed surface with a MOCKED owed_work_fn:
  - _item_is_user_gated      — the per-item Rick-gated predicate (all branches)
  - _holding_on_by_persona   — the degrade-safe corroboration source
  - _classify_owed           — BLOCKED_ON_USER / DONE / ACTIVE / UNKNOWN + the
                               store-raises-swallowed + seam-unwired fail-SAFE paths
  - _check_manager_acks      — advisory-once suppression for BLOCKED_ON_USER / DONE;
                               ACTIVE / UNKNOWN still escalate; UNKNOWN + holding_on
                               "user:" corroboration note; re-ack clears all flags
  - _has_live_owed_work      — BLOCKED_ON_USER exclusion (+ no-owed-class fail-safe)
  - _check_fleet_stall       — only-Rick-gated live work never stalls; normal does
  - _poll_once               — the one-read-per-poll classification wiring
"""
import datetime
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_job import (
    ArbiterConsumerJob,
    CLASS_BLOCKED_ON_USER, CLASS_DONE, CLASS_ACTIVE, CLASS_UNKNOWN,
)


NOW  = datetime.datetime( 2026, 6, 17, 12, 0, 0, tzinfo=datetime.timezone.utc )
LATE = NOW + datetime.timedelta( seconds=700 )      # past the default 600s ack window


class _Gateway:
    def __init__( self ):
        self.sent, self.posts = [ ], [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, recipient, body, metadata=None ): self.sent.append( ( recipient, body ) )
    def post( self, topic, body ): self.posts.append( ( topic, body ) )
    def read( self, topic, since=None, limit=50 ): return [ ]


def _job( *, owed_work_fn=None, notify=None ):
    """Bare arbiter job with no bridge liveness (bridge_mtime_fn → None), so the
    tap-ACK path always reaches the window/classification logic under test."""
    return ArbiterConsumerJob(
        commons         = _Gateway(),
        poll_seconds    = 5,
        manager_recipient = "DeclaredMgr",
        owed_work_fn    = owed_work_fn,
        bridge_mtime_fn = lambda sid: None,
        notify_fn       = notify or ( lambda *a, **k: None ),
    )


# ── owed-item shapes ─────────────────────────────────────────────────────────
def _operator( ): return { "id": "i1", "status": "in_progress", "gate_class": "operator", "blocked_by": None }
def _blocked_user(): return { "id": "i2", "status": "blocked", "gate_class": "none",
                              "blocked_by": [ { "kind": "user", "id": "rick" } ] }
def _normal(      ): return { "id": "i3", "status": "in_progress", "gate_class": "none", "blocked_by": None }


# ── _item_is_user_gated ──────────────────────────────────────────────────────
class TestItemIsUserGated:

    def test_operator_is_user_gated( self ):
        assert ArbiterConsumerJob._item_is_user_gated( _operator() ) is True

    def test_blocked_with_user_ref_is_user_gated( self ):
        assert ArbiterConsumerJob._item_is_user_gated( _blocked_user() ) is True

    def test_normal_item_not_user_gated( self ):
        assert ArbiterConsumerJob._item_is_user_gated( _normal() ) is False

    def test_blocked_but_peer_ref_not_user_gated( self ):
        item = { "status": "blocked", "gate_class": "none",
                 "blocked_by": [ { "kind": "persona", "id": "tiffany" } ] }
        assert ArbiterConsumerJob._item_is_user_gated( item ) is False

    def test_blocked_with_malformed_refs_not_user_gated( self ):
        # non-dict ref + None blocked_by are both skipped → not gated
        assert ArbiterConsumerJob._item_is_user_gated(
            { "status": "blocked", "blocked_by": [ "not-a-dict" ] } ) is False
        assert ArbiterConsumerJob._item_is_user_gated(
            { "status": "blocked", "blocked_by": None } ) is False

    def test_non_dict_item_not_user_gated( self ):
        assert ArbiterConsumerJob._item_is_user_gated( "not-a-dict" ) is False


# ── _holding_on_by_persona ───────────────────────────────────────────────────
class TestHoldingOnByPersona:

    def test_collects_string_holding_on_per_persona( self ):
        fv = {
            "s1": { "persona": "Mgr", "holding_on": "user:rick" },
            "s2": { "persona": "Wkr", "holding_on": "none" },
            "s3": { "persona": "NoHold" },                 # no holding_on key → skipped
            "s4": { "holding_on": "user:rick" },           # no persona → skipped
            "s5": "not-a-dict",                            # non-dict → skipped
            "s6": { "persona": "Bad", "holding_on": 123 }, # non-str holding_on → skipped
        }
        out = ArbiterConsumerJob._holding_on_by_persona( fv )
        assert out == { "Mgr": "user:rick", "Wkr": "none" }

    def test_none_fleet_view_is_empty( self ):
        assert ArbiterConsumerJob._holding_on_by_persona( None ) == { }


# ── _classify_owed ───────────────────────────────────────────────────────────
class TestClassifyOwed:

    def test_all_operator_is_blocked_on_user( self ):
        job = _job( owed_work_fn=lambda ps: { "Mgr": [ _operator(), _operator() ] } )
        assert job._classify_owed( [ "Mgr" ], { } ) == { "Mgr": CLASS_BLOCKED_ON_USER }

    def test_all_blocked_on_user_refs_is_blocked_on_user( self ):
        job = _job( owed_work_fn=lambda ps: { "Mgr": [ _blocked_user() ] } )
        assert job._classify_owed( [ "Mgr" ], { } ) == { "Mgr": CLASS_BLOCKED_ON_USER }

    def test_mixed_one_normal_item_is_active( self ):
        # the AC: one non-Rick-gated owed item ⇒ NOT suppressed (ACTIVE)
        job = _job( owed_work_fn=lambda ps: { "Mgr": [ _operator(), _normal() ] } )
        assert job._classify_owed( [ "Mgr" ], { } ) == { "Mgr": CLASS_ACTIVE }

    def test_empty_owed_list_is_done( self ):
        job = _job( owed_work_fn=lambda ps: { "Mgr": [ ] } )
        assert job._classify_owed( [ "Mgr" ], { } ) == { "Mgr": CLASS_DONE }

    def test_persona_absent_from_result_is_unknown( self ):
        job = _job( owed_work_fn=lambda ps: { } )           # reader returned nothing for Mgr
        assert job._classify_owed( [ "Mgr" ], { } ) == { "Mgr": CLASS_UNKNOWN }

    def test_seam_unwired_is_unknown_fail_safe( self ):
        job = _job( owed_work_fn=None )                     # no reader → never called
        assert job._classify_owed( [ "Mgr" ], { } ) == { "Mgr": CLASS_UNKNOWN }

    def test_store_raises_is_swallowed_to_unknown( self ):
        def _boom( personas ):
            raise RuntimeError( "store down" )
        job = _job( owed_work_fn=_boom )
        # observer invariant: never raises; every persona fails SAFE to UNKNOWN
        assert job._classify_owed( [ "Mgr", "Other" ], { } ) == {
            "Mgr": CLASS_UNKNOWN, "Other": CLASS_UNKNOWN }

    def test_empty_personas_skips_reader_call( self ):
        calls = [ ]
        def _reader( personas ):
            calls.append( personas )
            return { }
        job = _job( owed_work_fn=_reader )
        assert job._classify_owed( [ ], { } ) == { }
        assert job._classify_owed( [ None, "" ], { } ) == { }   # falsy names filtered out
        assert calls == [ ]                                     # reader never called with no names

    def test_multiple_personas_classified_independently( self ):
        owed = { "A": [ _operator() ], "B": [ _normal() ], "C": [ ] }
        job  = _job( owed_work_fn=lambda ps: owed )
        assert job._classify_owed( [ "A", "B", "C" ], { } ) == {
            "A": CLASS_BLOCKED_ON_USER, "B": CLASS_ACTIVE, "C": CLASS_DONE }


# ── _check_manager_acks — store-aware suppression ────────────────────────────
class TestManagerAcksSuppression:

    def _tapped( self, escal, owed_work_fn=None ):
        job = _job( owed_work_fn=owed_work_fn, notify=lambda m, *a, **k: escal.append( m ) )
        job._last_tap_at[ "Mgr" ] = NOW
        return job

    def test_blocked_on_user_suppresses_manager_down_advisory_once( self ):
        escal = [ ]
        job   = self._tapped( escal )
        oc    = { "Mgr": CLASS_BLOCKED_ON_USER }
        down1 = job._check_manager_acks( LATE, [ ], None, [ "OtherMgr" ], owed_class=oc )
        assert down1 == 0                                      # NOT a manager-down
        assert len( escal ) == 1 and "AWAITING-RICK" in escal[ 0 ]
        assert "Mgr" in job._manager_blocked_advised
        assert "Mgr" not in job._manager_down_escalated
        # advisory-once: a second poll still blocked does NOT re-advise
        down2 = job._check_manager_acks( LATE + datetime.timedelta( seconds=60 ), [ ], None, [ ], owed_class=oc )
        assert down2 == 0 and len( escal ) == 1

    def test_done_suppresses_manager_down_reap_advisory_once( self ):
        escal = [ ]
        job   = self._tapped( escal )
        oc    = { "Mgr": CLASS_DONE }
        down1 = job._check_manager_acks( LATE, [ ], None, [ ], owed_class=oc )
        assert down1 == 0
        assert len( escal ) == 1 and "MANAGER-DONE" in escal[ 0 ] and "reaping" in escal[ 0 ].lower()
        assert "Mgr" in job._manager_done_advised
        down2 = job._check_manager_acks( LATE + datetime.timedelta( seconds=60 ), [ ], None, [ ], owed_class=oc )
        assert down2 == 0 and len( escal ) == 1

    def test_active_still_escalates_manager_down( self ):
        escal = [ ]
        job   = self._tapped( escal )
        down  = job._check_manager_acks( LATE, [ ], None, [ ], owed_class={ "Mgr": CLASS_ACTIVE } )
        assert down == 1 and "MANAGER-DOWN" in escal[ 0 ]
        assert "(holding_on=" not in escal[ 0 ]                # ACTIVE → no corroboration note

    def test_unknown_fails_safe_to_manager_down( self ):
        escal = [ ]
        job   = self._tapped( escal )
        # owed_class empty → Mgr defaults to UNKNOWN → today's behavior (escalates)
        down  = job._check_manager_acks( LATE, [ ], None, [ ], owed_class={ } )
        assert down == 1 and "MANAGER-DOWN" in escal[ 0 ]

    def test_unknown_with_user_holding_adds_corroboration_note( self ):
        escal = [ ]
        job   = self._tapped( escal )
        fv    = { "s1": { "session_id": "s1", "persona": "Mgr", "holding_on": "user:rick" } }
        down  = job._check_manager_acks( LATE, [ ], fv, [ ], owed_class={ "Mgr": CLASS_UNKNOWN } )
        assert down == 1
        assert "holding_on=user:rick" in escal[ 0 ] and "to be SAFE" in escal[ 0 ]

    def test_unknown_without_user_holding_has_no_note( self ):
        escal = [ ]
        job   = self._tapped( escal )
        fv    = { "s1": { "session_id": "s1", "persona": "Mgr", "holding_on": "peer:x" } }
        down  = job._check_manager_acks( LATE, [ ], fv, [ ], owed_class={ "Mgr": CLASS_UNKNOWN } )
        assert down == 1 and "(holding_on=" not in escal[ 0 ]

    def test_window_not_elapsed_no_classification_or_escalation( self ):
        escal = [ ]
        job   = self._tapped( escal )
        early = NOW + datetime.timedelta( seconds=100 )       # within 600s window
        down  = job._check_manager_acks( early, [ ], None, [ ], owed_class={ "Mgr": CLASS_ACTIVE } )
        assert down == 0 and escal == [ ]

    def test_reack_clears_all_three_flags( self ):
        escal = [ ]
        job   = self._tapped( escal )
        # first: blocked-on-user advisory fires
        job._check_manager_acks( LATE, [ ], None, [ ], owed_class={ "Mgr": CLASS_BLOCKED_ON_USER } )
        assert job._manager_blocked_advised == { "Mgr" }
        # manager later shows commons activity AFTER its tap → re-acked, all flags clear
        who = [ { "persona_name": "Mgr",
                  "last_post_ts": ( NOW + datetime.timedelta( seconds=10 ) ).isoformat() } ]
        job._check_manager_acks( LATE, who, None, [ ], owed_class={ "Mgr": CLASS_BLOCKED_ON_USER } )
        assert job._manager_blocked_advised == set()
        assert job._manager_done_advised    == set()
        assert job._manager_down_escalated  == set()

    def test_default_owed_class_none_preserves_legacy_behavior( self ):
        # no owed_class arg at all (legacy callers) → UNKNOWN → escalates as before
        escal = [ ]
        job   = self._tapped( escal )
        down  = job._check_manager_acks( LATE, [ ] )
        assert down == 1 and "MANAGER-DOWN" in escal[ 0 ]


# ── _has_live_owed_work — BLOCKED_ON_USER exclusion ──────────────────────────
def _live( sid, persona, state="working" ):
    return { "session_id": sid, "persona": persona, "state": state, "alive": True, "holding_on": "none" }


class TestHasLiveOwedWork:

    def test_blocked_on_user_session_excluded( self ):
        fv = { "s1": _live( "s1", "Mgr", "holding" ) }
        assert ArbiterConsumerJob._has_live_owed_work( fv, { "Mgr": CLASS_BLOCKED_ON_USER } ) is False

    def test_active_session_counts_as_live_owed( self ):
        fv = { "s1": _live( "s1", "Mgr" ) }
        assert ArbiterConsumerJob._has_live_owed_work( fv, { "Mgr": CLASS_ACTIVE } ) is True

    def test_mixed_active_present_still_true( self ):
        fv = { "s1": _live( "s1", "Blocked", "holding" ), "s2": _live( "s2", "Active" ) }
        oc = { "Blocked": CLASS_BLOCKED_ON_USER, "Active": CLASS_ACTIVE }
        assert ArbiterConsumerJob._has_live_owed_work( fv, oc ) is True

    def test_no_owed_class_preserves_legacy_behavior( self ):
        fv = { "s1": _live( "s1", "Mgr", "holding" ) }
        assert ArbiterConsumerJob._has_live_owed_work( fv ) is True            # no class → not excluded

    def test_dead_session_never_counts( self ):
        fv = { "s1": { "session_id": "s1", "persona": "Mgr", "state": "working", "alive": False } }
        assert ArbiterConsumerJob._has_live_owed_work( fv, { } ) is False

    def test_session_without_persona_counts_when_live( self ):
        # persona None → the exclusion check is skipped → live owed work stands
        fv = { "s1": { "session_id": "s1", "state": "working", "alive": True } }
        assert ArbiterConsumerJob._has_live_owed_work( fv, { } ) is True


# ── _check_fleet_stall — owed_class threaded through ─────────────────────────
class TestFleetStallSuppression:

    def _settle( self, job, fv ):
        """Two calls at the same signature so _last_progress_at is armed and the
        window can elapse without a signature change resetting the timer."""
        job._check_fleet_stall( fv, NOW, [ ], owed_class={ } )

    def test_only_blocked_on_user_live_work_never_stalls( self ):
        escal = [ ]
        job   = _job( notify=lambda m, *a, **k: escal.append( m ) )
        fv    = { "s1": _live( "s1", "Mgr", "holding" ) }
        oc    = { "Mgr": CLASS_BLOCKED_ON_USER }
        job._check_fleet_stall( fv, NOW, [ ], owed_class=oc )                  # arm timer
        out   = job._check_fleet_stall( fv, NOW + datetime.timedelta( seconds=2000 ), [ ], owed_class=oc )
        assert out == 0 and escal == [ ]                                       # Rick-gated → not a stall

    def test_normal_live_work_stalls_past_window( self ):
        escal = [ ]
        job   = _job( notify=lambda m, *a, **k: escal.append( m ) )
        fv    = { "s1": _live( "s1", "Mgr" ) }
        oc    = { "Mgr": CLASS_ACTIVE }
        job._check_fleet_stall( fv, NOW, [ ], owed_class=oc )                  # arm timer
        out   = job._check_fleet_stall( fv, NOW + datetime.timedelta( seconds=2000 ), [ ], owed_class=oc )
        assert out == 1 and "WHOLE-FLEET-STALL" in escal[ 0 ]


# ── _poll_once — one-read-per-poll classification wiring ─────────────────────
class _FakeClock:
    def __init__( self, t ): self.t = t
    def now_iso( self ): return self.t.isoformat()
    def monotonic( self ): return 0.0
    async def sleep( self, s ): return None


def _poll_job( tmp_path, clock, *, bridges, mtimes, owed_work_fn, notify ):
    """Fully-injected job (no real IO) driven through _poll_once — mirrors the
    test_arbiter_scenarios harness with the L1 owed_work_fn seam added."""
    return ArbiterConsumerJob(
        commons                    = _Gateway(),
        poll_seconds               = 60,
        manager_recipient          = "manager-on-duty",
        events_dir                 = str( tmp_path ),
        clock                      = clock,
        owed_work_fn               = owed_work_fn,
        notify_fn                  = lambda m, *a, **k: notify.append( m ),
        log_fn                     = lambda event, **f: None,
        bridge_discovery_fn        = lambda: dict( bridges ),
        bridge_mtime_fn            = lambda sid: mtimes.get( sid ),
        list_managers_fn           = lambda: set( bridges.keys() ),
        resolve_manager_fn         = lambda sid, declared_manager=None: {
                                         "manager_persona": None, "source": "unresolved" },
        resolve_active_managers_fn = lambda who, bridge_sessions: [ ],
        render_sink                = lambda s: None,
        snapshot_sink              = lambda s: None,
    )


class TestPollOnceWiring:

    def test_poll_classifies_and_suppresses_blocked_manager( self, tmp_path ):
        """End-to-end through _poll_once: a tapped manager whose only owed work is
        Rick-gated is NOT escalated MANAGER-DOWN — the awaiting-Rick advisory fires
        instead (proves the eval_personas set + owed_class plumbing)."""
        clock  = _FakeClock( NOW )
        notify = [ ]
        # manager bridge-discovered but STALE (older than its tap) → no liveness ACK
        bridges = { "mgr-tiberius": "Tiberius" }
        mtimes  = { "mgr-tiberius": ( NOW - datetime.timedelta( seconds=800 ) ).timestamp() }
        owed    = { "Tiberius": [ _operator() ] }
        job = _poll_job( tmp_path, clock, bridges=bridges, mtimes=mtimes,
                         owed_work_fn=lambda ps: owed, notify=notify )
        job._last_tap_at[ "Tiberius" ] = NOW - datetime.timedelta( seconds=700 )   # tapped, window elapsed
        summary = job._poll_once()
        assert summary[ "managers_down" ] == 0                       # suppressed — not a down
        assert any( "AWAITING-RICK" in m for m in notify )           # advisory fired instead


# ── reusable suppression primitives (lane 4, 2026-06-17) ─────────────────────
#    The single named home for the store-owed "do-not-escalate?" decision, so Mr
#    Radio's engagement-#7 follow-through watcher reuses it (no re-inlining, no
#    poke-path contention). owed_class_suppresses = pure predicate;
#    session_is_not_owed = single-session seam (one store read + the predicate).

from cosa.agents.heartbeat_arbiter.arbiter_job import owed_class_suppresses, NOT_OWED_CLASSES


class TestOwedClassSuppresses:
    def test_blocked_and_done_suppress( self ):
        assert owed_class_suppresses( CLASS_BLOCKED_ON_USER ) is True
        assert owed_class_suppresses( CLASS_DONE ) is True

    def test_active_and_unknown_do_not_suppress( self ):
        assert owed_class_suppresses( CLASS_ACTIVE ) is False
        assert owed_class_suppresses( CLASS_UNKNOWN ) is False       # fail-SAFE

    def test_garbage_value_does_not_suppress( self ):
        assert owed_class_suppresses( "wat" ) is False
        assert owed_class_suppresses( None ) is False

    def test_constant_membership( self ):
        assert NOT_OWED_CLASSES == ( CLASS_BLOCKED_ON_USER, CLASS_DONE )


class TestSessionIsNotOwed:
    def test_blocked_on_user_is_not_owed( self ):
        job = _job( owed_work_fn=lambda ps: { "Mgr": [ _operator() ] } )
        assert job.session_is_not_owed( "Mgr" ) is True

    def test_done_is_not_owed( self ):
        job = _job( owed_work_fn=lambda ps: { "Mgr": [ ] } )         # zero owed → DONE
        assert job.session_is_not_owed( "Mgr" ) is True

    def test_active_is_owed( self ):
        job = _job( owed_work_fn=lambda ps: { "Mgr": [ _normal() ] } )
        assert job.session_is_not_owed( "Mgr" ) is False

    def test_unwired_seam_fails_safe_to_owed( self ):
        job = _job( owed_work_fn=None )                              # UNKNOWN → not suppressed
        assert job.session_is_not_owed( "Mgr" ) is False

    def test_absent_persona_fails_safe_to_owed( self ):
        job = _job( owed_work_fn=lambda ps: { } )                    # reader returned nothing → UNKNOWN
        assert job.session_is_not_owed( "Ghost" ) is False
