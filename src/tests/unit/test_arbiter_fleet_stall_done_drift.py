#!/usr/bin/env python3
"""
RED-first characterization + regression for bug d2a4c040 — the #11 (WHOLE-FLEET-
STALL) owed_class drift.

THE DRIFT (pre-existing; surfaced by Cheech during the 25ba173e review):
`_has_live_owed_work` (arbiter_job.py) HAND-ROLLS its owed-class exclusion and
excludes ONLY CLASS_BLOCKED_ON_USER — NOT CLASS_DONE — even though the shared
predicate `owed_class_suppresses` (NOT_OWED_CLASSES) and its docstring name #11 a
consumer that honors DONE, and the sibling single-session seam
`session_is_not_owed` already honors DONE.

RULING (Rachel, 2026-06-29): BUG — a latent FALSE-POSITIVE. A done-but-alive,
non-progressing fleet (sessions finished, frozen progress signature, not yet
reaped) trips a "WHOLE-FLEET-STALL ... with work owed" escalation even though NO
work is owed. The fix routes `_has_live_owed_work` through the shared
`owed_class_suppresses` predicate so the hand-roll, the predicate, the sibling
seam, and both docstrings agree.

This file is structured RED-first:
  - TestCharacterizationCurrentBehavior PINS the CORRECTED behavior (DONE excluded)
    — it FAILS on the un-fixed hand-roll and PASSES after the fix.
  - The direction/fail-safe tests pin the surrounding invariants so the fix cannot
    over-reach (ACTIVE still stalls; UNKNOWN/unwired still fail-SAFE; the new
    BLOCKED_ON_USER→DONE re-label is the only added inclusion path).
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


NOW = datetime.datetime( 2026, 6, 29, 12, 0, 0, tzinfo=datetime.timezone.utc )


class _Gateway:
    def __init__( self ):
        self.sent, self.posts = [ ], [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, recipient, body, metadata=None ): self.sent.append( ( recipient, body ) )
    def post( self, topic, body ): self.posts.append( ( topic, body ) )
    def read( self, topic, since=None, limit=50 ): return [ ]


def _job( *, notify=None ):
    return ArbiterConsumerJob(
        commons           = _Gateway(),
        poll_seconds      = 5,
        manager_recipient = "DeclaredMgr",
        bridge_mtime_fn   = lambda sid: None,
        notify_fn         = notify or ( lambda *a, **k: None ),
    )


def _live( sid, persona, state="working" ):
    """An alive session in a stall-eligible state (working/stuck/holding)."""
    return { "session_id": sid, "persona": persona, "state": state, "alive": True, "holding_on": "none" }


# ── _has_live_owed_work — the DONE exclusion (RED-first: fails pre-fix) ───────
class TestHasLiveOwedWorkDoneExclusion:

    def test_done_session_is_excluded_like_blocked_on_user( self ):
        """The core of the bug: a CLASS_DONE alive session owes NO work, so it must
        NOT count as live owed work — exactly as BLOCKED_ON_USER does not. On the
        un-fixed hand-roll this returns True (drift); the fix flips it to False."""
        fv = { "s1": _live( "s1", "Mgr", "holding" ) }
        assert ArbiterConsumerJob._has_live_owed_work( fv, { "Mgr": CLASS_DONE } ) is False

    def test_done_among_only_done_is_false( self ):
        fv = { "s1": _live( "s1", "A", "working" ), "s2": _live( "s2", "B", "stuck" ) }
        oc = { "A": CLASS_DONE, "B": CLASS_DONE }
        assert ArbiterConsumerJob._has_live_owed_work( fv, oc ) is False

    def test_active_alongside_done_still_true( self ):
        """One genuinely-ACTIVE live session is still live owed work even if a peer
        is DONE — the fix must not suppress the whole fleet."""
        fv = { "s1": _live( "s1", "Done", "holding" ), "s2": _live( "s2", "Active" ) }
        oc = { "Done": CLASS_DONE, "Active": CLASS_ACTIVE }
        assert ArbiterConsumerJob._has_live_owed_work( fv, oc ) is True


# ── direction / fail-safe invariants (the fix must not over-reach) ───────────
class TestSuppressionInvariantsPreserved:

    def test_active_still_counts( self ):
        fv = { "s1": _live( "s1", "Mgr" ) }
        assert ArbiterConsumerJob._has_live_owed_work( fv, { "Mgr": CLASS_ACTIVE } ) is True

    def test_blocked_on_user_still_excluded( self ):
        fv = { "s1": _live( "s1", "Mgr", "holding" ) }
        assert ArbiterConsumerJob._has_live_owed_work( fv, { "Mgr": CLASS_BLOCKED_ON_USER } ) is False

    def test_unknown_fails_safe_to_owed( self ):
        # UNKNOWN must NEVER suppress — a store hiccup must not silence a real stall
        fv = { "s1": _live( "s1", "Mgr" ) }
        assert ArbiterConsumerJob._has_live_owed_work( fv, { "Mgr": CLASS_UNKNOWN } ) is True

    def test_no_owed_class_preserves_legacy_behavior( self ):
        fv = { "s1": _live( "s1", "Mgr", "holding" ) }
        assert ArbiterConsumerJob._has_live_owed_work( fv ) is True            # seam unwired → counts

    def test_empty_owed_class_preserves_legacy_behavior( self ):
        fv = { "s1": _live( "s1", "Mgr", "holding" ) }
        assert ArbiterConsumerJob._has_live_owed_work( fv, { } ) is True       # absent class → counts

    def test_dead_done_session_never_counts( self ):
        fv = { "s1": { "session_id": "s1", "persona": "Mgr", "state": "working", "alive": False } }
        assert ArbiterConsumerJob._has_live_owed_work( fv, { "Mgr": CLASS_DONE } ) is False

    def test_session_without_persona_counts_when_live( self ):
        fv = { "s1": { "session_id": "s1", "state": "working", "alive": True } }
        assert ArbiterConsumerJob._has_live_owed_work( fv, { } ) is True


# ── _check_fleet_stall — the end-to-end false-positive is removed ────────────
class TestFleetStallDoneNoLongerFalseFires:

    def test_done_only_fleet_does_not_false_stall( self ):
        """A done-but-alive frozen fleet must NOT fire WHOLE-FLEET-STALL — there is
        no owed work to stall on. Pre-fix this fired (out==1, false positive)."""
        escal = [ ]
        job   = _job( notify=lambda m, *a, **k: escal.append( m ) )
        fv    = { "s1": _live( "s1", "Mgr", "holding" ) }
        oc    = { "Mgr": CLASS_DONE }
        job._check_fleet_stall( fv, NOW, [ ], owed_class=oc )                              # arm timer
        out = job._check_fleet_stall( fv, NOW + datetime.timedelta( seconds=2000 ), [ ], owed_class=oc )
        assert out == 0 and escal == [ ]

    def test_active_fleet_still_stalls_past_window( self ):
        """Guard the other direction: a genuinely-ACTIVE frozen fleet still fires."""
        escal = [ ]
        job   = _job( notify=lambda m, *a, **k: escal.append( m ) )
        fv    = { "s1": _live( "s1", "Mgr" ) }
        oc    = { "Mgr": CLASS_ACTIVE }
        job._check_fleet_stall( fv, NOW, [ ], owed_class=oc )
        out = job._check_fleet_stall( fv, NOW + datetime.timedelta( seconds=2000 ), [ ], owed_class=oc )
        assert out == 1 and "WHOLE-FLEET-STALL" in escal[ 0 ]


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
