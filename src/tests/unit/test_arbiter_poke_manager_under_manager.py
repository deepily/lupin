#!/usr/bin/env python3
"""
Row e2029f7f — a declared MANAGER currently serving UNDER another manager must not
be told to do manager things.

The stuck-poke body forked on `view["role"]` alone, so a declared manager working
a lane under someone else was told to "tap/assign your crew (staff up …)" — moves
that seat cannot make. The fix ANDs the wording fork with `view["manager"]` being
empty. `manager` is populated ONLY from lineage and is never guessed
(fleet_render.build_snapshot), so "declared manager currently serving under
someone" == role=="manager" AND manager non-empty.

WORDING ONLY. `role` is untouched, so the manager-staleness tier (which gates on
`row["role"] != "manager"`) keeps exactly the population it had before — that is
what cases 1 and 2 below pin, and case 3 is the worker-side regression guard.

Rick 2026-06-11 (fleet_render.py docstring): a DECLARED manager badges manager
"even before its first spawn" — so this fix must NOT key on spawned sessions.

Venue: :7999-eligible / local — pure + mocked, no server.
"""
import datetime
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob


NOW = datetime.datetime( 2026, 8, 18, 18, 0, 0, tzinfo=datetime.timezone.utc )

MANAGER_PHRASE = "tap/assign your crew"
WORKER_PHRASE  = "or resume. (Non-destructive nudge.)"


class _GW:
    def __init__( self ):
        self.sent = [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, r, b, metadata=None ): self.sent.append( ( r, b ) )
    def post( self, t, b ): pass
    def read( self, topic, since=None, limit=50 ): return [ ]


def _bare_job():
    """A body-formatter-only job (skips the heavy __init__), goal echoes muted so
    the assertion sees the BODY fork alone."""
    j = ArbiterConsumerJob.__new__( ArbiterConsumerJob )
    j.manager_goal_line = ""
    j.worker_goal_line  = ""
    j.manager_stale_poke_threshold_seconds = 2700
    return j


def _tier_job( gw ):
    return ArbiterConsumerJob(
        commons           = gw,
        poll_seconds      = 5,
        manager_recipient = "DeclaredMgr",
        notify_fn         = lambda *a, **k: None,
        log_fn            = lambda *a, **k: None,
    )


def _row( sid, role, manager, persona=None, age=3000 ):
    return { "session_id": sid, "persona": persona or sid, "state": "working",
             "holding_on": "none", "stuck": False, "role": role, "manager": manager,
             "liveness": { "freshest_age_s": age, "verdict": "stale 50m" } }


def _snap( *rows ):
    return { "generated_at": NOW.isoformat(), "session_count": len( rows ),
             "sessions": list( rows ) }


def _in_staleness_tier( row ):
    """Did the REAL tier fire for this row? (not a re-implementation of the gate)"""
    gw = _GW()
    return _tier_job( gw )._check_manager_staleness( _snap( row ), NOW, active_managers=[ ] ) == 1


# ── case 1: a fresh manager (declared, no lineage parent) ────────────────────

def test_fresh_manager_gets_manager_wording_and_stays_in_tier():
    row = _row( "m1", "manager", None, persona="Cheech" )
    body = _bare_job()._format_poke( row )
    assert MANAGER_PHRASE in body
    assert "don't resume the work yourself" in body
    assert WORKER_PHRASE not in body
    assert _in_staleness_tier( row )                       # regression guard: tier unchanged


# ── case 2: THE DEFECT — a declared manager serving under another manager ────

def test_manager_serving_under_a_manager_gets_worker_wording_and_stays_in_tier():
    row = _row( "m2", "manager", "María", persona="Rio" )
    body = _bare_job()._format_poke( row )
    assert WORKER_PHRASE in body                           # RED before the fix
    assert MANAGER_PHRASE not in body
    assert "don't resume the work yourself" not in body
    assert _in_staleness_tier( row )                       # wording only — tier untouched


# ── case 3: an ordinary worker under a manager ───────────────────────────────

def test_plain_worker_gets_worker_wording_and_is_out_of_tier():
    row = _row( "w1", "worker", "María", persona="Sam" )
    body = _bare_job()._format_poke( row )
    assert WORKER_PHRASE in body
    assert MANAGER_PHRASE not in body
    assert not _in_staleness_tier( row )                   # regression guard: workers stay out
