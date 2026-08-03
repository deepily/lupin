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


def _job( *, owed_work_fn=None, notify=None, known_owners_fn=None, log_fn=None, hold_reader_fn=None ):
    """Bare arbiter job with no bridge liveness (bridge_mtime_fn → None), so the
    tap-ACK path always reaches the window/classification logic under test."""
    return ArbiterConsumerJob(
        commons         = _Gateway(),
        poll_seconds    = 5,
        manager_recipient = "DeclaredMgr",
        owed_work_fn    = owed_work_fn,
        known_owners_fn = known_owners_fn,
        hold_reader_fn  = hold_reader_fn,
        log_fn          = log_fn,
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

    # 262c59f6 (A) follow-up (2): the single-persona seam must ALSO thread the
    # known-persona fail-safe, else (A) is inert on this narrower path (Tiberius's
    # consistency nit). A contaminated would-be-DONE label ∉ known owners → UNKNOWN →
    # NOT suppressed (escalates); a genuinely-done KNOWN persona stays suppressed.
    def test_contaminated_label_not_suppressed_with_known_owners( self ):
        job = _job( owed_work_fn=lambda ps: { "tiberius eb4b105f": [ ] },
                    known_owners_fn=lambda: [ "tiberius", "mr radio" ] )
        assert job.session_is_not_owed( "tiberius eb4b105f" ) is False   # UNKNOWN → not suppressed

    def test_genuinely_done_known_persona_still_suppressed( self ):
        job = _job( owed_work_fn=lambda ps: { "Mr Radio": [ ] },
                    known_owners_fn=lambda: [ "mr radio" ] )
        assert job.session_is_not_owed( "Mr Radio" ) is True             # DONE ∈ known → suppressed

    def test_unwired_known_seam_is_todays_suppression( self ):
        job = _job( owed_work_fn=lambda ps: { "tiberius eb4b105f": [ ] } )   # no known_owners_fn → inert
        assert job.session_is_not_owed( "tiberius eb4b105f" ) is True        # DONE → suppressed (today's behavior)


# ── 262c59f6 H1: re-spin attribution — created_by must NOT orphan owed rows ────
#
# The 262c59f6 MANAGER-DONE false-positive fired despite 2 live in_progress rows
# owner_persona=tiberius. Leading suspect: a re-spin attribution mismatch — the
# rows were created_by the PRE-/clear session ("Tiberius 91de0c54") while the poked
# session is the re-spun eb4b105f. The store read keys on owner_persona
# (canonicalized), NOT created_by, so a re-spin (which changes ONLY created_by)
# must keep the rows attributed to the persona → CLASS_ACTIVE, never a false DONE.
# This guards _classify_owed against created_by leaking into attribution AND against
# a display-vs-canonical label mismatch (the canonicalizing read seam absorbs case /
# accent / icon so "Tiberius" resolves the "tiberius" rows).
class TestClassifyOwedRespinAttribution:

    @staticmethod
    def _canonicalizing_fn( rows ):
        """Faithful mirror of _default_owed_work_fn: query by CANONICAL owner_persona,
        drop terminal, key the OUTPUT by the raw persona requested. created_by is
        NEVER consulted (exactly as the production repo query ignores it)."""
        from lupin_mcp.persona_normalization import canonical_persona_key
        _TERMINAL = ( "done", "dropped" )
        def _fn( personas ):
            out = { }
            for p in personas:
                key = canonical_persona_key( p ) or p
                out[ p ] = [ r for r in rows
                             if canonical_persona_key( r[ "owner_persona" ] ) == key
                             and r[ "status" ] not in _TERMINAL ]
            return out
        return _fn

    def _respun_rows( self ):
        # 2 in_progress rows owned by canonical "tiberius", created_by the PRIOR
        # (pre-/clear) session id — the exact 262c59f6 ground truth (dab6cdfa +
        # a5559b49 in the field; shapes here mirror _normal()).
        return [
            { "owner_persona": "tiberius", "status": "in_progress",
              "created_by": "Tiberius 91de0c54", "gate_class": "none", "blocked_by": None },
            { "owner_persona": "tiberius", "status": "in_progress",
              "created_by": "Tiberius 91de0c54", "gate_class": "none", "blocked_by": None },
        ]

    def test_respun_manager_in_progress_rows_classify_active_not_done( self ):
        """The re-spun session's clean display label 'Tiberius' must resolve its
        'tiberius' rows (created_by the prior session) → CLASS_ACTIVE, not DONE."""
        job = _job( owed_work_fn=self._canonicalizing_fn( self._respun_rows() ) )
        assert job._classify_owed( [ "Tiberius" ], { } ) == { "Tiberius": CLASS_ACTIVE }

    def test_iconified_display_label_still_resolves_active( self ):
        """A persona label carrying the icon ('Tiberius 👑') canonicalizes to
        'tiberius' → still resolves the rows → ACTIVE (never a false DONE)."""
        job = _job( owed_work_fn=self._canonicalizing_fn( self._respun_rows() ) )
        assert job._classify_owed( [ "Tiberius 👑" ], { } ) == { "Tiberius 👑": CLASS_ACTIVE }


# ── 262c59f6 (A): known-persona fail-safe on STORE-derived DONE ────────────────
#
# Tiberius-approved belt (option A). A would-be-DONE persona (zero non-terminal owed
# rows) whose CANONICAL label is NOT among the store's known owner personas is a
# likely re-spin / label-contamination false DONE — the empty read came from a label
# that canonicalizes to a key no real persona owns ('tiberius eb4b105f' ≠ 'tiberius'),
# NOT from genuine completion. Reclassify UNKNOWN → escalate, NEVER a false
# MANAGER-DONE. A genuinely-finished KNOWN persona ('mr radio' ∈ known, zero owed)
# stays legitimately DONE (don't over-catch real completion). A degenerate (empty /
# None) known set NEVER mass-UNKNOWNs the fleet (fail-SAFE). The literal idempotence
# assert was REJECTED: every legit display label is non-idempotent by design and an
# already-lowercased suffix slips through (evidence in the 262c59f6 characterization).
class TestClassifyOwedKnownOwnerFailSafe:

    def test_contaminated_label_would_be_done_downgrades_to_unknown( self ):
        """Zero owed rows on a contaminated label → would-be DONE; canonical
        'tiberius eb4b105f' ∉ known owners → UNKNOWN (escalate), not a false DONE."""
        job = _job( owed_work_fn=lambda ps: { "tiberius eb4b105f": [ ] } )
        out = job._classify_owed( [ "tiberius eb4b105f" ], { },
                                  known_owners={ "tiberius", "mr radio" } )
        assert out == { "tiberius eb4b105f": CLASS_UNKNOWN }

    def test_genuinely_done_known_persona_stays_done( self ):
        """A REAL persona ('Mr Radio' → 'mr radio' ∈ known) with zero owed rows is
        genuinely finished → stays DONE (the fail-safe must not over-catch)."""
        job = _job( owed_work_fn=lambda ps: { "Mr Radio": [ ] } )
        out = job._classify_owed( [ "Mr Radio" ], { }, known_owners={ "mr radio" } )
        assert out == { "Mr Radio": CLASS_DONE }

    def test_empty_known_owners_never_downgrades( self ):
        """Degenerate known set (empty) → NEVER mass-UNKNOWN the fleet → today's
        DONE stands (fail-SAFE: the belt only fires with a real known-owner set)."""
        job = _job( owed_work_fn=lambda ps: { "tiberius eb4b105f": [ ] } )
        out = job._classify_owed( [ "tiberius eb4b105f" ], { }, known_owners=set() )
        assert out == { "tiberius eb4b105f": CLASS_DONE }

    def test_none_known_owners_is_todays_behavior( self ):
        """known_owners omitted (default None) → inert → today's store-only DONE."""
        job = _job( owed_work_fn=lambda ps: { "tiberius eb4b105f": [ ] } )
        out = job._classify_owed( [ "tiberius eb4b105f" ], { } )
        assert out == { "tiberius eb4b105f": CLASS_DONE }

    def test_active_persona_absent_from_known_is_untouched( self ):
        """Only STORE-derived DONE downgrades; an ACTIVE persona missing from the
        known set is NOT touched (the belt guards false-DONE, not false-ACTIVE)."""
        job = _job( owed_work_fn=lambda ps: { "ghost worker": [ _normal() ] } )
        out = job._classify_owed( [ "ghost worker" ], { }, known_owners={ "mr radio" } )
        assert out == { "ghost worker": CLASS_ACTIVE }

    def test_known_owners_canonicalized_before_compare( self ):
        """A display-form entry in the known set ('Mr Radio') is canonicalized before
        the membership test → matches the canonicalized persona → stays DONE."""
        job = _job( owed_work_fn=lambda ps: { "mr radio": [ ] } )
        out = job._classify_owed( [ "mr radio" ], { }, known_owners={ "Mr Radio" } )
        assert out == { "mr radio": CLASS_DONE }


# ── 262c59f6 (A): _read_known_owners seam (swallow-safe) ───────────────────────
class TestReadKnownOwners:

    def test_unwired_seam_returns_none( self ):
        """No known_owners_fn wired → None (inert → _classify_owed downgrade never
        fires → today's behavior)."""
        assert _job()._read_known_owners() is None

    def test_wired_returns_canonical_filtered_set( self ):
        """Wired reader → a set of CANONICAL owner keys; falsy entries dropped."""
        job = _job( known_owners_fn=lambda: [ "Mr Radio", "Tiberius", None, "" ] )
        assert job._read_known_owners() == { "mr radio", "tiberius" }

    def test_read_raises_swallowed_to_none( self ):
        """A raising reader is swallowed (observer invariant) → None → fail-SAFE."""
        def _boom(): raise RuntimeError( "store hiccup" )
        assert _job( known_owners_fn=_boom )._read_known_owners() is None


# ── de3c5b87 + 33949e83 (re-scoped): MANAGER-DONE/DOWN emission diagnostics ────
#
# Ground-truth-before-fix instrument (Tiberius-approved re-scope of de3c5b87 after
# Cheech's live /state capture DISPROVED the session-suffix-contamination premise).
# At every MANAGER-DONE (case-17) and MANAGER-DOWN (case-9) emission, log the exact
# inputs so the true root of a false-fire is captured deterministically on the next
# occurrence — WIDENED to serve BOTH open bugs in one instrument:
#   • de3c5b87 (false MANAGER-DONE): fed_label + canonical(fed_label) +
#     label_is_canonical + owed_class + owed_read_ok + store_row_count + hold work_owed
#     → distinguishes a label→canonical mismatch from a genuine empty read from a
#     hold-override (work_owed=false) from a degraded/raised read.
#   • 33949e83 (false MANAGER-DOWN during the :7999 bog): owed_read_ok (store-read
#     health) + last_activity vs tapped_at → confirms whether the reads were degraded.
# Pure telemetry via the swallow-safe _log seam — NO control-flow effect.
class TestManagerAckDiagnostics:

    @staticmethod
    def _capturing( **kw ):
        logs = [ ]
        job  = _job( log_fn=lambda event, **f: logs.append( ( event, f ) ), **kw )
        return job, logs

    @staticmethod
    def _diags( logs ):
        return [ f for e, f in logs if e == "arbiter_manager_ack_diagnostic" ]

    def test_manager_done_emits_diagnostic( self ):
        """case-17 MANAGER-DONE fires the diagnostic with de3c5b87's fields: the
        fed_label + its canonical form + owed_read_ok + store_row_count."""
        job, logs = self._capturing( owed_work_fn=lambda ps: { "Mgr": [ ] } )
        job._last_tap_at[ "Mgr" ] = NOW
        job._check_manager_acks( LATE, [ ], { }, [ ], owed_class={ "Mgr": CLASS_DONE },
                                 owed_items={ "Mgr": [ ] } )
        diag = self._diags( logs )
        assert len( diag ) == 1
        d = diag[ 0 ]
        assert d[ "verdict" ] == "manager_done"
        assert d[ "fed_label" ] == "Mgr"
        assert d[ "canonical_label" ] == "mgr"
        assert d[ "label_is_canonical" ] is False        # 'Mgr' ≠ 'mgr' → a real contamination would flag here
        assert d[ "owed_class" ] == CLASS_DONE
        assert d[ "owed_read_ok" ] is True
        assert d[ "store_row_count" ] == 0
        assert d[ "hold_work_owed" ] is None             # no hold-reader wired
        assert d[ "session_id" ] is None                 # empty fleet_view → sid not resolved
        assert d[ "last_activity" ] is None              # no activity candidate

    def test_manager_down_emits_diagnostic_with_read_health( self ):
        """case-9 MANAGER-DOWN fires the diagnostic capturing 33949e83's signal:
        owed_read_ok False (store read degraded/raised → owed_items None) + a stale
        last_activity older than tapped_at. Uses a CANONICAL label → is_canonical True."""
        who = [ { "persona_name": "mr radio",
                  "last_post_ts": ( NOW - datetime.timedelta( seconds=100 ) ).isoformat() } ]
        fv  = { "s1": { "session_id": "s1", "persona": "mr radio" } }
        job, logs = self._capturing(
            owed_work_fn=lambda ps: { "mr radio": [ _normal() ] },
            hold_reader_fn=lambda sid: { "work_owed": True } )
        job._last_tap_at[ "mr radio" ] = NOW
        down = job._check_manager_acks( LATE, who, fv, [ ], owed_class={ "mr radio": CLASS_ACTIVE },
                                        owed_items=None )
        assert down == 1
        diag = self._diags( logs )
        assert len( diag ) == 1
        d = diag[ 0 ]
        assert d[ "verdict" ] == "manager_down"
        assert d[ "label_is_canonical" ] is True         # 'mr radio' == canonical
        assert d[ "owed_read_ok" ] is False              # owed_items None → store read degraded/raised
        assert d[ "store_row_count" ] is None
        assert d[ "session_id" ] == "s1"                 # resolved from fleet_view
        assert d[ "hold_work_owed" ] is True             # read from the wired hold-reader
        assert d[ "last_activity" ] is not None and d[ "secs_since_activity" ] >= 100

    def test_diagnostic_hold_reader_raise_swallowed( self ):
        """A raising hold-reader in the diagnostic is swallowed → hold_work_owed None
        (telemetry never crashes the poll — observer invariant)."""
        def _boom( sid ): raise RuntimeError( "hold hiccup" )
        fv  = { "s1": { "session_id": "s1", "persona": "Mgr" } }
        job, logs = self._capturing( owed_work_fn=lambda ps: { "Mgr": [ ] },
                                     hold_reader_fn=_boom )
        job._last_tap_at[ "Mgr" ] = NOW
        job._check_manager_acks( LATE, [ ], fv, [ ], owed_class={ "Mgr": CLASS_DONE },
                                 owed_items={ "Mgr": [ ] } )
        d = self._diags( logs )[ 0 ]
        assert d[ "hold_work_owed" ] is None and d[ "session_id" ] == "s1"

    def test_no_diagnostic_when_acked_or_window_open( self ):
        """No emission when the manager acked (fresh activity ≥ tap) or the ack
        window has not elapsed — the diagnostic fires ONLY at an actual emission."""
        # acked: fresh activity after tap
        who = [ { "persona_name": "Mgr", "last_post_ts": ( LATE ).isoformat() } ]
        job, logs = self._capturing( owed_work_fn=lambda ps: { "Mgr": [ ] } )
        job._last_tap_at[ "Mgr" ] = NOW
        job._check_manager_acks( LATE, who, { }, [ ], owed_class={ "Mgr": CLASS_DONE },
                                 owed_items={ "Mgr": [ ] } )
        assert self._diags( logs ) == [ ]
        # window not elapsed
        job2, logs2 = self._capturing( owed_work_fn=lambda ps: { "Mgr": [ ] } )
        job2._last_tap_at[ "Mgr" ] = NOW
        job2._check_manager_acks( NOW + datetime.timedelta( seconds=1 ), [ ], { }, [ ],
                                  owed_class={ "Mgr": CLASS_DONE }, owed_items={ "Mgr": [ ] } )
        assert self._diags( logs2 ) == [ ]

    def test_diagnostic_fires_once_per_episode( self ):
        """Advisory-once: a manager that stays DONE across polls emits the case-17
        diagnostic exactly ONCE (tied to the emission, not per-poll — no spam)."""
        job, logs = self._capturing( owed_work_fn=lambda ps: { "Mgr": [ ] } )
        job._last_tap_at[ "Mgr" ] = NOW
        for _ in range( 3 ):
            job._check_manager_acks( LATE, [ ], { }, [ ], owed_class={ "Mgr": CLASS_DONE },
                                     owed_items={ "Mgr": [ ] } )
        assert len( self._diags( logs ) ) == 1

    def test_blocked_on_user_emits_no_diagnostic( self ):
        """The awaiting-Rick (case-16) suppression is NOT under investigation — it
        emits NO ack-diagnostic (scope stays the two false-positive verdicts)."""
        job, logs = self._capturing( owed_work_fn=lambda ps: { "Mgr": [ _operator() ] } )
        job._last_tap_at[ "Mgr" ] = NOW
        job._check_manager_acks( LATE, [ ], { }, [ ], owed_class={ "Mgr": CLASS_BLOCKED_ON_USER },
                                 owed_items={ "Mgr": [ _operator() ] } )
        assert self._diags( logs ) == [ ]

    def test_diagnostic_sid_unresolved_when_no_matching_row( self ):
        """The sid-resolution loop exhausts without a break when NO fleet_view row
        matches the manager (or the row is non-dict) → session_id stays None."""
        fv = { "o": { "session_id": "o1", "persona": "Other" }, "bad": "not-a-dict" }
        job, logs = self._capturing( owed_work_fn=lambda ps: { "Mgr": [ ] } )
        job._last_tap_at[ "Mgr" ] = NOW
        job._check_manager_acks( LATE, [ ], fv, [ ], owed_class={ "Mgr": CLASS_DONE },
                                 owed_items={ "Mgr": [ ] } )
        d = self._diags( logs )[ 0 ]
        assert d[ "session_id" ] is None


# ── 33949e83: store-health gate — suppress MANAGER-DOWN on a self-observed outage ──
#
# The :7999/store bog on 2026-07-01 ~11:40-11:52 swallowed tap-acks → the arbiter's
# 600s-since-tap timer expired for BOTH live managers within 1s → false MANAGER-DOWN
# to Rick. Root IS known (infra outage, not darkness). Fix: when the arbiter's OWN
# owed store read is degraded THIS poll (it RAISED / timed-out → owed_items None while
# the seam is wired AND personas exist), the missing-tap-ACK reading is untrustworthy
# → SUPPRESS the MANAGER-DOWN escalation (UNKNOWN-INFRA, not dark) and do NOT set the
# escalate-once flag → re-arms on the next clean read window.
class TestStoreReadDegraded:

    def test_unwired_seam_not_degraded( self ):
        """No owed seam wired → not 'degraded' (inert ≠ outage)."""
        assert _job( owed_work_fn=None )._store_read_degraded( None, [ "Mgr" ] ) is False

    def test_no_personas_not_degraded( self ):
        """Nothing to read (empty / all-falsy personas) → not degraded."""
        job = _job( owed_work_fn=lambda ps: { } )
        assert job._store_read_degraded( None, [ ] ) is False
        assert job._store_read_degraded( None, [ None, "" ] ) is False

    def test_wired_personas_none_result_is_degraded( self ):
        """Seam wired + ≥1 persona but None result → the read RAISED/timed-out → degraded."""
        assert _job( owed_work_fn=lambda ps: { } )._store_read_degraded( None, [ "Mgr" ] ) is True

    def test_wired_personas_present_result_not_degraded( self ):
        """A successful read (dict result) → healthy, not degraded."""
        assert _job( owed_work_fn=lambda ps: { } )._store_read_degraded( { "Mgr": [ ] }, [ "Mgr" ] ) is False


class TestManagerDownStoreHealthGate:

    @staticmethod
    def _cap( **kw ):
        logs, routes = [ ], [ ]
        job = _job( log_fn=lambda e, **f: logs.append( ( e, f ) ),
                    notify=lambda m, *a, **k: routes.append( m ), **kw )
        return job, logs, routes

    def test_manager_down_suppressed_when_store_degraded( self ):
        """A tapped, past-window, UNKNOWN manager during a degraded read → NO
        MANAGER-DOWN: down count 0, no Rick escalation, escalate-once flag NOT set
        (re-arms), and a 'manager_down_suppressed_infra' diagnostic is logged."""
        job, logs, routes = self._cap( owed_work_fn=lambda ps: { } )
        job._last_tap_at[ "Mgr" ] = NOW
        down = job._check_manager_acks( LATE, [ ], { }, [ ], owed_class={ "Mgr": CLASS_UNKNOWN },
                                        owed_items=None, store_read_degraded=True )
        assert down == 0
        assert routes == [ ]                                          # no MANAGER-DOWN escalation to Rick
        assert "Mgr" not in job._manager_down_escalated              # flag NOT set → re-arms on clean poll
        diag = [ f for e, f in logs if e == "arbiter_manager_ack_diagnostic" ]
        assert len( diag ) == 1 and diag[ 0 ][ "verdict" ] == "manager_down_suppressed_infra"

    def test_manager_down_fires_when_store_healthy( self ):
        """Store healthy (not degraded) → today's MANAGER-DOWN still fires (the gate
        only suppresses on a self-observed outage — never silences a real down)."""
        job, logs, routes = self._cap( owed_work_fn=lambda ps: { "Mgr": [ _normal() ] } )
        job._last_tap_at[ "Mgr" ] = NOW
        down = job._check_manager_acks( LATE, [ ], { }, [ ], owed_class={ "Mgr": CLASS_ACTIVE },
                                        owed_items={ "Mgr": [ _normal() ] }, store_read_degraded=False )
        assert down == 1
        assert "Mgr" in job._manager_down_escalated
        assert any( "MANAGER-DOWN" in m for m in routes )

    def test_suppressed_then_rearms_on_clean_poll( self ):
        """Re-arm: a degraded poll suppresses (flag unset); the next CLEAN poll with
        the manager still unacked + ACTIVE escalates (only-after-a-clean-read-window)."""
        job, logs, routes = self._cap( owed_work_fn=lambda ps: { "Mgr": [ _normal() ] } )
        job._last_tap_at[ "Mgr" ] = NOW
        assert job._check_manager_acks( LATE, [ ], { }, [ ], owed_class={ "Mgr": CLASS_UNKNOWN },
                                        owed_items=None, store_read_degraded=True ) == 0
        assert job._check_manager_acks( LATE, [ ], { }, [ ], owed_class={ "Mgr": CLASS_ACTIVE },
                                        owed_items={ "Mgr": [ _normal() ] }, store_read_degraded=False ) == 1


# ---------------------------------------------------------------------------
# PARKED-STATUS (2026-07-19) — R3 WIRING guard (Krishna, seat 2)
# ---------------------------------------------------------------------------
#
# Rachel's parity gate proves the PREDICATE against in-memory SQLite; it never
# builds an arbiter poll, so this wiring choice is structurally invisible to it.
# The mutant guarded here READS LIKE A TIGHTENING and is a silent catastrophe:
# swapping hide_parked=True for owed_only=True narrows the arbiter to
# queued/in_progress and blinds it to every `blocked` row — and the blocked rows
# are exactly what its deadlock-corroboration ring is built from.
class TestDefaultOwedWorkFnParkWiring:

    @staticmethod
    def _capture( monkeypatch ):
        """Patch the repo + get_db seams; return the list of query_tasks kwargs."""
        from contextlib import contextmanager
        import cosa.rest.db.repositories.task_repository as repo_mod
        import cosa.rest.db.database as db_mod
        calls = [ ]

        class _FakeRepo:
            def __init__( self, session ): pass
            def query_tasks( self, **kwargs ):
                calls.append( kwargs )
                return [ ]

        @contextmanager
        def _fake_get_db():
            yield object()

        monkeypatch.setattr( db_mod, "get_db", _fake_get_db )
        monkeypatch.setattr( repo_mod, "TaskRepository", _FakeRepo )
        return calls

    def test_suppresses_park_active_without_narrowing_the_status_set( self, monkeypatch ):
        """MUTANT GUARD (b): swap hide_parked=True for owed_only=True and this
        goes RED. The arbiter selects ALL non-terminal rows, which already
        contains parked ones, so SUPPRESSION alone is both sufficient and
        correct — admission would drop the blocked rows it reasons over."""
        from cosa.agents.heartbeat_arbiter.arbiter_job import _default_owed_work_fn
        calls = self._capture( monkeypatch )
        _default_owed_work_fn( [ "Krishna" ] )
        assert calls, "expected one query_tasks call per persona"
        assert calls[ 0 ][ "hide_parked" ] is True
        assert calls[ 0 ].get( "owed_only", False ) is False, (
            "the arbiter must NOT use owed_only — it would blind the deadlock "
            "ring to every `blocked` row while reading like a tightening"
        )

    def test_one_clock_is_shared_across_every_persona_in_the_poll( self, monkeypatch ):
        """A per-persona clock read could classify two personas against different
        instants and straddle a park-expiry boundary mid-poll, making readers 2
        and 3 disagree for a reason no test reproduces and no log explains."""
        from cosa.agents.heartbeat_arbiter.arbiter_job import _default_owed_work_fn
        calls = self._capture( monkeypatch )
        _default_owed_work_fn( [ "Krishna", "Rachel", "Clayton" ] )
        assert len( calls ) == 3
        stamps = { c[ "now" ] for c in calls }
        assert len( stamps ) == 1, f"expected ONE shared instant, got {stamps}"
        assert next( iter( stamps ) ).tzinfo is not None, "the shared clock must be tz-aware UTC"
